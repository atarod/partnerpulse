"""Verifier and policy check: runs on every answer before a partner sees it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Numbers the product itself may introduce (test design), not data claims.
POLICY_CONSTANTS = {"50", "2", "14"}


def _norm(token: str) -> str:
    return token.replace(",", "").rstrip(".")


def _variants(token: str) -> set[str]:
    """A number plus its common roundings, so '6.12' allows '6.1' and '6'."""
    t = _norm(token)
    out = {t}
    try:
        v = float(t)
    except ValueError:
        return out
    out |= {f"{v:.1f}", f"{v:.0f}", f"{round(v):d}"}
    if "." in t:
        out.add(t.rstrip("0").rstrip("."))
    return out


def allowed_numbers(facts: list[str]) -> set[str]:
    allowed = set(POLICY_CONSTANTS)
    for f in facts:
        for tok in NUMBER_RE.findall(str(f)):
            allowed |= _variants(tok)
    return allowed


@dataclass
class Verification:
    passed: bool
    unverified_numbers: list[str] = field(default_factory=list)
    leaked_partners: list[str] = field(default_factory=list)
    requires_review: bool = False


def verify(text: str, facts: list[str], session_partner: str, all_partners: list[str],
           has_recommendation: bool) -> Verification:
    allowed = allowed_numbers(facts)
    unverified = [tok for tok in NUMBER_RE.findall(text) if _norm(tok) not in allowed]
    leaked = [p for p in all_partners if p != session_partner and p in text]
    return Verification(passed=not unverified and not leaked, unverified_numbers=unverified,
                        leaked_partners=leaked, requires_review=has_recommendation)
