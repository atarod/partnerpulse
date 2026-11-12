import pytest

from partnerpulse.mvp.data import GROUND_TRUTH, generate
from partnerpulse.mvp.detect import run


@pytest.fixture(scope="module")
def mvp():
    data = generate(11)
    return data, run(data)


def by_id(alerts, id_):
    return [a for a in alerts if a["id"] == id_]


def test_tables_present(mvp):
    data, _ = mvp
    assert set(data) == {"partners", "daily_sales", "integration_changes", "claims", "am_actions"}
    assert len(data["partners"]) == 12


def test_claims_only_visible_up_to_as_of(mvp):
    data, _ = mvp
    assert data["claims"].claim_date.max() <= __import__("pandas").Timestamp("2026-10-31")


def test_placement_story_found_with_cause(mvp):
    a = by_id(mvp[1], "p01")[0]
    assert a["alert"] == "step" and a["cause"] == "placement" and "Sep 9" in a["message"]


def test_price_story_explains_revenue_tradeoff(mvp):
    a = by_id(mvp[1], "p02")[0]
    assert a["cause"] == "price" and "revenue rose" in a["message"]


def test_mix_effect_not_called_a_conversion_problem(mvp):
    assert by_id(mvp[1], "p09")[0]["alert"] == "mix"


def test_market_dip_grouped_not_three_partner_alerts(mvp):
    m = by_id(mvp[1], "travel:AE")[0]
    assert sorted(m["partners"]) == ["p03", "p04", "p06"]
    assert not by_id(mvp[1], "p03") and not by_id(mvp[1], "p04")


def test_no_false_alarms_on_seasonal_noisy_or_steady(mvp):
    for pid in ["p05", "p10", "p11", "p12"]:
        assert not by_id(mvp[1], pid)


def test_claims_lag_adjusted(mvp):
    a = by_id(mvp[1], "p06:ES:flight_delay")[0]
    assert "claims still to arrive" in a["message"]

