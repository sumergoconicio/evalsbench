#!/usr/bin/env python3
"""A/B probe: current server template (baseline) vs hybrid template.

Uses vLLM's per-request `chat_template` override, so no server restart is
needed. Cases mirror the failure modes the template fixes:

  case  : what it tests
  default-off   : thinking off, short prompt            (both should pass)
  default-think : enable_thinking true, NO effort       (official 3.8 defaults
                 to xhigh -> token-budget burn; hybrid defaults to medium)
  xhigh         : enable_thinking true + effort xhigh   (explicit deep reason)
  tool-strargs  : multi-turn tool history with stringified JSON args
                 (official 3.8 crashes on string args; hybrid parses them)

Usage: python3 probe_hybrid.py [--template path] [--url ...] [--model ...]
If --template is omitted, only the baseline (server default) runs.
"""

import argparse
import json
import time
import urllib.request

HARD_PROMPT = ("Minicorp has 4 engineers and 3 support agents. Alice Chen is an "
               "engineer reporting to Bob Martinez (Team Lead of Platform, who reports "
               "to Dana Smith, Head of Engineering). Carol Nguyen leads Support. Bob "
               "Martinez has 2 directs: Alice and Evan. Who should a medium 'Budget "
               "sign-off' ticket be assigned to? State the chain of command you used.")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_employee",
        "description": "Find a specific person by name, employee ID, or email.",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string"},
                                      "employee_id": {"type": "string"}},
                       "required": []}}},
    {"type": "function",
     "function": {
        "name": "directory_search",
        "description": "List or filter staff by department.",
        "parameters": {"type": "object",
                       "properties": {"department": {"type": "string"}},
                       "required": []}}}]


def call(url, model, payload, template_str=None, timeout=300):
    if template_str is not None:
        payload = dict(payload, chat_template=template_str)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}",
                "wall": round(time.monotonic() - t0, 1)}
    ch = d["choices"][0] if d.get("choices") else {}
    m = ch.get("message", {})
    return {
        "finish": ch.get("finish_reason"),
        "content_len": len(m.get("content") or ""),
        "content_head": (m.get("content") or "")[:200],
        "reasoning_len": len(m.get("reasoning_content") or ""),
        "usage": d.get("usage"),
        "wall": round(time.monotonic() - t0, 1),
        "error": None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", help="path to hybrid template; omit to baseline only")
    ap.add_argument("--url", default="http://localhost:2468/v1")
    ap.add_argument("--model", default="qwen3.8-dense")
    args = ap.parse_args()

    tpl = open(args.template).read() if args.template else None
    print(f"### probe url={args.url} model={args.model} template={'hybrid' if tpl else 'baseline(default)'}")

    cases = [
        ("default-off", {"messages": [{"role": "user", "content": "What is 2+2? Answer briefly."}],
                         "max_tokens": 256,
                         "chat_template_kwargs": {"enable_thinking": False}}),
        ("default-think", {"messages": [{"role": "user", "content": HARD_PROMPT}],
                           "max_tokens": 2048,
                           "chat_template_kwargs": {"enable_thinking": True}}),
        ("xhigh", {"messages": [{"role": "user", "content": HARD_PROMPT}],
                   "max_tokens": 2048,
                   "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "xhigh"}}),
        ("tool-strargs", {"messages": [
            {"role": "user", "content": "What department is Alice Chen in?"}],
            "max_tokens": 512,
            "tools": TOOLS,
            "tool_choice": "auto",
            "chat_template_kwargs": {"enable_thinking": False}}),
    ]
    for name, pload in cases:
        res = call(args.url, args.model, pload, tpl)
        if res.get("error"):
            print(f"  [{name}] ERROR {res['error']}")
            continue
        print(f"  [{name}] finish={res['finish']} content_len={res['content_len']} "
              f"reasoning_len={res['reasoning_len']} wall={res['wall']}s "
              f"usage={json.dumps(res['usage'])[:160]}")
        if res["content_len"]:
            print(f"      head: {res['content_head']!r}")
    if tpl:
        # multi-turn tool render: stringified args must not crash template
        hist = [
            {"role": "user", "content": "Look up Bob Martinez."},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "lookup_employee",
                                          "arguments": "{\"name\": \"Bob Martinez\"}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "lookup_employee",
             "content": "{\"employee\": \"Bob Martinez (E002)\"}"},
            {"role": "user", "content": "Now find Carol Nguyen too."},
        ]
        res = call(args.url, args.model,
                   {"messages": hist, "max_tokens": 256,
                    "tools": TOOLS, "tool_choice": "auto",
                    "chat_template_kwargs": {"enable_thinking": False}}, tpl)
        if res.get("error"):
            print(f"  [multi-turn-strargs] ERROR {res['error']}")
        else:
            print(f"  [multi-turn-strargs] finish={res['finish']} content_len={res['content_len']} wall={res['wall']}s")


if __name__ == "__main__":
    main()
