import pytest

from partnerpulse.metrics import AccessDenied, UnknownMetric


def test_attach_rate_matches_definition(metrics, data):
    r = metrics.query("attach_rate", "airline_a", "2026-08-01", "2026-08-31", session_partner="airline_a")
    d = data[(data.partner_id == "airline_a") & (data.date.dt.month == 8)]
    assert r["value"] == pytest.approx(100 * d.policies_sold.sum() / d.eligible_bookings.sum())
    assert r["source"] == "metrics:attach_rate:v3"


def test_cannot_read_other_partner(metrics):
    with pytest.raises(AccessDenied):
        metrics.query("attach_rate", "airline_b", "2026-08-01", "2026-08-31", session_partner="airline_a")


def test_unknown_metric(metrics):
    with pytest.raises(UnknownMetric):
        metrics.query("lifetime_value", "airline_a", "2026-08-01", "2026-08-31", session_partner="airline_a")
