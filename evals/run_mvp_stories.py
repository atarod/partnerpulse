"""Check the MVP detector against the planted stories in the synthetic dataset.

Usage: python evals/run_mvp_stories.py [--seeds 5]
Reports, per story, whether the right alert (type, direction, cause) was raised,
plus precision and recall. Several seeds test that results aren't luck.
"""
import argparse
import sys

import pandas as pd

from partnerpulse.mvp.data import GROUND_TRUTH, generate
from partnerpulse.mvp.detect import run


def matches(alert: dict, truth: dict) -> bool:
    if alert["scope"] != truth["scope"] or alert["id"] != truth["id"] or alert["alert"] != truth["alert"]:
        return False
    if truth.get("direction") and alert.get("direction") != truth["direction"]:
        return False
    if truth.get("cause") and alert.get("cause") != truth["cause"]:
        return False
    if truth.get("partners") and sorted(alert.get("partners", [])) != sorted(truth["partners"]):
        return False
    return True


def score(seed: int, verbose: bool):
    alerts = run(generate(seed))
    expected = [t for t in GROUND_TRUTH if t["alert"]]
    found = {i for i, t in enumerate(expected) if any(matches(a, t) for a in alerts)}
    correct = [a for a in alerts if any(matches(a, t) for t in expected)]
    if verbose:
        print(f"{'Story':<6}{'Target':<24}{'Expected':<12}Result")
        for t in GROUND_TRUTH:
            hit = [a for a in alerts if a["id"] == t["id"]]
            if t["alert"]:
                ok = any(matches(a, t) for a in alerts)
                res = "PASS" if ok else "MISS"
            else:
                ok = not hit
                res = "PASS (no alert)" if ok else "FALSE ALARM"
            print(f"{str(t['story'] or '-'):<6}{t['id']:<24}{str(t['alert'] or 'none'):<12}{res}")
        extra = [a for a in alerts if a not in correct]
        for a in extra:
            print(f"      unexpected alert: {a['scope']} {a['id']} {a['alert']}")
    precision = len(correct) / len(alerts) if alerts else 1.0
    recall = len(found) / len(expected)
    return precision, recall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    n = ap.parse_args().seeds
    rows = []
    for i, seed in enumerate(range(11, 11 + n)):
        if i == 0:
            print(f"=== Seed {seed} (the published dataset) ===")
        p, r = score(seed, verbose=(i == 0))
        rows.append((seed, p, r))
    df = pd.DataFrame(rows, columns=["seed", "precision", "recall"])
    print("\n=== Across seeds ===")
    print(df.to_string(index=False, formatters={"precision": "{:.0%}".format, "recall": "{:.0%}".format}))
    print(f"\nMean precision {df.precision.mean():.0%} · mean recall {df.recall.mean():.0%}")
    sys.exit(0 if df.recall.min() == 1.0 and df.precision.min() == 1.0 else 1)


if __name__ == "__main__":
    main()
