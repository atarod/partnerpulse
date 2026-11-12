# Trust and privacy

[← Back to README](../README.md)

PartnerPulse separates two problems: **trust** (answers are correct and honest about uncertainty) and **privacy** (no partner sees another partner's data, and no customer's personal data reaches the model).

## Trust

**Numbers come from the metrics layer, never from the LLM.** The agent translates the question into tool calls and explains results; governed code computes every figure.

**Every insight shows its sources:** metric definition, period, segment and peer group.

**Confidence is explicit.** The agent flags thin data, separates real change from noise using statistics, and distinguishes correlation from tested cause. "I don't have enough data to answer that" is a valid answer.

**Evaluation before and after release.**

| Check | Target |
|---|---|
| Numeric accuracy against metrics layer | 100% |
| Correct tool and filter selection | Tracked per release |
| Faithfulness of explanation to tool output | Tracked per release |
| Correct refusals on unanswerable questions | Tracked per release |
| Partner usefulness rating | Tracked in production |

The evaluation set is built from real partner questions with known answers and re-run on every model or prompt change. Flagged answers in production are reviewed and added to the set.

**Autonomy is earned.** Recommendations go through human review until accuracy is proven, then review is loosened step by step.

## Privacy

**Isolation in the data layer.** Each partner's agent session can only query that partner's data, enforced by permissions in the metrics layer. Prompt instructions are never relied on for isolation.

**Safe benchmarks.** Peer comparisons come only from pre-computed aggregates that satisfy:

- **minimum peer count:** a benchmark needs enough partners behind it (for example, at least five);
- **dominance rule:** no single partner may make up too large a share of a peer group;
- **fixed peer groups and rounding:** prevent "differencing", where slightly different repeated queries are subtracted to reveal one partner's figure.

**No personal data in the model.** End-customer names, contact or payment details never enter the LLM context; insights work on aggregated, de-identified data.

**Contracts and vendors.** Partners consent to anonymised benchmarking; any external model provider must not retain or train on partner data. All queries are logged for audit.
