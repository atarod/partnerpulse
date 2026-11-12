"""Monitoring: scheduled anomaly checks that turn into proactive alerts."""
from __future__ import annotations

import pandas as pd

from .metrics import MetricsLayer
from .tools import Toolbox, fmt_date


def scan(metrics: MetricsLayer, events: pd.DataFrame, as_of: str, lookback_days: int = 60,
         recent_days: int = 14) -> list[dict]:
    end = pd.Timestamp(as_of) - pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=lookback_days)
    alerts = []
    for partner in metrics.partner_ids():
        tools = Toolbox(metrics, events, partner)
        a = tools.anomaly_detector("attach_rate", str(start.date()), str(end.date()), min_after=3)
        if not a["significant"]:
            continue
        change = pd.Timestamp(a["change_date"])
        if (end - change).days > recent_days:
            continue
        direction = "dropped" if a["shift_pts"] < 0 else "rose"
        alerts.append({"partner_id": partner, "change_date": a["change_date"],
                       "message": f"Attach rate {direction} from {a['mean_before']:.1f}% to "
                                  f"{a['mean_after']:.1f}% starting {fmt_date(change)}.",
                       "related_events": a["related_events"]})
    return alerts
