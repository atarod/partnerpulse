# Metrics and KPIs

[← Back to README](../README.md)

## North star: insights acted on

The share of delivered insights that lead a partner to take a concrete action within a set window, such as changing price, placement or bundle, launching a test, or fixing an operational issue.

It sits between usage and business results: usage without action is noise, and business results take months to show.

## KPI layers

| Layer | Question | Metrics |
|---|---|---|
| Adoption | Are partners using it? | Active partners per week; questions and alerts opened per partner; unprompted repeat usage |
| Quality and trust | Do partners believe it? | Numeric accuracy (target 100%); answer coverage; usefulness rating; alert precision |
| Action | Does behaviour change? | **Insights acted on**; time to detect; time to act; tests launched |
| Partner outcomes | Do partners win? | Attach-rate lift from actions; partner protection revenue; checkout completion |
| Platform outcomes | Does the platform win? | Premium growth; partner retention and renewal; product or market expansion; account-team time saved |

## Guardrails

These must not get worse while the KPIs above improve:

- zero cross-partner data leaks;
- loss ratio stays within agreed bounds, keeping insurers healthy;
- pricing suggestions stay within approved limits;
- cost and latency per answer stay within budget.

## The hard part: defining "acted on"

Possible signals, each with gaps:

| Signal | Strength | Gap |
|---|---|---|
| Integration or configuration change seen by the platform | Objective | Not every action shows up in the integration |
| Test launched from an insight | Clear link | Only covers testable actions |
| Partner marks "acting on this" | Direct | Self-reported, often skipped |
| Account manager logs the action | Rich context | Manual and inconsistent |

Attribution is the second challenge: if attach rate rises after a change, was it the insight or something else? Controlled tests give the cleanest answer, so the product nudges partners toward testing suggested changes.
