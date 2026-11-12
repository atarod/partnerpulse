import pandas as pd
import pytest

from partnerpulse.metrics import MetricsLayer
from partnerpulse.tools import Toolbox


def test_rate_and_mix_effects_add_up(metrics, events):
    t = Toolbox(metrics, events, "airline_a")
    out = t.driver_breakdown("attach_rate", "2026-08", "2026-09", ["device"])
    total = sum(s["total_pts"] for s in out["dimensions"][0]["segments"])
    assert total == pytest.approx(out["total_change_pts"], abs=1e-9)
    assert out["dimensions"][0]["top_segment"] == "app"


def test_anomaly_finds_placement_change(metrics, events):
    t = Toolbox(metrics, events, "airline_a")
    a = t.anomaly_detector("attach_rate", "2026-08-01", "2026-09-30", filters={"device": "app"})
    assert a["significant"]
    assert abs((pd.Timestamp(a["change_date"]) - pd.Timestamp("2026-09-09")).days) <= 1
    assert a["related_events"], "the integration change should be linked"


def test_no_false_alarm_on_stable_partner(metrics, events):
    t = Toolbox(metrics, events, "airline_b")
    assert not t.anomaly_detector("attach_rate", "2026-08-01", "2026-09-30")["significant"]


def test_benchmark_excludes_self_and_respects_min_peers(metrics, events):
    airline = Toolbox(metrics, events, "airline_a").peer_benchmark("attach_rate", "2026-09")
    assert all(not g["suppressed"] for g in airline["groups"])
    market = Toolbox(metrics, events, "market_a").peer_benchmark("attach_rate", "2026-09")
    assert all(g["suppressed"] for g in market["groups"])


def test_benchmark_dominance_rule(data, events):
    d = data[data.vertical == "airline"].copy()
    d.loc[d.partner_id == "airline_h", "eligible_bookings"] *= 50   # one huge peer
    t = Toolbox(MetricsLayer(d), events, "airline_a")
    groups = {g["group"]: g for g in t.peer_benchmark("attach_rate", "2026-09")["groups"]}
    assert groups["after_payment"]["suppressed"]
    assert "dominates" in groups["after_payment"]["reason"]
