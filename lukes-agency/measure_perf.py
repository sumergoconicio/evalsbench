#!/usr/bin/env python3
"""Live perf measurement for the hybrid+DSpark server on port 2468.

Measures per-request: TTFT (first streamed token), completion tokens,
decode tok/s (tokens / (wall - ttft)) and total tok/s (tokens / wall),
across prompt types; and per-phase DSpark acceptance rate from the vLLM
/metrics spec-decode counters (accepted/draft tokens, drafts emitted,
accepted-per-draft-batch).

Usage:
  python3 measure_perf.py [--mode off|on] [--reps 3] [--url ...] [--model ...]
"""

import argparse
import json
import re
import sys
import time
import urllib.request


def metrics_counters(url):
    base = url[: url.rfind("/")] + "/metrics"
    with urllib.request.urlopen(base, timeout=30) as r:
        text = r.read().decode("utf-8", "replace")
    out = {}
    for m in re.finditer(
        r"^vllm:spec_decode_num_(accepted_tokens|draft_tokens|drafts)_total\{[^}]*\}\s+([0-9.]+)",
        text, re.M):
        out[m.group(1)] = out.get(m.group(1), 0.0) + float(m.group(2))
    return out


def stream_once(url, payload, timeout=600):
    """Stream one chat completion; return ttft, tokens, wall, finish, content_head."""
    req = urllib.request.Request(url + "/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    started = time.monotonic()
    first_ts = None
    content = ""
    usage = {}
    finish = None
    resp = urllib.request.urlopen(req, timeout=timeout)
    buf = b""

    def process_lines(data):
        nonlocal buf, first_ts, content, usage, finish
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            handle(line)

    def handle(line):
        nonlocal first_ts, content, usage, finish
        line = line.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            return
        payload_line = line[5:].strip()
        if payload_line == "[DONE]":
            return
        try:
            ev = json.loads(payload_line)
        except Exception:
            return
        if first_ts is None:
            first_ts = time.monotonic()
        ch = ev.get("choices") or []
        if ch:
            if ch[0].get("finish_reason"):
                finish = ch[0]["finish_reason"]
            d = ch[0].get("delta") or {}
            if d.get("content"):
                content += d["content"]
        if ev.get("usage"):
            usage = ev["usage"]

    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        process_lines(chunk)
    if buf:
        handle(buf)  # trailing data line without a final newline (common SSE end)
    wall = time.monotonic() - started
    if first_ts is None:
        first_ts = time.monotonic()
    comp = int(usage.get("completion_tokens", 0) or 0)
    return {
        "ttft": (first_ts - started),
        "completion_tokens": comp,
        "wall": wall,
        "decode_tokps": round(comp / (wall - (first_ts - started)), 2) if comp and (wall - (first_ts - started)) > 0.05 else None,
        "total_tokps": round(comp / wall, 2) if comp else None,
        "finish": finish,
        "content_head": content[:80],
        "wall": wall,
    }


PROMPTS = {
    # short tool-call round (agency-style)
    "tool": {"messages": [{"role": "user", "content": "What department is Alice Chen in?"}],
             "tools": [{"type": "function", "function": {"name": "lookup_employee",
                        "description": "Find a specific person by name, employee ID, or email.",
                        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": []}}}],
             "tool_choice": "auto", "max_tokens": 256},
    # reasoning-heavy chain (medium thinking shows token burn)
    "reason": {"messages": [{"role": "user", "content": "Minicorp has 4 engineers and 3 support agents. Alice Chen is an engineer reporting to Bob Martinez (Team Lead of Platform, who reports to Dana Smith, Head of Engineering). Carol Nguyen leads Support. Bob Martinez has 2 directs: Alice and Evan. Who should a medium 'Budget sign-off' ticket be assigned to? State the chain of command you used."}],
             "max_tokens": 1024},
    # long general-content decode (essay)
    "essay": {"messages": [{"role": "user", "content": "Write a 350-word essay on why speculative decoding is useful for local LLM serving. Cover draft models, acceptance rates, and practical trade-offs."}],
             "max_tokens": 768},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["off", "on"], default="on")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--url", default="http://localhost:2468/v1")
    ap.add_argument("--model", default="qwen3.8-dense")
    ap.add_argument("--max-tokens", type=int, default=16384,
                    help="generation cap, reasoning+answer combined (default 16K)")
    args = ap.parse_args()

    if args.mode == "off":
        tk = {"enable_thinking": False}
    else:
        tk = {"enable_thinking": True}  # no effort -> froggeric medium default

    m0 = metrics_counters(args.url)
    print(f"### PHASE mode={args.mode} reps={args.reps} "
          f"(drafts={int(m0.get('drafts',0))} draft_tok={int(m0.get('draft_tokens',0))} acc_tok={int(m0.get('accepted_tokens',0))})")

    results = {k: [] for k in PROMPTS}
    for name, p in PROMPTS.items():
        print(f"\n--- {name} ---")
        for i in range(args.reps):
            pload = {**p, "model": args.model, "temperature": 0,
                     "max_tokens": args.max_tokens,
                     "stream": True, "stream_options": {"include_usage": True},
                     "chat_template_kwargs": tk}
            r = stream_once(args.url, pload)
            results[name].append(r)
            print(f"  rep{i+1}: ttft={r['ttft']:.2f}s wall={r['wall']:.2f}s comp={r['completion_tokens']} "
                  f"decode={r['decode_tokps']} tok/s total={r['total_tokps']} tok/s "
                  f"finish={r['finish']} head={r['content_head']!r}")

    m1 = metrics_counters(args.url)
    dacc = m1.get("accepted_tokens", 0) - m0.get("accepted_tokens", 0)
    ddraft = m1.get("draft_tokens", 0) - m0.get("draft_tokens", 0)
    ddrafts = m1.get("drafts", 0) - m0.get("drafts", 0)
    print("\n### PHASE SUMMARY mode=" + args.mode)
    for name, rs in results.items():
        ttfts = sorted(r["ttft"] for r in rs)
        decs = [r["decode_tokps"] for r in rs if r["decode_tokps"]]
        tots = [r["total_tokps"] for r in rs if r["total_tokps"]]
        comps = [r["completion_tokens"] for r in rs]
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
        print(f"  {name}: ttft_med={med(ttfts):.2f}s (range {ttfts[0]:.2f}-{ttfts[-1]:.2f}) "
              f"decode_tokps_med={med(decs)} total_tokps_med={med(tots)} "
              f"comp_tokens_med={med(comps)}")
    print(f"### DSPARK ACCEPTANCE mode={args.mode}: "
          f"accepted={dacc:.0f} draft_tokens={ddraft:.0f} drafts={ddrafts:.0f} "
          f"accept_rate={round(dacc/ddraft,3) if ddraft else 'n/a'} "
          f"accepted_per_draft_batch={round(dacc/ddrafts,2) if ddrafts else 'n/a'} "
          f"(k=7 +1 bonus)")


if __name__ == "__main__":
    sys.exit(main())
