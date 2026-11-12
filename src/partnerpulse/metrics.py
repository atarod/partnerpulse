"""Metrics layer: the single source of governed metric definitions.

Dashboards and the agent both query this layer, so their numbers always agree.
Access is scoped to the session's partner here, in the data layer, rather than
by instructions in a prompt.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


class AccessDenied(Exception):
    """Raised when a session asks for another partner's data."""


class UnknownMetric(Exception):
    """Raised when a metric has no governed definition."""


@dataclass(frozen=True)
class MetricDef:
    name: str
    description: str
    numerator: str
    denominator: str | None
    unit: str
    version: int

    @property
    def source(self) -> str:
        return f"metrics:{self.name}:v{self.version}"


REGISTRY: dict[str, MetricDef] = {
    "attach_rate": MetricDef("attach_rate", "Policies sold divided by eligible bookings",
                             "policies_sold", "eligible_bookings", "pct", 3),
    "policies_sold": MetricDef("policies_sold", "Number of protection policies sold",
                               "policies_sold", None, "count", 1),
    "eligible_bookings": MetricDef("eligible_bookings", "Transactions where protection was offered",
                                   "eligible_bookings", None, "count", 1),
    "premium": MetricDef("premium", "Gross premium sold, in USD", "premium", None, "usd", 1),
}


def get_metric(name: str) -> MetricDef:
    if name not in REGISTRY:
        raise UnknownMetric(name)
    return REGISTRY[name]


def compute(df: pd.DataFrame, m: MetricDef) -> float:
    num = float(df[m.numerator].sum())
    if m.denominator is None:
        return num
    den = float(df[m.denominator].sum())
    return 100.0 * num / den if den else float("nan")


class MetricsLayer:
    def __init__(self, data: pd.DataFrame):
        self._data = data

    def _scoped(self, partner_id: str, session_partner: str) -> pd.DataFrame:
        if partner_id != session_partner:
            raise AccessDenied(f"session for {session_partner} cannot read {partner_id}")
        return self._data[self._data.partner_id == partner_id]

    @staticmethod
    def _filter(df: pd.DataFrame, start: str, end: str, filters: dict | None) -> pd.DataFrame:
        df = df[(df.date >= pd.Timestamp(start)) & (df.date <= pd.Timestamp(end))]
        for col, val in (filters or {}).items():
            df = df[df[col] == val]
        return df

    def query(self, metric: str, partner_id: str, start: str, end: str, *, session_partner: str,
              group_by: str | None = None, filters: dict | None = None) -> dict:
        m = get_metric(metric)
        df = self._filter(self._scoped(partner_id, session_partner), start, end, filters)
        out = {"metric": m.name, "definition": m.description, "unit": m.unit, "source": m.source,
               "partner_id": partner_id, "start": start, "end": end, "filters": filters or {}}
        if group_by is None:
            out["value"] = compute(df, m)
            if m.denominator:
                out["denominator"] = int(df[m.denominator].sum())
            return out
        rows = []
        for seg, g in df.groupby(group_by):
            row = {"segment": str(seg), "value": compute(g, m), "numerator": float(g[m.numerator].sum())}
            if m.denominator:
                row["denominator"] = float(g[m.denominator].sum())
            rows.append(row)
        out["group_by"], out["rows"] = group_by, rows
        return out

    def daily_series(self, metric: str, partner_id: str, start: str, end: str, *, session_partner: str,
                     filters: dict | None = None) -> pd.Series:
        m = get_metric(metric)
        df = self._filter(self._scoped(partner_id, session_partner), start, end, filters)
        return df.groupby("date").apply(lambda g: compute(g, m), include_groups=False)

    def vertical_of(self, partner_id: str) -> str:
        return str(self._data.loc[self._data.partner_id == partner_id, "vertical"].iloc[0])

    def partner_ids(self) -> list[str]:
        return sorted(self._data.partner_id.unique())

    def peer_frame(self, vertical: str, exclude: str, start: str, end: str) -> pd.DataFrame:
        """Raw peer rows. Only the benchmark tool may call this, and it applies privacy rules."""
        d = self._data
        d = d[(d.vertical == vertical) & (d.partner_id != exclude)]
        return self._filter(d, start, end, None)
