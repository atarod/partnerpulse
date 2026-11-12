"""Orchestrators: plan the steps, call tools, write the answer, then verify it.

``RuleBasedOrchestrator`` runs offline with a fixed planner and templates, so the
project works without an API key. ``LLMOrchestrator`` lets a Claude model plan and
write, using the same tools and the same verifier.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import pandas as pd

from .metrics import MetricsLayer, UnknownMetric, get_metric
from .tools import TOOL_SCHEMAS, Toolbox, fmt_date, month_range
from .verifier import Verification, verify

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
METRIC_WORDS = [("attach", "attach_rate"), ("premium", "premium"), ("policies", "policies_sold"),
                ("sold", "policies_sold"), ("bookings", "eligible_bookings")]
MIN_EXPLAINABLE_PTS = 0.3
EXPLAIN_WORDS = ("why", "drop", "fell", "fall", "decline", "down", "rise", "rose", "increase", "change")


@dataclass
class Answer:
    text: str
    confidence: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    verification: Verification | None = None
    refused: bool = False

    @property
    def requires_review(self) -> bool:
        return bool(self.verification and self.verification.requires_review)

    def render(self) -> str:
        lines = [self.text]
        if self.confidence:
            lines.append("Confidence: " + ", ".join(f"{k} {v}" for k, v in self.confidence.items()))
        if self.sources:
            lines.append("Sources: " + "; ".join(self.sources))
        if self.verification:
            v = self.verification
            status = "passed" if v.passed else f"FAILED {v.unverified_numbers or ''} {v.leaked_partners or ''}"
            lines.append(f"[verifier: {status}{' · routed to human review' if v.requires_review else ''}]")
        return "\n".join(lines)


def prev_month(period: str) -> str:
    ts = pd.Timestamp(period + "-01") - pd.offsets.MonthBegin(1)
    return ts.strftime("%Y-%m")


def parse_metric(q: str) -> str | None:
    ql = q.lower()
    for word, metric in METRIC_WORDS:
        if word in ql:
            return metric
    return None


def parse_period(q: str, as_of: str) -> str:
    ql = q.lower()
    year = pd.Timestamp(as_of).year
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b|\b{name[:3]}\b", ql):
            return f"{year:04d}-{num:02d}"
    return prev_month(pd.Timestamp(as_of).strftime("%Y-%m"))


class RuleBasedOrchestrator:
    def __init__(self, metrics: MetricsLayer, events: pd.DataFrame, as_of: str = "2026-10-06"):
        self.metrics, self.events, self.as_of = metrics, events, as_of
        self.metric_backlog: list[str] = []   # unanswerable questions become metric requests

    def ask(self, question: str, partner: str) -> Answer:
        tools = Toolbox(self.metrics, self.events, partner)
        metric = parse_metric(question)
        for other in self.metrics.partner_ids():
            if other != partner and other in question.lower():
                return Answer("I can only share data for your own account. I can compare you with "
                              "similar partners using anonymised benchmarks instead.", refused=True)
        if metric is None:
            self.metric_backlog.append(question)
            return Answer("I don't have a governed metric for that yet, so I won't estimate it. "
                          "I've logged the question for the metrics team.", refused=True)
        period = parse_period(question, self.as_of)
        if any(w in question.lower() for w in EXPLAIN_WORDS) and get_metric(metric).denominator:
            return self._explain(tools, metric, period, partner)
        return self._lookup(tools, metric, period, partner)

    def _finish(self, answer: Answer, partner: str, has_rec: bool) -> Answer:
        facts = [f for step in answer.trace for f in step.get("facts", [])]
        answer.verification = verify(answer.text, facts, partner, self.metrics.partner_ids(), has_rec)
        return answer

    def _lookup(self, tools: Toolbox, metric: str, period: str, partner: str) -> Answer:
        r = tools.metric_query(metric, period)
        label = metric.replace("_", " ")
        month = pd.Timestamp(period + "-01").strftime("%B %Y")
        text = f"Your {label} in {month} was {r['facts'][0]}."
        if "denominator" in r:
            text += f" That is based on {r['denominator']:,} eligible bookings."
        a = Answer(text, {"value": "high"}, [f"{r['source']}, {period}"], [r])
        return self._finish(a, partner, has_rec=False)

    def _explain(self, tools: Toolbox, metric: str, period: str, partner: str) -> Answer:
        base = prev_month(period)
        q_base, q_cmp = tools.metric_query(metric, base), tools.metric_query(metric, period)
        drivers = tools.driver_breakdown(metric, base, period)
        top_dim = drivers["dimensions"][0]
        seg, dim, share = top_dim["top_segment"], top_dim["dimension"], top_dim["top_share_of_change"]
        top = next(s for s in top_dim["segments"] if s["segment"] == seg)
        b0, _ = month_range(base)
        _, c1 = month_range(period)
        anomaly = tools.anomaly_detector(metric, b0, c1, filters={dim: seg})
        bench = tools.peer_benchmark(metric, period)
        trace = [q_base, q_cmp, drivers, anomaly, bench]

        mb, mc = pd.Timestamp(base + "-01").strftime("%B"), pd.Timestamp(period + "-01").strftime("%B")
        if abs(drivers["total_change_pts"]) < MIN_EXPLAINABLE_PTS:
            text = (f"Your {metric.replace('_', ' ')} was essentially stable: {q_base['facts'][0]} in {mb} "
                    f"and {q_cmp['facts'][0]} in {mc}. There is no meaningful change to explain.")
            a = Answer(text, {"value": "high"}, [f"{q_cmp['source']}, {base} vs {period}"], [q_base, q_cmp])
            return self._finish(a, partner, has_rec=False)
        direction = "fell" if drivers["total_change_pts"] < 0 else "rose"
        seg_label = seg.replace("_", " ")
        parts = [f"Your {metric.replace('_', ' ')} {direction} from {q_base['facts'][0]} in {mb} "
                 f"to {q_cmp['facts'][0]} in {mc}."]
        concentrated = top_dim["concentration"] >= 0.6 and share >= 0.6
        if concentrated:
            lead = "Nearly all of the change" if share >= 0.9 else f"About {share * 100:.0f}% of the change"
            parts.append(f"{lead} comes from {seg_label} "
                         f"({dim}), where the rate went from {top['base_rate']:.1f}% to {top['compare_rate']:.1f}%.")
        else:
            parts.append(f"The change is spread across segments; the largest contributor is {seg_label} ({dim}).")

        cause_conf, has_rec, event = "low", False, None
        if anomaly["significant"]:
            when = fmt_date(anomaly["change_date"])
            parts.append(f"The shift starts on {when}.")
            if anomaly["related_events"]:
                event = anomaly["related_events"][0]
                parts.append(f"On the same day your integration logged a change: "
                             f"{event['event'].replace('_', ' ')}.")
                cause_conf = "medium"   # strong timing evidence, but not tested

        groups = {g["group"]: g for g in bench["groups"]}
        visible = [g for g in groups.values() if not g["suppressed"]]
        if event and event.get("placement_to") in groups and not groups[event["placement_to"]]["suppressed"]:
            to, other = groups[event["placement_to"]], next(
                (g for g in visible if g["group"] != event["placement_to"]), None)
            if other:
                parts.append(f"Among {to['peer_count']} similar partners offering protection "
                             f"{to['group'].replace('_', ' ')}, the median attach rate is {to['median']:.1f}%, "
                             f"versus {other['median']:.1f}% for {other['peer_count']} partners offering it "
                             f"{other['group'].replace('_', ' ')}.")
                if other["median"] > to["median"]:
                    parts.append(f"Suggested next step: test moving the {seg_label} offer back "
                                 f"{other['group'].replace('_', ' ')} for 50% of users for 2 weeks.")
                    has_rec = True
        elif not visible:
            parts.append("Peer benchmarks are not available for your segment because there are too few "
                         "comparable partners to protect their privacy.")

        conf = {"where": "high" if concentrated else "medium", "why": cause_conf}
        sources = [f"{q_cmp['source']}, {base} vs {period}", f"driver breakdown by {dim}",
                   f"change-point analysis ({seg_label})"]
        if visible:
            sources.append(f"peer benchmark, {bench['vertical']}")
        a = Answer(" ".join(parts), conf, sources, trace)
        return self._finish(a, partner, has_rec)


SYSTEM_PROMPT = """You are PartnerPulse, an analyst for partners of an embedded protection platform.
Rules:
- Never calculate or estimate numbers yourself. Every number you state must come from a tool result.
- Use tools to confirm, locate, time and compare a change before explaining it.
- Separate where a change happened from why. Never claim a cause as proven without a test.
- If a metric is not available, say so instead of guessing.
- If you suggest an action, propose a 50% test for 2 weeks and label it a suggestion.
- Be concise: at most 6 sentences, then a line starting 'Confidence:'."""


class LLMOrchestrator:
    """Claude plans and writes; the same tools compute and the same verifier checks."""

    def __init__(self, metrics: MetricsLayer, events: pd.DataFrame, as_of: str = "2026-10-06",
                 model: str | None = None):
        import anthropic  # optional dependency
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("PARTNERPULSE_MODEL", "claude-sonnet-5-5")
        self.metrics, self.events, self.as_of = metrics, events, as_of

    def ask(self, question: str, partner: str, max_turns: int = 8) -> Answer:
        tools = Toolbox(self.metrics, self.events, partner)
        messages = [{"role": "user", "content": f"Today is {self.as_of}. Question: {question}"}]
        trace: list[dict] = []
        for _ in range(max_turns):
            resp = self.client.messages.create(model=self.model, max_tokens=1000, system=SYSTEM_PROMPT,
                                               tools=TOOL_SCHEMAS, messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                facts = [f for t in trace for f in t.get("facts", [])]
                facts += re.findall(r"\d[\d.]*", json.dumps(trace, default=str))
                has_rec = "suggest" in text.lower()
                a = Answer(text, trace=trace)
                a.verification = verify(text, facts, partner, self.metrics.partner_ids(), has_rec)
                return a
            results = []
            for c in calls:
                try:
                    out = tools.call(c.name, dict(c.input))
                except (UnknownMetric, KeyError, ValueError) as e:
                    out = {"error": str(e), "facts": []}
                trace.append(out)
                results.append({"type": "tool_result", "tool_use_id": c.id,
                                "content": json.dumps(out, default=str)})
            messages.append({"role": "user", "content": results})
        return Answer("I couldn't complete the analysis within the step limit.", refused=True, trace=trace)
