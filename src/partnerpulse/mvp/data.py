"""Synthetic dataset for the MVP, with planted stories and ground truth.

Everything is fictional. Each planted story has a known correct answer, so the
dataset doubles as an evaluation set for detection and explanation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

START, END, AS_OF = "2026-06-01", "2026-10-31", "2026-10-31"
LY_START, LY_END = "2025-06-01", "2025-10-31"   # last year, for year-on-year baselines
DEVICES = {"app": 0.45, "mobile_web": 0.20, "desktop": 0.35}
DEVICE_RATE = {"app": 1.02, "mobile_web": 0.92, "desktop": 1.0}
MARKETS = {"travel": {"UK": 0.35, "DE": 0.25, "ES": 0.25, "AE": 0.15},
           "ecommerce": {"UK": 0.40, "DE": 0.30, "US": 0.30},
           "fintech": {"UK": 0.50, "DE": 0.30, "ES": 0.20}}
DAILY = {"large": 6000, "medium": 2500, "small": 400}
PRICE = {"travel": 18.0, "ecommerce": 9.0, "fintech": 6.0}


@dataclass
class Partner:
    partner_id: str
    name: str
    vertical: str
    size: str
    account_manager: str
    base_rate: float
    story: str = "steady"


PARTNERS = [
    Partner("p01", "SkyBridge Air", "travel", "large", "Maya", 0.074, "placement_drop"),
    Partner("p02", "Nordlys Travel", "travel", "medium", "Maya", 0.080, "price_increase"),
    Partner("p03", "Atlas Journeys", "travel", "medium", "Maya", 0.070, "market_dip"),
    Partner("p04", "Meridian Fly", "travel", "medium", "Maya", 0.066, "market_dip"),
    Partner("p05", "Sunwise Holidays", "travel", "medium", "Leo", 0.072, "seasonal_only"),
    Partner("p06", "Costa Verde Trips", "travel", "medium", "Leo", 0.068, "market_dip+claims"),
    Partner("p07", "Harbor Rail", "travel", "medium", "Leo", 0.075, "gradual_drift"),
    Partner("p08", "Cartwell", "ecommerce", "large", "Leo", 0.050, "checkout_redesign"),
    Partner("p09", "Bramble Market", "ecommerce", "medium", "Sara", 0.060, "mix_shift"),
    Partner("p10", "Kettle & Co", "ecommerce", "medium", "Sara", 0.055, "steady"),
    Partner("p11", "PocketPay", "fintech", "small", "Sara", 0.030, "noise_only"),
    Partner("p12", "Ledgerly", "fintech", "medium", "Sara", 0.035, "steady"),
]

D = pd.Timestamp
PLACEMENT_DATE, PRICE_DATE, REDESIGN_DATE = D("2026-09-09"), D("2026-08-20"), D("2026-09-15")
MIX_DATE, MARKET_DIP_DATE, CLAIMS_FROM = D("2026-09-01"), D("2026-09-22"), D("2026-08-01")


def travel_season(date: pd.Timestamp) -> float:
    """Summer peak in travel, centred on the end of July."""
    return float(np.exp(-((date.dayofyear - 212) / 25.0) ** 2))


def generate(seed: int = 11) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(LY_START, LY_END, freq="D").append(pd.date_range(START, END, freq="D"))
    sales, changes = [], []
    for p in PARTNERS:
        for date in dates:
            wk = 1.08 if date.weekday() in (0, 4) else (0.9 if date.weekday() == 6 else 1.0)
            season = travel_season(date) if p.vertical == "travel" else 0.0
            vol_mult = wk * (1 + 0.35 * season)
            rate_mult = 1 + 0.15 * season
            devices = dict(DEVICES)
            if p.story == "mix_shift" and date >= MIX_DATE:
                devices = {"app": 0.55, "mobile_web": 0.15, "desktop": 0.30}
            elif p.story == "mix_shift":
                devices = {"app": 0.25, "mobile_web": 0.25, "desktop": 0.50}
            price = PRICE[p.vertical]
            for device, dshare in devices.items():
                rate = p.base_rate * DEVICE_RATE[device] * rate_mult
                placement = "before_payment"
                if p.story == "placement_drop" and device == "app" and date >= PLACEMENT_DATE:
                    rate, placement = 0.036 * rate_mult, "after_payment"
                if p.story == "mix_shift":
                    rate = {"app": 0.035, "mobile_web": 0.060, "desktop": 0.075}[device]
                for market, mshare in MARKETS[p.vertical].items():
                    r, vol = rate, DAILY[p.size] * dshare * mshare * vol_mult
                    if p.story == "price_increase" and date >= PRICE_DATE:
                        price, r = 22.0, rate * 0.82
                    elif p.story == "price_increase":
                        price = 15.0
                    if p.story == "checkout_redesign" and date >= REDESIGN_DATE:
                        r = rate * 1.24
                    if p.story == "gradual_drift" and date >= D(START):
                        r = rate * (1 - 0.27 * (date - D(START)).days / (D(END) - D(START)).days)
                    if "market_dip" in p.story and market == "AE" and date >= MARKET_DIP_DATE:
                        r, vol = rate * 0.6, vol * 0.7
                    eligible = int(rng.poisson(vol))
                    sold = int(rng.binomial(eligible, min(r, 0.99))) if eligible else 0
                    sales.append((date, p.partner_id, device, market, placement, price, eligible, sold,
                                  round(sold * price, 2)))
    sales_df = pd.DataFrame(sales, columns=["date", "partner_id", "device", "market", "placement",
                                            "price_point", "eligible_bookings", "policies_sold", "premium"])
    changes += [(PLACEMENT_DATE, "p01", "app", "Offer moved from before to after payment", "placement"),
                (PRICE_DATE, "p02", "all", "Protection price changed from $15 to $22", "price"),
                (REDESIGN_DATE, "p08", "all", "Checkout redesign released", "checkout")]
    changes_df = pd.DataFrame(changes, columns=["date", "partner_id", "device", "change", "change_type"])
    claims_df = _claims(sales_df, rng)
    partners_df = pd.DataFrame([{k: v for k, v in p.__dict__.items() if k != "story"} for p in PARTNERS])
    actions_df = pd.DataFrame(columns=["insight_id", "partner_id", "account_manager", "decision", "useful",
                                       "acted_on", "timestamp"])
    return {"partners": partners_df, "daily_sales": sales_df, "integration_changes": changes_df,
            "claims": claims_df, "am_actions": actions_df}


CLAIM_RATES = {"flight_delay": 0.020, "cancellation": 0.015, "baggage": 0.005}


def _claims(sales: pd.DataFrame, rng) -> pd.DataFrame:
    """Claims for travel policies, arriving 2 to 8+ weeks after the sale. Only claims
    reported by the as-of date are visible, which creates the claims-lag effect."""
    travel_ids = {p.partner_id for p in PARTNERS if p.vertical == "travel"}
    t = sales[sales.partner_id.isin(travel_ids) & (sales.date >= START)].groupby(["date", "partner_id", "market"], as_index=False)["policies_sold"].sum()
    rows, as_of = [], D(AS_OF)
    for r in t.itertuples():
        for reason, base in CLAIM_RATES.items():
            rate = base
            if r.partner_id == "p06" and r.market == "ES" and reason == "flight_delay" and r.date >= CLAIMS_FROM:
                rate = 0.05
            n = rng.binomial(r.policies_sold, rate)
            for _ in range(n):
                lag = 14 + rng.gamma(2.0, 12.0)
                claim_date = r.date + pd.Timedelta(days=int(lag))
                if claim_date <= as_of:
                    rows.append((r.date, claim_date, r.partner_id, r.market, reason,
                                 round(float(rng.lognormal(5.2, 0.5)), 2)))
    return pd.DataFrame(rows, columns=["sale_date", "claim_date", "partner_id", "market", "reason", "amount"])


GROUND_TRUTH = [
    {"story": 1, "scope": "partner", "id": "p01", "alert": "step", "direction": "down", "cause": "placement",
     "explain": "App only; offer moved after payment on Sep 9"},
    {"story": 2, "scope": "partner", "id": "p02", "alert": "step", "direction": "down", "cause": "price",
     "explain": "Price rose from $15 to $22: fewer policies, more premium each"},
    {"story": 3, "scope": "partner", "id": "p08", "alert": "step", "direction": "up", "cause": "checkout",
     "explain": "Checkout redesign lifted attach rate"},
    {"story": 4, "scope": "market", "id": "travel:AE", "alert": "market", "direction": "down",
     "partners": ["p03", "p04", "p06"], "explain": "Several travel partners dip in one market from Sep 22"},
    {"story": 5, "scope": "partner", "id": "p05", "alert": None, "explain": "Seasonal only: no alert"},
    {"story": 6, "scope": "partner", "id": "p11", "alert": None, "explain": "Noise on small volume: no alert"},
    {"story": 7, "scope": "partner", "id": "p07", "alert": "drift", "direction": "down",
     "explain": "Gradual decline, no single break"},
    {"story": 8, "scope": "partner", "id": "p09", "alert": "mix", "direction": "down",
     "explain": "Traffic shifted to the app; each device converts as before"},
    {"story": 9, "scope": "claims", "id": "p06:ES:flight_delay", "alert": "claims", "direction": "up",
     "explain": "Delay claims rising; recent weeks look low only because of claims lag"},
    {"story": None, "scope": "partner", "id": "p10", "alert": None, "explain": "Steady"},
    {"story": None, "scope": "partner", "id": "p12", "alert": None, "explain": "Steady"},
]


def write(out_dir: str | Path = "data/mvp", seed: int = 11) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in generate(seed).items():
        df.to_csv(out / f"{name}.csv", index=False)
    (out / "ground_truth.json").write_text(json.dumps(GROUND_TRUTH, indent=2))
    return out
