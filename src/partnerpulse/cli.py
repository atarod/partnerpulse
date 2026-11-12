"""Command-line interface: python -m partnerpulse <command>."""
from __future__ import annotations

import argparse
import textwrap

from . import build
from .data import generate
from .monitor import scan

DEMO_QUESTIONS = [
    ("airline_a", "What was our attach rate in August?"),
    ("airline_a", "Why did our protection attach rate drop in September?"),
    ("airline_a", "What is our customer lifetime value?"),
    ("airline_a", "Show me airline_b's attach rate"),
    ("market_a", "Why did our attach rate change in September?"),
]


def _print_answer(partner: str, question: str, answer) -> None:
    print(f"\n[{partner}] Q: {question}")
    for line in answer.render().splitlines():
        print(textwrap.fill(line, width=96, initial_indent="  ", subsequent_indent="  "))


def main() -> None:
    p = argparse.ArgumentParser(prog="partnerpulse", description="Agentic insights prototype")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="ask a question as a partner")
    a.add_argument("question")
    a.add_argument("--partner", default="airline_a")
    a.add_argument("--as-of", default="2026-10-06")
    a.add_argument("--llm", action="store_true", help="use a Claude model (needs ANTHROPIC_API_KEY)")
    a.add_argument("--trace", action="store_true", help="print tool calls")
    m = sub.add_parser("monitor", help="run scheduled anomaly checks")
    m.add_argument("--as-of", default="2026-09-12")
    sub.add_parser("demo", help="run the scenario end to end")
    md = sub.add_parser("mvp-data", help="write the MVP synthetic dataset and ground truth to CSV/JSON")
    md.add_argument("--out", default="data/mvp")
    sub.add_parser("mvp-alerts", help="run the MVP copilot detector and print alerts for account managers")
    e = sub.add_parser("export", help="write the synthetic dataset to CSV")
    e.add_argument("--out", default="tidewell_sales.csv")
    args = p.parse_args()

    if args.cmd == "ask":
        orch = build(as_of=args.as_of, llm=args.llm)
        ans = orch.ask(args.question, args.partner)
        _print_answer(args.partner, args.question, ans)
        if args.trace:
            for step in ans.trace:
                print(f"  · {step.get('tool')}: facts={step.get('facts')}")
    elif args.cmd == "monitor":
        orch = build()
        alerts = scan(orch.metrics, orch.events, args.as_of)
        print(f"Monitoring run as of {args.as_of}: {len(alerts)} alert(s)")
        for al in alerts:
            print(f"  ALERT {al['partner_id']}: {al['message']}")
            for ev in al["related_events"]:
                print(f"     related change on {ev['date']}: {ev['event']}")
    elif args.cmd == "demo":
        print("=== Monitoring on Sep 12 (3 days after the change) ===")
        orch = build()
        for al in scan(orch.metrics, orch.events, "2026-09-12"):
            print(f"  ALERT {al['partner_id']}: {al['message']}")
        print("\n=== Partner questions on Oct 6 ===")
        for partner, q in DEMO_QUESTIONS:
            _print_answer(partner, q, orch.ask(q, partner))
        print(f"\nMetric backlog from unanswered questions: {orch.metric_backlog}")
    elif args.cmd == "mvp-data":
        from .mvp.data import write
        print(f"wrote MVP dataset to {write(args.out)}")
    elif args.cmd == "mvp-alerts":
        from .mvp.data import PARTNERS, generate
        from .mvp.detect import run
        am = {p.partner_id: p.account_manager for p in PARTNERS}
        alerts = run(generate())
        for manager in sorted(set(am.values())):
            mine = [a for a in alerts if any(am.get(pid) == manager for pid in
                    ([a["id"].split(":")[0]] if a["scope"] != "market" else a["partners"]))]
            print(f"\n=== {manager}: {len(mine)} insight(s) to review ===")
            for a in mine:
                print(textwrap.fill(f"[{a['alert']}] {a['message']}", 96, initial_indent="  ", subsequent_indent="    "))
    elif args.cmd == "export":
        generate().to_csv(args.out, index=False)
        print(f"wrote {args.out}")
