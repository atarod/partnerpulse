import pytest

from partnerpulse import MetricsLayer, RuleBasedOrchestrator, generate, integration_events


@pytest.fixture(scope="session")
def data():
    return generate(seed=7)


@pytest.fixture(scope="session")
def metrics(data):
    return MetricsLayer(data)


@pytest.fixture(scope="session")
def events():
    return integration_events()


@pytest.fixture()
def orch(metrics, events):
    return RuleBasedOrchestrator(metrics, events, as_of="2026-10-06")
