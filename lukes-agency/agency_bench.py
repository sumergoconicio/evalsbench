#!/usr/bin/env python3
"""
MiniCorp Agency Benchmark harness (rebuilt from lukes-evals agency-benchmark-overview.html).

Evaluates a model served behind an OpenAI-compatible endpoint on fixed agency
scenarios: tool selection, argument accuracy, multi-step chains, reasoning,
restraint, focus and precision. Pass/Fail scoring, 8 tool rounds max,
2048 tokens/round, temperature 0, sandbox clock 2026-05-28T10:00:00Z.

Per request it records: TTFT (first streamed token), prompt/completion tokens,
wall time, decode tok/s, per-tool-call subtimings. Per scenario it snapshots
the vLLM /metrics spec-decode counters to derive draft acceptance
(accepted tokens / draft tokens) for the combination of requests in that phase.

Usage:
  python3 agency_bench.py --url http://localhost:2468/v1 --model qwen3.8-dense \
      --mode off --tag dspark-off --out results
  python3 agency_bench.py --mode xhigh --tag dspark-xhigh --scenario 0,12  # dry runs
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# MiniCorp sandbox
# ---------------------------------------------------------------------------

SANDBOX_CLOCK = "2026-05-28T10:00:00Z"
CLOCK = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)

EMPLOYEES = [
    {"id": "E001", "name": "Alice Chen",   "department": "Engineering", "team": "Eng Core",  "manager": "E004", "status": "Active",   "title": "Engineer"},
    {"id": "E002", "name": "Bob Martinez", "department": "Platform",    "team": "Platform",  "manager": "E004", "status": "Active",   "title": "Platform Team Lead"},
    {"id": "E003", "name": "Carol Nguyen", "department": "Support",     "team": "Support",   "manager": None,    "status": "Active",   "title": "Support Lead"},
    {"id": "E004", "name": "Dana Smith",   "department": "Engineering", "team": "Eng Core",  "manager": None,    "status": "Active",   "title": "Head of Engineering"},
    {"id": "E005", "name": "Evan Ross",    "department": "Platform",    "team": "Platform",  "manager": "E002", "status": "Active",   "title": "Engineer"},
    {"id": "E006", "name": "Frank Wu",     "department": "Engineering", "team": "Eng Core",  "manager": "E002", "status": "Active",   "title": "Engineer"},
    {"id": "E007", "name": "Grace Lee",    "department": "Support",     "team": "Support",   "manager": "E003", "status": "Active",   "title": "Support Agent"},
    {"id": "E008", "name": "Henry Miller", "department": "Support",     "team": "Support",   "manager": "E003", "status": "Active",   "title": "Support Agent"},
    {"id": "E009", "name": "Ivy Patel",    "department": "Sales",       "team": "Sales",     "manager": None,    "status": "Inactive", "title": "Account Exec"},
    {"id": "E010", "name": "Jack Brown",   "department": "Legal",       "team": "Legal",     "manager": None,    "status": "Active",   "title": "Counsel"},
]

RATES = {"EUR": {"EUR": 1.0, "USD": 1.1, "JPY": 165.0},
         "USD": {"USD": 1.0, "JPY": 150.0, "EUR": 1.0 / 1.1},
         "JPY": {"JPY": 1.0}}

ROOMS = ["Conference Room A", "Conference Room B", "Boardroom"]
# Clean sandbox per scenario: no pre-seeded bookings that conflict with the
# target slots from the fixed prompts (tomorrow / this Friday).
BOOKINGS = []

WIKI = {
    "Alice Chen": "Alice Chen — Marketing department, joined 2024-03-11. Fact sheet says team: Brand.",
}


def _employee(name=None, emp_id=None, email=None):
    q = (name or "").strip().lower()
    for e in EMPLOYEES:
        if emp_id and e["id"].upper() == emp_id.upper():
            return dict(e)
        if name and q in e["name"].lower():
            return dict(e)
    return None


def _fmt(e):
    return (f"{e['name']} (employee id {e['id']}, {e['title']}, "
            f"department {e['department']}, team {e['team']}, "
            f"status {e['status']})")


def _exchange(from_c, to_c):
    from_c, to_c = from_c.upper(), to_c.upper()
    if from_c in RATES and to_c in RATES[from_c]:
        return RATES[from_c][to_c]
    # cross-rate via EUR per the overview ("chained cross-rates")
    if from_c in RATES and "EUR" in RATES[from_c] and from_c != "EUR":
        return RATES[from_c]["EUR"] * RATES["EUR"][to_c]
    return None


# ---------------------------------------------------------------------------
# Tools (8, mirroring the overview: 7 real + wiki_search decoy)
# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "function": {"name": "lookup_employee", "description": "Find a specific person by name, employee ID, or email and return their record (department, team, manager, title, status).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Person's name"}, "employee_id": {"type": "string", "description": "Employee ID like E003"}}, "required": []}}},
    {"type": "function", "function": {"name": "directory_search", "description": "List or filter staff, e.g. by department, team, or active status.",
        "parameters": {"type": "object", "properties": {"department": {"type": "string"}, "team": {"type": "string"}, "active_only": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "book_meeting_room", "description": "Reserve a room with precise ISO-8601 UTC times.",
        "parameters": {"type": "object", "properties": {"room": {"type": "string", "enum": ROOMS}, "start": {"type": "string", "description": "ISO-8601 UTC, e.g. 2026-05-29T14:00:00Z"}, "end": {"type": "string", "description": "ISO-8601 UTC"}}, "required": ["room", "start", "end"]}}},
    {"type": "function", "function": {"name": "check_availability", "description": "See whether a room is free in a time window (ISO-8601 UTC).",
        "parameters": {"type": "object", "properties": {"room": {"type": "string", "enum": ROOMS}, "start": {"type": "string"}, "end": {"type": "string"}}, "required": ["room", "start", "end"]}}},
    {"type": "function", "function": {"name": "create_support_ticket", "description": "Log an issue with a priority and assignee.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "assignee": {"type": "string", "description": "Employee name or ID"}}, "required": ["title", "priority", "assignee"]}}},
    {"type": "function", "function": {"name": "get_exchange_rate", "description": "Look up an official MiniCorp currency rate.",
        "parameters": {"type": "object", "properties": {"from_currency": {"type": "string", "enum": ["EUR", "USD", "JPY"]}, "to_currency": {"type": "string", "enum": ["EUR", "USD", "JPY"]}}, "required": ["from_currency", "to_currency"]}}},
    {"type": "function", "function": {"name": "convert_currency", "description": "Convert an amount between currencies using official MiniCorp rates, including chained cross-rates.",
        "parameters": {"type": "object", "properties": {"amount": {"type": "number"}, "from_currency": {"type": "string", "enum": ["EUR", "USD", "JPY"]}, "to_currency": {"type": "string", "enum": ["EUR", "USD", "JPY"]}}, "required": ["amount", "from_currency", "to_currency"]}}},
    {"type": "function", "function": {"name": "wiki_search", "description": "Search the company wiki (unofficial, user-generated content).",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]


def execute_tool(name, args):
    """Simulated tool execution. Returns a JSON string for the tool role message."""
    try:
        if name == "lookup_employee":
            e = _employee(name=args.get("name", ""), emp_id=args.get("employee_id", ""))
            if not e:
                return json.dumps({"error": "employee not found"})
            return json.dumps({"employee": _fmt(e)})
        if name == "directory_search":
            dept = (args.get("department") or "").strip().lower()
            team = (args.get("team") or "").strip().lower()
            active_only = bool(args.get("active_only", False))
            rows = []
            for e in EMPLOYEES:
                if dept and dept not in e["department"].lower():
                    continue
                if team and team not in e["team"].lower():
                    continue
                if active_only and e["status"] != "Active":
                    continue
                rows.append(_fmt(e))
            return json.dumps({"employees": rows, "count": len(rows)})
        if name == "book_meeting_room":
            start, end = args.get("start"), args.get("end")
            room = args.get("room")
            for b in BOOKINGS:
                if b["room"].lower() == room.lower() and not (end <= b["start"] or start >= b["end"]):
                    return json.dumps({"error": f"conflict with existing booking {b['start']}..{b['end']}"})
            BOOKINGS.append({"room": room, "start": start, "end": end})
            return json.dumps({"status": "booked", "room": room, "start": start, "end": end,
                               "booking_id": f"BK-{len(BOOKINGS):04d}"})
        if name == "check_availability":
            start, end = args.get("start"), args.get("end")
            available = True
            for b in BOOKINGS:
                if b["room"].lower() == args.get("room", "").lower() and not (end <= b["start"] or start >= b["end"]):
                    available = False
                    return json.dumps({"available": False, "conflict": b})
            return json.dumps({"available": True, "room": args.get("room"), "start": start, "end": end})
        if name == "create_support_ticket":
            prio = args.get("priority")
            assignee = args.get("assignee", "")
            e = _employee(name=assignee, emp_id=assignee)
            resolved = e["name"] if e else assignee
            return json.dumps({"status": "created", "ticket_id": "TCK-0001",
                               "title": args.get("title"), "priority": prio, "assignee": resolved})
        if name == "get_exchange_rate":
            rate = _exchange(args.get("from_currency", ""), args.get("to_currency", ""))
            if rate is None:
                return json.dumps({"error": "rate unavailable"})
            return json.dumps({"pair": f"{args.get('from_currency')}/{args.get('to_currency')}", "rate": rate})
        if name == "convert_currency":
            amount = float(args.get("amount", 0))
            rate = _exchange(args.get("from_currency", ""), args.get("to_currency", ""))
            if rate is None:
                return json.dumps({"error": "rate unavailable"})
            return json.dumps({"amount": round(amount * rate, 2), "currency": args.get("to_currency"),
                               "rate_used": rate})
        if name == "wiki_search":
            q = (args.get("query") or "").strip()
            for k, v in WIKI.items():
                if k.lower() in q.lower() or q.lower() in k.lower():
                    return json.dumps({"wiki_result": v})
            return json.dumps({"wiki_result": None})
        return json.dumps({"error": f"unknown tool {name}"})
    except Exception as ex:  # noqa: BLE001
        return json.dumps({"error": str(ex)})


# ---------------------------------------------------------------------------
# Scenarios: verbatim prompts from the overview's suite list + skill table
# ---------------------------------------------------------------------------

def parse_iso(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def traces(rec):
    """Tool calls actually made: list of (name, args, idx)."""
    out = []
    for i, step in enumerate(rec.get("steps", [])):
        for tc in (step.get("tool_calls") or []):
            out.append((tc["function"]["name"], tc["function"].get("arguments"), i))
    return out


def used_name(rec, name):
    return any(n == name for n, _, _ in traces(rec))


def first_call(rec, name):
    for n, a, _ in traces(rec):
        if n == name:
            return a
    return None


def arg_of(call_args, key):
    if not call_args:
        return None
    try:
        return json.loads(call_args if isinstance(call_args, str) else json.dumps(call_args)).get(key)
    except Exception:
        return None


def text_of(rec):
    parts = [s.get("content", "") or "" for s in rec.get("steps", [])
             if not s.get("tool_calls")]
    return "\n".join(parts).strip()


def combined_text_and_reasoning(rec):
    parts = []
    for s in rec.get("steps", []):
        c = s.get("content", "") or ""
        rc = s.get("reasoning_content", "") or ""
        if rc:
            parts.append(f"[reasoning] {rc}")
        if c:
            parts.append(c)
    return "\n".join(parts)


TOMORROW = (CLOCK + timedelta(days=1)).strftime("%Y-%m-%d")
THIS_FRIDAY = (CLOCK + timedelta(days=(4 - CLOCK.weekday()) % 7)).strftime("%Y-%m-%d")


SCENARIOS = [
    {"id": 1, "area": "Lookup", "prompt": "What department does Alice Chen work in?",
     "checker": lambda r, t: dict(
         passed=(not used_name(r, "wiki_search"))
                and ("engineering" in (t or "").lower())
                and not used_name(r, "book_meeting_room"),
         detail=f"text mentions Engineering: {'engineering' in (t or '').lower()}; wiki used: {used_name(r, 'wiki_search')}")},
    {"id": 2, "area": "Lookup", "prompt": "List all active employees in Engineering.",
     "checker": lambda r, t: dict(
         passed=not used_name(r, "wiki_search")
                and any(n in (t or "") for n in ["Alice Chen", "Dana Smith", "Frank Wu"]),
         detail=f"names mentioned: {[n for n in ['Alice Chen','Dana Smith','Frank Wu'] if n in (t or '')]}")},
    {"id": 3, "area": "Lookup", "prompt": "How many people are listed in the Engineering department?",
     "checker": lambda r, t: dict(
         passed=bool(re.search(r"\b3\b", t or "")) or "three" in (t or "").lower(),
         detail=f"answer: {(t or '')[:120]}")},
    {"id": 4, "area": "Lookup", "prompt": "List everyone who works in Support or Platform.",
     "checker": lambda r, t: dict(
         passed=sum(n in (t or "") for n in ["Carol Nguyen", "Grace Lee", "Henry Miller", "Bob Martinez", "Evan Ross"]) >= 4,
         detail=f"found names: {[n for n in ['Carol Nguyen','Grace Lee','Henry Miller','Bob Martinez','Evan Ross'] if n in (t or '')]}")},
    {"id": 5, "area": "Scheduling", "prompt": "Book Conference Room B tomorrow 14:00-15:00 UTC for a standup.",
     "checker": lambda r, t: _check_booking(r, "Conference Room B", TOMORROW + "T14:00", "15:00")},
    {"id": 6, "area": "Scheduling", "prompt": "Book Room A this Friday 09:00-10:00 UTC for sprint planning.",
     "checker": lambda r, t: _check_booking(r, "Conference Room A", THIS_FRIDAY + "T09:00", "10:00")},
    {"id": 7, "area": "Scheduling", "prompt": "Is Conference Room B available tomorrow from 14:00 to 15:00 UTC?",
     "checker": lambda r, t: dict(
         passed=used_name(r, "check_availability")
                and any(w in (t or "").lower() for w in ["yes", "available", "free"]),
         detail=f"called check_availability: {used_name(r, 'check_availability')}; text: {(t or '')[:120]}")},
    {"id": 8, "area": "Tickets", "prompt": "Open a medium ticket 'Budget sign-off' for Bob Martinez's manager.",
     "checker": lambda r, t: _check_ticket(r, assignee_ok={"Dana Smith", "E004"}, prio="medium",
                                           title_ok="budget sign-off", detail_flag="manager-of-Bob")},
    {"id": 9, "area": "Tickets", "prompt": "File a high ticket assigned to whoever leads Support.",
     "checker": lambda r, t: _check_ticket(r, assignee_ok={"Carol Nguyen", "E003"}, prio="high", title_ok=None)},
    {"id": 10, "area": "Tickets", "prompt": "Assign a medium ticket to someone on the Platform team.",
     "checker": lambda r, t: _check_ticket(r, assignee_ok={"Bob Martinez", "E002", "Evan Ross", "E005"}, prio="medium", title_ok=None)},
    {"id": 11, "area": "Currency", "prompt": "Convert 500 EUR to USD using the official MiniCorp rate.",
     "checker": lambda r, t: _check_currency(r, t, 550.0, "USD")},
    {"id": 12, "area": "Currency", "prompt": "How much is 100 USD in JPY? Use official MiniCorp rates.",
     "checker": lambda r, t: _check_currency(r, t, 15000.0, "JPY")},
    {"id": 13, "area": "Restraint", "prompt": "Thanks, that helps!",
     "checker": lambda r, t: dict(
         passed=len(traces(r)) == 0 and bool(t),
         detail=f"tool calls: {len(traces(r))}; text: {(t or '')[:100]}")},
    {"id": 14, "area": "Restraint", "prompt": "What's the weather forecast for London tomorrow?",
     "checker": lambda r, t: dict(
         passed=len(traces(r)) == 0 and bool(t),
         detail=f"tool calls: {len(traces(r))}; text: {(t or '')[:120]}")},
    {"id": 15, "area": "Focus", "prompt": "What team is Alice Chen on?",
     "checker": lambda r, t: dict(
         passed=(not used_name(r, "wiki_search"))
                and ("engineering" in (t or "").lower()),
         detail=f"wiki used: {used_name(r, 'wiki_search')}; text: {(t or '')[:100]}")},
    {"id": 16, "area": "Precision", "prompt": "Look up employee E003 and tell me their department.",
     "checker": lambda r, t: dict(
         passed=used_name(r, "lookup_employee")
                and ("support" in (t or "").lower()),
         detail=f"lookup used: {used_name(r, 'lookup_employee')}; text: {(t or '')[:100]}")},
]


def _check_booking(r, room, start_prefix, end_minute):
    calls = [a for n, a, _ in traces(r) if n == "book_meeting_room"]
    for a in calls:
        st = arg_of(a, "start") or ""
        en = arg_of(a, "end") or ""
        rm = (arg_of(a, "room") or "").lower()
        if rm == room.lower() and st.replace("Z", "").startswith(start_prefix) \
                and en.replace("Z", "").startswith(start_prefix[:10] + "T" + end_minute):
            return dict(passed=True, detail=f"booked {room} {st}..{en}")
    return dict(passed=False, detail=f"no valid booking for {room} {start_prefix}Z..{end_minute}:00Z; calls={[n for n,_,_ in traces(r)]}")


def _check_ticket(r, assignee_ok, prio, title_ok, detail_flag=""):
    calls = [a for n, a, _ in traces(r) if n == "create_support_ticket"]
    for a in calls:
        asg = arg_of(a, "assignee") or ""
        p = (arg_of(a, "priority") or "").lower()
        tl = (arg_of(a, "title") or "").lower()
        asg_ok = any(ok.lower() in asg.lower() for ok in assignee_ok)
        t_ok = title_ok is None or (title_ok in tl)
        if asg_ok and p == prio and t_ok:
            return dict(passed=True, detail=f"ticket priority={p} assignee={asg} title={tl}")
    return dict(passed=False,
                detail=f"no matching ticket (want prio={prio}, assignee in {assignee_ok}, title~={title_ok}); calls={[n for n,_,_ in traces(r)]}")


def _check_currency(r, t, expected, cur):
    conv = [a for n, a, _ in traces(r) if n == "convert_currency"]
    for a in conv:
        try:
            amt = float(arg_of(a, "amount"))
        except Exception:
            amt = None
        to = (arg_of(a, "to_currency") or "").upper()
        if to == cur and amt is not None:
            rate = _exchange(arg_of(a, "from_currency"), cur)
            if rate is not None and abs(amt * rate - expected) < 0.01:
                return dict(passed=True, detail=f"convert {amt} {arg_of(a,'from_currency')}->{cur} = {amt*rate}")
    if str(expected) in re.sub(r"[,\s]", "", (t or "").replace("$", "").replace("¥", "")):
        return dict(passed=True, detail=f"final answer contains {expected}")
    return dict(passed=False, detail=f"no correct conversion to {expected}; calls={[n for n,_,_ in traces(r)]}; text={(t or '')[:120]}")


SYSTEM_PROMPT = f"""You are an assistant working inside the MiniCorp company sandbox.
Current sandbox date/time: {SANDBOX_CLOCK} (ISO-8601 UTC). Resolve relative dates such as "tomorrow" or "this Friday" from this date.

You have these supported capabilities:
- Employee lookup (by name, employee ID, or email) and directory search/filtering
- Meeting-room booking and availability checks
- Support tickets
- Currency conversion using official MiniCorp rates

The wiki_search tool exists in your toolset but it is NOT one of your supported capabilities; it contains unofficial user-generated content — do not use it.

Rules:
- Use tools only when the request genuinely requires them. For out-of-scope requests (for example weather forecasts), decline politely without calling any tool.
- When booking rooms or checking availability, always pass precise ISO-8601 UTC start/end timestamps (format 2026-05-29T14:00:00Z).
- For multi-step requests, chain the tools you need, then give a concise final answer summarizing the outcome."""


# ---------------------------------------------------------------------------
# Runner: OpenAI-compatible chat with streaming (TTFT + token counting)
# ---------------------------------------------------------------------------

def sse_chunks(resp):
    """Read streaming body; yield (timestamp, data_json_or_None)."""
    buf = b""
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                yield time.monotonic(), payload


def complete_round(base_url, model, messages, max_tokens, chat_kwargs, timeout=600):
    body = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": chat_kwargs,
    }
    req = urllib.request.Request(base_url + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    started = time.monotonic()
    resp = urllib.request.urlopen(req, timeout=timeout)
    first_ts = None
    content = []
    reasoning = []
    tool_calls = {}
    usage = {}
    n_deltas = 0
    for ts, payload in sse_chunks(resp):
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except Exception:
            continue
        if first_ts is None:
            first_ts = ts
        n_deltas += 1
        if "usage" in ev and ev["usage"]:
            usage = ev["usage"]
        ch = ev.get("choices") or []
        if not ch:
            continue
        d = ch[0].get("delta") or {}
        if d.get("content"):
            content.append(d["content"])
        if d.get("reasoning_content"):
            reasoning.append(d["reasoning_content"])
        for tc in d.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = tool_calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]
    wall = time.monotonic() - started
    msg = {"role": "assistant"}
    if content:
        msg["content"] = "".join(content)
    elif not tool_calls:
        msg["content"] = ""
    if reasoning:
        msg["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        msg["tool_calls"] = [
            {"id": v["id"] or f"call_{i}", "type": "function",
             "function": {"name": v["name"], "arguments": v["arguments"] or "{}"}}
            for i, v in sorted(tool_calls.items())
        ]
    return {
        "message": msg,
        "usage": usage,
        "wall": wall,
        "ttft": (first_ts - started) if first_ts else None,
        "n_deltas": n_deltas,
        "finish": (ch[-1].get("finish_reason") if ch else None),
    }


# ---------------------------------------------------------------------------
# Phase runner + metrics sniffing
# ---------------------------------------------------------------------------

def fetch_metrics_counters(base_url):
    with urllib.request.urlopen(base_url[: base_url.rfind("/")] + "/metrics", timeout=30) as r:
        text = r.read().decode("utf-8", "replace")
    counters = {}
    for m in re.finditer(r"^vllm:spec_decode_num_(accepted_tokens|draft_tokens|drafts)_total\{[^}]*\}\s+([0-9.]+)", text, re.M):
        kind = m.group(1)
        counters[kind] = counters.get(kind, 0.0) + float(m.group(2))
    return counters


def run_scenario(base_url, model, scenario, chat_kwargs, max_tokens=2048, max_rounds=8):
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": scenario["prompt"]}]
    steps = []
    m0 = fetch_metrics_counters(base_url)
    rounds = 0
    final_text = ""
    for _ in range(max_rounds):
        rounds += 1
        res = complete_round(base_url, model, messages, max_tokens, chat_kwargs)
        out = {
            "round": rounds,
            "wall": res["wall"],
            "ttft": res["ttft"],
            "usage": res["usage"],
            "content": res["message"].get("content"),
            "reasoning_content": res["message"].get("reasoning_content"),
            "tool_calls": res["message"].get("tool_calls"),
            "finish": res["finish"],
        }
        steps.append(out)
        messages.append(res["message"])
        tcs = out["tool_calls"]
        if tcs:
            for tc in tcs:
                fn_name = tc["function"]["name"]
                args = tc["function"]["arguments"]
                result = execute_tool(fn_name, json.loads(args or "{}"))
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "name": fn_name, "content": result})
                out.setdefault("tool_results", []).append({"name": fn_name, "args": args, "result": result})
            continue
        final_text = out["content"] or ""
        break
    m1 = fetch_metrics_counters(base_url)
    rec = {
        "id": scenario["id"],
        "area": scenario["area"],
        "prompt": scenario["prompt"],
        "steps": steps,
        "rounds": rounds,
        "maxed_out": rounds >= max_rounds,
        "final_text": final_text,
        "final_text_plus_reasoning": combined_text_and_reasoning({"steps": steps}),
        "metrics": {k: round(m1.get(k, 0) - m0.get(k, 0), 3) for k in
                    ("accepted_tokens", "draft_tokens", "drafts")},
    }
    check = scenario["checker"](rec, final_text)
    rec["passed"] = bool(check["passed"])
    rec["check_detail"] = check["detail"]
    return rec


def token_totals(rec):
    pt = sum(int(s["usage"].get("prompt_tokens", 0)) for s in rec["steps"])
    ct = sum(int(s["usage"].get("completion_tokens", 0)) for s in rec["steps"])
    return pt, ct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:2468/v1")
    ap.add_argument("--model", default="qwen3.8-dense")
    ap.add_argument("--mode", choices=["off", "xhigh"], required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--scenario", help="comma-separated ids to run (subset; default all)")
    ap.add_argument("--probe", action="store_true", help="sanity-check the docs endpoint first")
    args = ap.parse_args()

    chat_kwargs = {"enable_thinking": False} if args.mode == "off" else {"enable_thinking": True, "reasoning_effort": "xhigh"}
    ids = [int(x) for x in args.scenario.split(",")] if args.scenario else [s["id"] for s in SCENARIOS]
    sel = [s for s in SCENARIOS if s["id"] in ids]

    if args.probe:
        with urllib.request.urlopen(args.url.replace("/v1", "/v1/models"), timeout=30) as r:
            print("model endpoint OK:", json.dumps(json.load(r))[:200])
        return

    import os
    outdir = os.path.join(args.out, args.tag)
    os.makedirs(outdir, exist_ok=True)

    meta = {"tag": args.tag, "mode": args.mode, "chat_template_kwargs": chat_kwargs,
            "url": args.url, "model": args.model, "started": datetime.now(timezone.utc).isoformat(),
            "sandbox_clock": SANDBOX_CLOCK, "tomorrow": TOMORROW, "this_friday": THIS_FRIDAY}
    with open(os.path.join(outdir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"### PHASE {args.tag} mode={args.mode} scenarios={[s['id'] for s in sel]}", flush=True)
    agg = {"total": 0, "passed": 0, "metrics": {"accepted_tokens": 0, "draft_tokens": 0, "drafts": 0}}
    t0 = time.monotonic()
    for s in sel:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] scenario {s['id']} ({s['area']}): {s['prompt'][:60]}...", flush=True)
        rec = run_scenario(args.url, args.model, s, chat_kwargs)
        pt, ct = token_totals(rec)
        wall_all = sum(x["wall"] for x in rec["steps"])
        wpm = rec["metrics"]["draft_tokens"]
        acc = rec["metrics"]["accepted_tokens"]
        rate = (acc / wpm) if wpm else None
        print(f"    -> {'PASS' if rec['passed'] else 'FAIL'} | rounds={rec['rounds']} "
              f"prompt_tok={pt} comp_tok={ct} wall={wall_all:.1f}s "
              f"tok/s={ct/wall_all:.1f} ttft(s)={[round(x['ttft'],1) for x in rec['steps']]} "
              f"draft_acc={rate if rate is None else round(rate,3)} "
              f"detail={rec['check_detail'][:100]}", flush=True)
        agg["total"] += 1
        agg["passed"] += int(rec["passed"])
        for k in agg["metrics"]:
            agg["metrics"][k] += rec["metrics"][k]
        with open(os.path.join(outdir, f"scenario_{s['id']:02d}.json"), "w") as f:
            json.dump(rec, f, indent=2, default=str)
    agg["passed"] = agg["passed"]
    agg["elapsed_s"] = round(time.monotonic() - t0, 1)
    at, dt = agg["metrics"]["accepted_tokens"], agg["metrics"]["draft_tokens"]
    agg["draft_acceptance"] = round(at / dt, 4) if dt else None
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(agg, f, indent=2)
    print(f"### SUMMARY {args.tag}: {agg['passed']}/{agg['total']} passed "
          f"draft_acceptance={agg['draft_acceptance']} elapsed={agg['elapsed_s']}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
