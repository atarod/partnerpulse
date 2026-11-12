"""Run the evaluation set. Ground truth is computed straight from raw data,
independently of the metrics layer, so a broken definition would be caught.

Usage: python evals/run_evals.py [--llm]
"""
import json
import pathlib
import sys

from partnerpulse import build
from partnerpulse.data import generate

USE_LLM = "--llm" in sys.argv


def truth(df, partner, period):
    d = df[(df.partner_id == partner) & (df.date.dt.strftime("%Y-%m") == period)]
    return f"{100 * d.policies_sold.sum() / d.eligible_bookings.sum():.1f}%"


def main():
    df = generate()
    cases = [json.loads(l) for l in pathlib.Path(__file__).with_name("eval_set.jsonl").read_text().splitlines() if l]
    passed = 0
    for c in cases:
        orch = build(llm=USE_LLM)
        a = orch.ask(c["question"], c["partner"])
        e, checks = c["expect"], []
        if e["type"] == "value":
            checks.append(("correct value", truth(df, c["partner"], e["period"]) in a.text))
        if e["type"] == "explain":
            checks += [(f"mentions '{m}'", m in a.text) for m in e["must_mention"]]
            checks.append(("review routing", a.requires_review == e["review"]))
        if e["type"] == "refusal":
            checks.append(("refused", a.refused))
        if a.verification is not None:
            checks.append(("verifier passed", a.verification.passed))
        ok = all(r for _, r in checks)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']:<14} " + ", ".join(f"{n}={'ok' if r else 'x'}" for n, r in checks))
    print(f"\n{passed}/{len(cases)} passed")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
