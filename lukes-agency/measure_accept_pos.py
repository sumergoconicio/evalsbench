#!/usr/bin/env python3
"""Measure DSpark per-position acceptance and propose ideal k.

Samples N varied prompts at temperature 0 (thinking on, medium), snapshots the
vLLM per-position spec-decode counters before/after, then builds the acceptance
survival curve S(i) = P(run length >= i) and evaluates candidate k in 1..7.

Usage: python3 measure_accept_pos.py [--reps 10] [--url ...] [--model ...]
"""

import argparse
import json
import re
import sys
import time
import urllib.request


def parse(url):
    base = url[: url.rfind("/")] + "/metrics"
    with urllib.request.urlopen(base, timeout=30) as r:
        text = r.read().decode("utf-8", "replace")
    out = {"batches": 0.0, "draft_tokens": 0.0, "accepted": 0.0, "per_pos": {}}
    for m in re.finditer(r"^vllm:spec_decode_num_(\w+)(?:_total)?\{[^}]*\}\s+([0-9.]+)",
                         text, re.M):
        full = m.group(0)
        label = full.split("{")[0]
        if "per_pos" in label:
            pos = re.search(r'position="(\d+)"', full).group(1)
            out["per_pos"][int(pos)] = float(m.group(2))
    for m in re.finditer(r"^vllm:spec_decode_num_(drafts|draft_tokens|accepted_tokens)_total\{[^}]*\}\s+([0-9.]+)",
                         text, re.M):
        out[{"drafts": "batches", "draft_tokens": "draft_tokens",
             "accepted_tokens": "accepted"}[m.group(1)]] = float(m.group(2))
    return out


PROMPTS = [
    ("convo", "Explain what a transformer model is in two sentences."),
    ("reason-chain", "Minicorp has 4 engineers and 3 support agents. Alice Chen is an engineer reporting to Bob Martinez (Team Lead of Platform, who reports to Dana Smith, Head of Engineering). Carol Nguyen leads Support. Bob Martinez has 2 directs: Alice and Evan. Who should a medium 'Budget sign-off' ticket be assigned to? State the chain of command you used."),
    ("code", "Write a Python function that returns the nth Fibonacci number with memoization, including a short usage example."),
    ("math", "Solve: if x + y = 10 and x - y = 4, what are x and y? Show your work briefly."),
    ("essay", "Write a 250-word essay on why speculative decoding is useful for local LLM serving. Cover draft models, acceptance rates, and practical trade-offs."),
    ("translate", "Translate 'The quick brown fox jumps over the lazy dog' into German, then into Japanese."),
    ("plan", "Plan a 3-day Kyoto itinerary with 5 bullet points per day, mixing temples, food, and nature."),
    ("summary", "Summarize the plot of Romeo and Juliet in exactly 3 sentences."),
    ("tradeoff", "What are the trade-offs of a monolith vs microservices? Give 4 concise bullet points."),
    ("tool", "What department is Alice Chen in?",
     [{"type": "function", "function": {"name": "lookup_employee",
        "description": "Find a specific person by name, employee ID, or email.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": []}}}],
     "auto"),
]


def stream_once(url, model, msg, tools=None, tool_choice="none", timeout=900):
    body = {"model": model, "messages": [{"role": "user", "content": msg}],
            "max_tokens": 8192, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": True},
            "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    req = urllib.request.Request(url + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic(); first = None; buf = b""; usage = {}; finish = None; content = ""

    def handle(line):
        nonlocal first, usage, finish, content
        line = line.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            return
        pl = line[5:].strip()
        if pl == "[DONE]":
            return
        try:
            ev = json.loads(pl)
        except Exception:
            return
        if first is None:
            first = time.monotonic()
        ch = ev.get("choices") or []
        if ch:
            if ch[0].get("finish_reason"):
                finish = ch[0]["finish_reason"]
            d = ch[0].get("delta") or {}
            if d.get("content"):
                content += d["content"]
        if ev.get("usage"):
            usage = ev["usage"]

    with urllib.request.urlopen(req, timeout=timeout) as r:
        while True:
            chunk = r.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                handle(line)
    if buf:
        handle(buf)
    wall = time.monotonic() - t0
    comp = int(usage.get("completion_tokens", 0) or 0)
    return {
        "comp": comp,
        "wall": wall,
        "ttft": (first - t0) if first else wall,
        "decode_tokps": round(comp / (wall - (first - t0)), 2) if comp and (wall - (first - t0)) > 0.05 else None,
        "finish": finish,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:2468/v1")
    ap.add_argument("--model", default="qwen3.8-dense")
    args = ap.parse_args()

    m0 = parse(args.url)
    print("### per-position acceptance measurement (DSpark k=7, raw-mode server)")
    print(f"start counters: batches={int(m0['batches'])} draft_tok={int(m0['draft_tokens'])} "
          f"accepted={int(m0['accepted'])}")
    for name, msg, *rest in PROMPTS:
        tools = rest[0] if rest else None
        tc = rest[1] if len(rest) > 1 else "auto"
        r = stream_once(args.url, args.model, msg, tools, tc)
        print(f"  {name:14s} comp={r['comp']:5d} ttft={r['ttft']:.2f}s wall={r['wall']:.1f}s "
              f"decode={r['decode_tokps']} tok/s finish={r['finish']}", flush=True)

    m1 = parse(args.url)
    batches = m1["batches"] - m0["batches"]
    dpos = {p: m1["per_pos"].get(p, 0) - m0["per_pos"].get(p, 0) for p in range(7)}
    print(f"\n### deltas over this run: batches={int(batches)} "
          f"draft_tokens={int(m1['draft_tokens']-m0['draft_tokens'])} "
          f"accepted={int(m1['accepted']-m0['accepted'])}")
    print("per-position accepted:", {k: int(v) for k, v in dpos.items()})

    if batches <= 0:
        print("no batches — cannot compute curve; is speculation active?")
        return
    # survival curve S(i) = P(run length >= i), i = 1..7
    surv = {i: dpos[i - 1] / batches for i in range(1, 8)}
    print("\n### acceptance survival curve S(i) = P(accepted >= i)")
    for i in range(1, 8):
        print(f"  pos {i}: S({i}) = {surv[i]:.4f}  ({int(dpos[i-1])}/{int(batches)} batches)")
    total_acc = sum(dpos.values())
    print(f"  E[accepted] over full k=7 = {total_acc/batches:.3f} tokens/batch")

    print("\n### ideal k evaluation (tokens advanced vs target verify cost)")
    print(f"  {'k':>2} {'E[a(k)]':>9} {'tok/step':>9} {'verify pos':>10} {'eff (tok/pos)':>12}")
    best = None
    for k in range(1, 8):
        ea = sum(surv[i] for i in range(1, k + 1))
        tok_per_step = ea + 1.0
        eff = tok_per_step / (k + 1)
        flag = ""
        if best is None or eff > best[1]:
            best = (k, eff)
            flag = "  <-- best"
        print(f"  {k:>2} {ea:>9.3f} {tok_per_step:>9.3f} {k+1:>10} {eff:>12.3f}{flag}")
    print(f"\n### recommendation: k = {best[0]} "
          f"(max tokens-per-target-position {best[1]:.3f})")
    print("note: wall-clock also includes draft-model cost and kernel overheads; "
          "eff(tok/pos) is the compute-side proxy.")


if __name__ == "__main__":
    sys.exit(main())
