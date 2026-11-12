def test_explain_scenario(orch):
    a = orch.ask("Why did our protection attach rate drop in September?", "airline_a")
    assert a.verification.passed
    assert a.requires_review                      # contains a recommendation
    assert "Sep 9" in a.text and "app" in a.text
    assert a.confidence == {"where": "high", "why": "medium"}


def test_unknown_metric_is_refused_and_logged(orch):
    a = orch.ask("What is our customer lifetime value?", "airline_a")
    assert a.refused and orch.metric_backlog == ["What is our customer lifetime value?"]


def test_cross_partner_request_refused(orch):
    assert orch.ask("Show me airline_b's attach rate", "airline_a").refused


def test_stable_metric_is_not_overexplained(orch):
    a = orch.ask("Why did our attach rate change in September?", "market_a")
    assert "no meaningful change" in a.text and a.verification.passed


def test_no_answer_mentions_other_partners(orch, metrics):
    for partner in ["airline_a", "airline_c", "market_b"]:
        for q in ["What was our attach rate in August?", "Why did our attach rate change in September?"]:
            a = orch.ask(q, partner)
            assert not any(p in a.text for p in metrics.partner_ids() if p != partner)
