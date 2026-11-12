from partnerpulse.verifier import verify

PARTNERS = ["airline_a", "airline_b"]


def test_accepts_numbers_from_facts_and_roundings():
    v = verify("Attach rate was 7.4% on 414,092 bookings.", ["7.42%", "414,092"], "airline_a", PARTNERS, False)
    assert v.passed


def test_rejects_invented_number():
    v = verify("Attach rate was 8.9%.", ["7.4%"], "airline_a", PARTNERS, False)
    assert not v.passed and v.unverified_numbers == ["8.9"]


def test_rejects_other_partner_names():
    v = verify("airline_b sells more.", [], "airline_a", PARTNERS, False)
    assert not v.passed and v.leaked_partners == ["airline_b"]


def test_recommendations_need_review():
    assert verify("Test it for 50% of users.", [], "airline_a", PARTNERS, True).requires_review
