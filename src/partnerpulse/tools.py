"""Deterministic tools the agent can call. The LLM never computes numbers itself.

Every tool returns a JSON-serialisable dict that includes ``facts``: the exact
display strings the answer is allowed to use. The verifier checks against them.
"""
from __future__ import annotations

import calendar
import math

import numpy as np
import pandas as pd

from .metrics import MetricsLayer, get_metric

MIN_PEERS = 5          # a benchmark needs at least this many partners
MAX_PEER_SHARE = 0.40  # dominance rule: no single partner above this share of volume


def month_range(period: str) -> tuple[str, str]:
    """'2026-09' -> ('2026-09-01', '2026-09-30')."""
    year, month = (int(x) for x in period.split("-"))
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def fmt_value(value: float, unit: str) -> str:
    if unit == "pct":
        return f"{value:.1f}%"
    if unit == "usd":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def fmt_date(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.strftime('%b')} {ts.day}"


class Toolbox:
    """Tools bound to one partner session."""

    def __init__(self, metrics: MetricsLayer, events: pd.DataFrame, session_partner: str):
        self.metrics = metrics
        self.events = events
        self.partner = session_partner

    # 1. Metric query ---------------------------------------------------------------
    def metric_query(self, metric: str, period: str, filters: dict | None = None) -> dict:
        start, end = month_range(period)
        r = self.metrics.query(metric, self.partner, start, end, session_partner=self.partner, filters=filters)
        facts = [fmt_value(r["value"], r["unit"]), period]
        if "denominator" in r:
            facts.append(f"{r['denominator']:,}")
        return {"tool": "metric_query", "period": period, **r, "facts": facts}

    # 2. Driver breakdown (rate effect vs. mix effect) -------------------------------
    def driver_breakdown(self, metric: str, base_period: str, compare_period: str,
                         dimensions: list[str] | None = None) -> dict:
        m = get_metric(metric)
        if m.denominator is None:
            return {"tool": "driver_breakdown", "error": "breakdown supports ratio metrics only", "facts": []}
        dimensions = dimensions or ["device", "market"]
        b0, b1 = month_range(base_period)
        c0, c1 = month_range(compare_period)
        total_base = self.metrics.query(metric, self.partner, b0, b1, session_partner=self.partner)["value"]
        total_cmp = self.metrics.query(metric, self.partner, c0, c1, session_partner=self.partner)["value"]
        total_change = total_cmp - total_base
        results, facts = [], [fmt_value(total_base, "pct"), fmt_value(total_cmp, "pct")]
        for dim in dimensions:
            base = {r["segment"]: r for r in self.metrics.query(
                metric, self.partner, b0, b1, session_partner=self.partner, group_by=dim)["rows"]}
            cmp_ = {r["segment"]: r for r in self.metrics.query(
                metric, self.partner, c0, c1, session_partner=self.partner, group_by=dim)["rows"]}
            den0 = sum(r["denominator"] for r in base.values())
            den1 = sum(r["denominator"] for r in cmp_.values())
            segs = []
            for seg in sorted(set(base) | set(cmp_)):
                s0 = base[seg]["denominator"] / den0 if seg in base else 0.0
                s1 = cmp_[seg]["denominator"] / den1 if seg in cmp_ else 0.0
                r0 = base[seg]["value"] if seg in base else 0.0
                r1 = cmp_[seg]["value"] if seg in cmp_ else 0.0
                rate_eff, mix_eff = s0 * (r1 - r0), (s1 - s0) * r1
                segs.append({"segment": seg, "base_rate": r0, "compare_rate": r1,
                             "rate_effect_pts": rate_eff, "mix_effect_pts": mix_eff,
                             "total_pts": rate_eff + mix_eff})
            segs.sort(key=lambda s: abs(s["total_pts"]), reverse=True)
            top = segs[0]
            share = top["total_pts"] / total_change if total_change else 0.0
            concentration = abs(top["total_pts"]) / (sum(abs(x["total_pts"]) for x in segs) or 1.0)
            results.append({"dimension": dim, "segments": segs, "top_segment": top["segment"],
                            "top_share_of_change": share, "concentration": concentration})
            facts += [fmt_value(top["base_rate"], "pct"), fmt_value(top["compare_rate"], "pct"),
                      f"{min(abs(share), 1.0) * 100:.0f}%"]
        results.sort(key=lambda d: d["concentration"], reverse=True)
        facts.append(f"{abs(total_change):.1f}")
        return {"tool": "driver_breakdown", "metric": metric, "base_period": base_period,
                "compare_period": compare_period, "total_change_pts": total_change,
                "dimensions": results, "source": m.source, "facts": facts}

    # 3. Anomaly detector -------------------------------------------------------------
    def anomaly_detector(self, metric: str, start: str, end: str, filters: dict | None = None,
                         min_shift_pts: float = 0.5, t_threshold: float = 4.0, min_after: int = 7,
                         window: int = 28) -> dict:
        s = self.metrics.daily_series(metric, self.partner, start, end, session_partner=self.partner,
                                      filters=filters).dropna()
        best = None
        vals, idx = s.values, s.index
        for k in range(7, len(vals) - min_after + 1):
            before, after = vals[max(0, k - window):k], vals[k:k + window]
            diff = after.mean() - before.mean()
            se = math.sqrt(before.var(ddof=1) / len(before) + after.var(ddof=1) / len(after)) or 1e-9
            t = diff / se
            if best is None or abs(t) > abs(best[1]):
                best = (k, t, diff, before.mean(), after.mean())
        out = {"tool": "anomaly_detector", "metric": metric, "filters": filters or {}, "start": start,
               "end": end, "significant": False, "facts": []}
        if best is None:
            return out
        k, t, diff, mb, ma = best
        change_date = idx[k]
        significant = abs(t) >= t_threshold and abs(diff) >= min_shift_pts
        ev = self.events[(self.events.partner_id == self.partner) &
                         ((self.events.date - change_date).abs() <= pd.Timedelta(days=2))]
        if filters and "device" in filters:
            ev = ev[ev.device == filters["device"]]
        events = [{"date": str(pd.Timestamp(e.date).date()), "event": e.event, "device": e.device,
                   "placement_to": e.placement_to} for e in ev.itertuples()]
        out.update({"significant": bool(significant), "change_date": str(change_date.date()),
                    "mean_before": float(mb), "mean_after": float(ma), "shift_pts": float(diff),
                    "t_stat": float(t), "related_events": events,
                    "facts": [fmt_date(change_date), fmt_value(mb, "pct"), fmt_value(ma, "pct"),
                              f"{abs(diff):.1f}"]})
        return out

    # 4. Peer benchmark ---------------------------------------------------------------
    def peer_benchmark(self, metric: str, period: str, group_by: str = "placement") -> dict:
        m = get_metric(metric)
        start, end = month_range(period)
        vertical = self.metrics.vertical_of(self.partner)
        peers = self.metrics.peer_frame(vertical, self.partner, start, end)
        groups = []
        for key, g in peers.groupby(group_by):
            per_partner = g.groupby("partner_id")[[m.numerator, m.denominator]].sum()
            n = len(per_partner)
            max_share = float((per_partner[m.denominator] / per_partner[m.denominator].sum()).max())
            if n < MIN_PEERS:
                groups.append({"group": str(key), "suppressed": True,
                               "reason": f"fewer than {MIN_PEERS} peers"})
                continue
            if max_share > MAX_PEER_SHARE:
                groups.append({"group": str(key), "suppressed": True,
                               "reason": "one partner dominates the group"})
                continue
            rates = 100.0 * per_partner[m.numerator] / per_partner[m.denominator]
            groups.append({"group": str(key), "suppressed": False, "peer_count": n,
                           "median": round(float(np.median(rates)), 1),  # rounded to limit inference
                           "range_low": math.floor(float(rates.min()) * 2) / 2,
                           "range_high": math.ceil(float(rates.max()) * 2) / 2})
        facts = []
        for gr in groups:
            if not gr["suppressed"]:
                facts += [f"{gr['median']:.1f}%", str(gr["peer_count"])]
        return {"tool": "peer_benchmark", "metric": metric, "period": period, "vertical": vertical,
                "group_by": group_by, "groups": groups, "rules": {"min_peers": MIN_PEERS,
                "max_peer_share": MAX_PEER_SHARE}, "source": m.source, "facts": facts}

    # Registry used by the LLM orchestrator ------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        fn = {"metric_query": self.metric_query, "driver_breakdown": self.driver_breakdown,
              "anomaly_detector": self.anomaly_detector, "peer_benchmark": self.peer_benchmark}[name]
        return fn(**args)


TOOL_SCHEMAS = [
    {"name": "metric_query",
     "description": "Get the official value of a governed metric for the current partner for one month.",
     "input_schema": {"type": "object", "properties": {
         "metric": {"type": "string", "enum": ["attach_rate", "policies_sold", "eligible_bookings", "premium"]},
         "period": {"type": "string", "description": "Month as YYYY-MM"},
         "filters": {"type": "object", "description": "Optional, e.g. {\"device\": \"app\"}"}},
         "required": ["metric", "period"]}},
    {"name": "driver_breakdown",
     "description": "Explain a change in a ratio metric between two months by segment, split into rate and mix effects.",
     "input_schema": {"type": "object", "properties": {
         "metric": {"type": "string", "enum": ["attach_rate"]},
         "base_period": {"type": "string"}, "compare_period": {"type": "string"},
         "dimensions": {"type": "array", "items": {"type": "string", "enum": ["device", "market"]}}},
         "required": ["metric", "base_period", "compare_period"]}},
    {"name": "anomaly_detector",
     "description": "Find the date of the strongest shift in a daily metric and any integration changes near it.",
     "input_schema": {"type": "object", "properties": {
         "metric": {"type": "string", "enum": ["attach_rate"]},
         "start": {"type": "string", "description": "YYYY-MM-DD"}, "end": {"type": "string"},
         "filters": {"type": "object"}}, "required": ["metric", "start", "end"]}},
    {"name": "peer_benchmark",
     "description": "Privacy-safe comparison with similar partners, grouped by placement. Groups may be suppressed.",
     "input_schema": {"type": "object", "properties": {
         "metric": {"type": "string", "enum": ["attach_rate"]}, "period": {"type": "string"}},
         "required": ["metric", "period"]}},
]
