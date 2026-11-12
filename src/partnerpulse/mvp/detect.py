"""Detection and explanation for the MVP copilot.

All numbers are computed here in code; an LLM (optional) only rewrites the
explanations. Partner-level: step changes, gradual drift, mix effects.
Market-level: one market moving for several partners. Claims: rising claims
after adjusting for claims that have not arrived yet (claims lag).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .data import AS_OF, PARTNERS, START

NAMES = {p.partner_id: p.name for p in PARTNERS}
VERTICAL = {p.partner_id: p.vertical for p in PARTNERS}
STEP_T, STEP_REL = 6.0, 0.10
DRIFT_T, DRIFT_REL = 8.0, 0.15
WINDOW = 45


def _rate(df: pd.DataFrame) -> pd.Series:
    g = df.groupby("date")[["policies_sold", "eligible_bookings"]].sum()
    return g.policies_sold / g.eligible_bookings


def yoy_series(sales: pd.DataFrame, partner: str) -> tuple[pd.Series, pd.Series]:
    """This year's daily attach rate, and the ratio to the same weekday last year.
    The ratio removes seasonality, such as the summer travel peak."""
    d = sales[sales.partner_id == partner]
    cur = _rate(d[d.date >= START])
    ly = _rate(d[d.date < START])
    ly.index = ly.index + pd.Timedelta(days=364)
    ly_smooth = ly.rolling(7, center=True, min_periods=1).mean()
    return cur, (cur / ly_smooth.reindex(cur.index)).dropna()


def step_scan(vals: np.ndarray, min_side: int = 10):
    best = None
    for k in range(min_side, len(vals) - min_side):
        b, a = vals[max(0, k - WINDOW):k], vals[k:k + WINDOW]
        se = math.sqrt(b.var(ddof=1) / len(b) + a.var(ddof=1) / len(a)) or 1e-12
        t = (a.mean() - b.mean()) / se
        if best is None or abs(t) > abs(best[1]):
            best = (k, t, (a.mean() - b.mean()) / b.mean())
    return best


def model_fit(vals: np.ndarray, k: int):
    x = np.arange(len(vals))
    coef = np.polyfit(x, vals, 1)
    resid_lin = vals - np.polyval(coef, x)
    se_slope = math.sqrt((resid_lin ** 2).sum() / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
    step_fit = np.where(x < k, vals[:k].mean(), vals[k:].mean())
    return {"slope_t": coef[0] / se_slope, "drift_rel": coef[0] * len(x) / vals.mean(),
            "sse_lin": float((resid_lin ** 2).sum()), "sse_step": float(((vals - step_fit) ** 2).sum())}


def decompose(sales: pd.DataFrame, partner: str, date: pd.Timestamp, dim: str, days: int = 28) -> dict:
    d = sales[sales.partner_id == partner]
    before = d[(d.date < date) & (d.date >= date - pd.Timedelta(days=days))]
    after = d[(d.date >= date) & (d.date < date + pd.Timedelta(days=days))]
    def seg(x):
        g = x.groupby(dim)[["policies_sold", "eligible_bookings"]].sum()
        return g.eligible_bookings / g.eligible_bookings.sum(), g.policies_sold / g.eligible_bookings
    s0, r0 = seg(before)
    s1, r1 = seg(after)
    rows = []
    for k in sorted(set(s0.index) | set(s1.index)):
        rate_eff = s0.get(k, 0) * (r1.get(k, 0) - r0.get(k, 0))
        mix_eff = (s1.get(k, 0) - s0.get(k, 0)) * r1.get(k, 0)
        rows.append({"segment": k, "share_before": s0.get(k, 0), "share_after": s1.get(k, 0),
                     "rate_before": r0.get(k, 0), "rate_after": r1.get(k, 0),
                     "rate_effect": rate_eff, "mix_effect": mix_eff, "total": rate_eff + mix_eff})
    rows.sort(key=lambda r: abs(r["total"]), reverse=True)
    total = sum(r["total"] for r in rows)
    mix_share = sum(r["mix_effect"] for r in rows) / total if total else 0
    conc = abs(rows[0]["total"]) / (sum(abs(r["total"]) for r in rows) or 1)
    return {"dim": dim, "rows": rows, "total": total, "mix_share": mix_share, "concentration": conc,
            "before": (before.policies_sold.sum() / before.eligible_bookings.sum()),
            "after": (after.policies_sold.sum() / after.eligible_bookings.sum()),
            "premium_per_booking": (before.premium.sum() / before.eligible_bookings.sum(),
                                    after.premium.sum() / after.eligible_bookings.sum())}


def fmt_date(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.strftime('%b')} {ts.day}"


def partner_alerts(data: dict) -> list[dict]:
    sales, changes = data["daily_sales"], data["integration_changes"]
    out = []
    for p in NAMES:
        raw, yoy = yoy_series(sales, p)
        adj = yoy.values
        k, t, rel = step_scan(adj)
        fit = model_fit(adj, k)
        step_sig = abs(t) >= STEP_T and abs(rel) >= STEP_REL
        drift_sig = abs(fit["slope_t"]) >= DRIFT_T and abs(fit["drift_rel"]) >= DRIFT_REL
        if not (step_sig or drift_sig):
            continue
        if drift_sig and (not step_sig or fit["sse_lin"] < 0.9 * fit["sse_step"]):
            d = "down" if fit["drift_rel"] < 0 else "up"
            out.append({"scope": "partner", "id": p, "alert": "drift", "direction": d, "cause": None,
                        "date": None, "message": f"{NAMES[p]}: compared with last year, attach rate has drifted {d} about "
                        f"{abs(fit['drift_rel']) * 100:.0f}% over five months, with no single break. "
                        "Worth reviewing offer freshness and checkout changes with the partner."})
            continue
        date = yoy.index[k]
        dev, mkt = decompose(sales, p, date, "device"), decompose(sales, p, date, "market")
        main = dev if dev["concentration"] >= mkt["concentration"] else mkt
        d = "down" if rel < 0 else "up"
        ev = changes[(changes.partner_id == p) & ((changes.date - date).abs() <= pd.Timedelta(days=2))]
        cause = ev.change_type.iloc[0] if len(ev) else None
        msg = (f"{NAMES[p]}: attach rate {'fell' if d == 'down' else 'rose'} from {dev['before'] * 100:.1f}% "
               f"to {dev['after'] * 100:.1f}% starting {fmt_date(date)}.")
        alert = "step"
        if abs(dev["mix_share"]) >= 0.6 and abs(dev["total"]) > 0:
            alert = "mix"
            top = max(dev["rows"], key=lambda r: r["share_after"] - r["share_before"])
            msg += (f" This is a mix effect: {top['segment'].replace('_', ' ')} share rose from "
                    f"{top['share_before'] * 100:.0f}% to {top['share_after'] * 100:.0f}% of bookings, "
                    "while each device converts about as before.")
        else:
            top = main["rows"][0]
            if main["concentration"] >= 0.5:
                msg += (f" Most of the change is in {top['segment'].replace('_', ' ')} ({main['dim']}), "
                        f"from {top['rate_before'] * 100:.1f}% to {top['rate_after'] * 100:.1f}%.")
            else:
                msg += " The change is spread evenly across devices and markets."
        if cause:
            msg += f" Same day, the integration log shows: {ev.change.iloc[0]}."
        if cause == "price":
            a, b = dev["premium_per_booking"]
            trend = "rose" if b > a * 1.02 else ("fell" if b < a * 0.98 else "held steady")
            msg += (f" Premium per eligible booking moved from ${a:.2f} to ${b:.2f}, so revenue "
                    f"{trend} despite fewer policies.")
        if cause == "placement":
            msg += " Suggested next step: test moving the offer back before payment for 50% of app users."
        out.append({"scope": "partner", "id": p, "alert": alert, "direction": d, "cause": cause,
                    "date": str(date.date()), "top_market": mkt["rows"][0]["segment"], "message": msg})
    return out


def market_alerts(data: dict) -> list[dict]:
    """A market moving relative to the same partners' other markets, for several partners."""
    sales, out = data["daily_sales"], []
    travel = [p for p, v in VERTICAL.items() if v == "travel"]
    for m in sorted(sales[sales.partner_id.isin(travel)].market.unique()):
        logs = {}
        for p in travel:
            d = sales[(sales.partner_id == p) & (sales.date >= START)]
            logs[p] = np.log(_rate(d[d.market == m]) / _rate(d[d.market != m]))
        avg = pd.concat(logs, axis=1).mean(axis=1)
        k, t, _ = step_scan(avg.values)
        shift = avg.values[k:k + 28].mean() - avg.values[max(0, k - 28):k].mean()
        if abs(t) < STEP_T or abs(math.expm1(shift)) < STEP_REL:
            continue
        date = avg.index[k]
        affected = []
        for p, s in logs.items():
            b, a = s.values[max(0, k - 28):k], s.values[k:k + 28]
            se = math.sqrt(b.var(ddof=1) / len(b) + a.var(ddof=1) / len(a))
            if a.mean() - b.mean() <= math.log(0.85) and abs((a.mean() - b.mean()) / se) >= 3:
                affected.append(p)
        if len(affected) >= 2:
            names = ", ".join(NAMES[p] for p in affected)
            out.append({"scope": "market", "id": f"travel:{m}", "alert": "market",
                        "direction": "down" if shift < 0 else "up", "date": str(date.date()),
                        "partners": affected, "message": f"Travel partners selling in {m} saw attach rate "
                        f"{'fall' if shift < 0 else 'rise'} about {abs(math.expm1(shift)) * 100:.0f}% relative to "
                        f"their other markets from {fmt_date(date)}: {names}. No partner change was logged, "
                        "so this looks market-level rather than a partner issue."})
    return out


def claims_alerts(data: dict, ratio_min: float = 1.5, min_claims: int = 30, z_min: float = 4.0) -> list[dict]:
    """Rising claims after adjusting for claims still to come (chain-ladder style)."""
    claims, sales, as_of = data["claims"], data["daily_sales"], pd.Timestamp(AS_OF)
    dev = claims[claims.sale_date <= "2026-06-30"]
    lags = np.sort((dev.claim_date - dev.sale_date).dt.days.values)
    F = lambda age: np.searchsorted(lags, age, side="right") / len(lags)
    pol = sales[sales.date >= START].groupby(["date", "partner_id", "market"])["policies_sold"].sum()
    out = []
    for (p, m, reason), c in claims.groupby(["partner_id", "market", "reason"]):
        pp = pol.xs((p, m), level=("partner_id", "market"))
        dates = pp.index
        expo = pd.Series(pp.values * F((as_of - dates).days.values), index=dates)
        base_mask = (dates >= "2026-06-01") & (dates <= "2026-07-31")
        rec_mask = (dates >= "2026-08-01") & (dates <= "2026-09-30")
        cr = c[(c.sale_date >= "2026-08-01") & (c.sale_date <= "2026-09-30")]
        # Baseline pooled across the partner's markets: small markets alone are too noisy.
        pc = claims[(claims.partner_id == p) & (claims.reason == reason) &
                    (claims.sale_date >= "2026-06-01") & (claims.sale_date <= "2026-07-31")]
        pall = pol.xs(p, level="partner_id").groupby(level="date").sum()
        pall = pall[(pall.index >= "2026-06-01") & (pall.index <= "2026-07-31")]
        base_rate = len(pc) / (pall.values * F((as_of - pall.index).days.values)).sum()
        rec_rate = len(cr) / expo[rec_mask].sum()
        expected = base_rate * expo[rec_mask].sum()
        z = (len(cr) - expected) / math.sqrt(expected) if expected else 0
        if rec_rate / base_rate >= ratio_min and len(cr) >= min_claims and z >= z_min:
            raw_recent = len(cr) / pp[rec_mask].sum()
            out.append({"scope": "claims", "id": f"{p}:{m}:{reason}", "alert": "claims", "direction": "up",
                        "message": f"{NAMES[p]}, {m}, {reason.replace('_', ' ')} claims: estimated rate for "
                        f"Aug–Sep sales is {rec_rate * 100:.1f}% of policies vs {base_rate * 100:.1f}% before "
                        f"(×{rec_rate / base_rate:.1f}), after adjusting for claims still to arrive. Unadjusted, "
                        f"it looks like only {raw_recent * 100:.1f}%, because claims arrive weeks after the sale."})
    return out


def run(data: dict) -> list[dict]:
    market = market_alerts(data)
    partner = partner_alerts(data)
    # A partner alert explained by a market-level move is folded into the market alert.
    covered = {(p, a["id"].split(":")[1], a["date"]) for a in market for p in a["partners"]}
    partner = [a for a in partner if not any(a["id"] == p and a.get("top_market") == m and a["date"] and
               abs((pd.Timestamp(a["date"]) - pd.Timestamp(d)).days) <= 5 for p, m, d in covered)]
    return partner + market + claims_alerts(data)
