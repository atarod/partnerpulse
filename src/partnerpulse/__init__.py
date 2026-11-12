"""PartnerPulse: agentic insights for embedded protection partners (prototype)."""
from .agent import Answer, LLMOrchestrator, RuleBasedOrchestrator
from .data import generate, integration_events
from .metrics import MetricsLayer

__all__ = ["Answer", "LLMOrchestrator", "RuleBasedOrchestrator", "MetricsLayer", "generate",
           "integration_events", "build"]


def build(as_of: str = "2026-10-06", seed: int = 7, llm: bool = False):
    """Create an orchestrator over freshly generated synthetic data."""
    metrics, events = MetricsLayer(generate(seed)), integration_events()
    cls = LLMOrchestrator if llm else RuleBasedOrchestrator
    return cls(metrics, events, as_of=as_of)
