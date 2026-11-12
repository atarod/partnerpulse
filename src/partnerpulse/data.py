"""Synthetic data for the fictional Tidewell Protect platform.

Generates daily sales of protection by partner, device and market. One partner,
``airline_a``, moves its mobile-app offer to after payment on 2026-09-09, which
is the story used in the demo scenario. All numbers are invented.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEVICES = {"app": 0.45, "mobile_web": 0.20, "desktop": 0.35}
MARKETS = {"GB": 0.35, "DE": 0.25, "ES": 0.20, "TR": 0.20}
START, END = "2026-06-01", "2026-10-05"
PLACEMENT_CHANGE_DATE = pd.Timestamp("2026-09-09")


@dataclass(frozen=True)
class PartnerSpec:
    partner_id: str
    vertical: str
    daily_bookings: int
    placement: str            # "before_payment" or "after_payment"
    base_rate: float          # attach rate as a fraction
    avg_premium: float


DEVICE_MULTIPLIER = {"app": 1.02, "mobile_web": 0.92, "desktop": 1.0}


def partner_specs() -> list[PartnerSpec]:
    specs = [PartnerSpec("airline_a", "airline", 13300, "before_payment", 0.0745, 20.0)]
    before = [("airline_b", 9000, 0.071), ("airline_c", 7000, 0.079), ("airline_d", 5000, 0.066),
              ("airline_e", 8000, 0.082), ("airline_f", 6000, 0.074), ("airline_g", 4000, 0.069)]
    after = [("airline_h", 8000, 0.044), ("airline_i", 6000, 0.038), ("airline_j", 5000, 0.047),
             ("airline_k", 7000, 0.041), ("airline_l", 4000, 0.049)]
    specs += [PartnerSpec(p, "airline", n, "before_payment", r, 20.0) for p, n, r in before]
    specs += [PartnerSpec(p, "airline", n, "after_payment", r, 20.0) for p, n, r in after]
    specs += [PartnerSpec("market_a", "marketplace", 20000, "before_payment", 0.031, 6.0),
              PartnerSpec("market_b", "marketplace", 15000, "after_payment", 0.022, 6.0),
              PartnerSpec("market_c", "marketplace", 9000, "before_payment", 0.028, 6.0)]
    return specs


# airline_a gets explicit per-device rates so the scenario is easy to follow
AIRLINE_A_RATES = {"app": 0.075, "mobile_web": 0.067, "desktop": 0.074}
AIRLINE_A_APP_AFTER_CHANGE = 0.036


def generate(seed: int = 7, start: str = START, end: str = END) -> pd.DataFrame:
    """Return one row per date x partner x device x market."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    rows = []
    for spec in partner_specs():
        for date in dates:
            weekday_factor = 1.08 if date.weekday() in (0, 4) else (0.9 if date.weekday() == 6 else 1.0)
            for device, dev_share in DEVICES.items():
                placement = spec.placement
                if spec.partner_id == "airline_a":
                    rate = AIRLINE_A_RATES[device]
                    if device == "app" and date >= PLACEMENT_CHANGE_DATE:
                        rate, placement = AIRLINE_A_APP_AFTER_CHANGE, "after_payment"
                else:
                    rate = spec.base_rate * DEVICE_MULTIPLIER[device]
                for market, mkt_share in MARKETS.items():
                    eligible = int(rng.poisson(spec.daily_bookings * dev_share * mkt_share * weekday_factor))
                    sold = int(rng.binomial(eligible, rate)) if eligible else 0
                    rows.append((date, spec.partner_id, spec.vertical, device, market, placement,
                                 eligible, sold, round(sold * spec.avg_premium, 2)))
    return pd.DataFrame(rows, columns=["date", "partner_id", "vertical", "device", "market", "placement",
                                       "eligible_bookings", "policies_sold", "premium"])


def integration_events() -> pd.DataFrame:
    """Changes the platform can see in partner integrations (e.g. when the offer is requested)."""
    return pd.DataFrame([{
        "date": PLACEMENT_CHANGE_DATE, "partner_id": "airline_a", "device": "app",
        "event": "Offer placement changed from before_payment to after_payment",
        "placement_from": "before_payment", "placement_to": "after_payment",
    }])
