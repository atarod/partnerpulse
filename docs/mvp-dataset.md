# MVP: synthetic dataset and story check

[← Back to README](../README.md)

The MVP focuses on one problem: **helping account managers find out quickly why a partner's attach rate changed, and what to do about it.** This page describes the synthetic data behind it and how the detector is checked against known answers.

Everything is fictional: invented partners, account managers and numbers.

## Tables (`data/mvp/`, or `partnerpulse mvp-data`)

| File | One row per | Key fields |
|---|---|---|
| `partners.csv` | Partner (12) | vertical, size, account manager, base attach rate |
| `daily_sales.csv` | Day × partner × device × market | placement, price point, eligible bookings, policies sold, premium |
| `integration_changes.csv` | Logged partner change | date, device, change, change type |
| `claims.csv` | Claim | sale date, claim date, market, reason, amount |
| `am_actions.csv` | Account manager decision (starts empty) | decision, useful, acted on |
| `ground_truth.json` | Planted story | expected alert type, direction, cause |

Sales cover **Jun–Oct 2026** plus the **same months of 2025**, so detection can compare year on year. About 5.7 million eligible bookings in total. Claims arrive 2 to 8+ weeks after the sale and only claims reported by **Oct 31, 2026** are visible, which recreates the claims-lag problem.

## How the numbers behave

- Base attach rates of 3% to 9%, varying by partner, device and market
- Busier Mondays and Fridays, quieter Sundays
- A summer peak in travel bookings and attach rate
- Random noise from realistic sampling, larger for small partners

## Planted stories and the correct response

| # | Partner | What's hidden | Correct response |
|---|---|---|---|
| 1 | SkyBridge Air | Sep 9: app offer moved after payment | Step down, app only, cause: placement; suggest a test |
| 2 | Nordlys Travel | Aug 20: price $15 → $22 | Step down, cause: price; revenue per booking still rose |
| 3 | Cartwell | Sep 15: checkout redesign | Step **up**, cause: checkout |
| 4 | Atlas Journeys, Meridian Fly, Costa Verde Trips | Sep 22: one market (AE) dips | **One market-level alert**, not three partner alerts |
| 5 | Sunwise Holidays | Summer peak, then normal decline | **No alert** (seasonal) |
| 6 | PocketPay | Small volume, noisy days | **No alert** (noise) |
| 7 | Harbor Rail | Slow decline, no single break | Drift down |
| 8 | Bramble Market | Traffic shifts to the app; devices unchanged | **Mix effect**, not a conversion problem |
| 9 | Costa Verde Trips, Spain | Delay claims rising from August | Claims alert, adjusted for claims still to come |
| – | Kettle & Co, Ledgerly | Steady | No alert |

## How detection works (`src/partnerpulse/mvp/detect.py`)

- **Year-on-year baseline:** each partner's daily attach rate is divided by the same weekday last year, removing seasonality.
- **Step vs. drift:** the strongest break is found with a two-sample test; a straight-line fit is compared, and whichever explains the data better wins. Thresholds: |t| ≥ 6 and at least a 10% change for steps; |t| ≥ 8 and 15% over the period for drift.
- **Rate vs. mix:** the change is split into "segments converted differently" and "traffic shifted between segments".
- **Cause:** integration changes within two days of the break are attached as the likely cause, with timing treated as evidence, not proof.
- **Market level:** each market is compared with the same partners' other markets, so a partner-wide change cannot fake a market dip. Partner alerts explained by a market move are folded into the market alert.
- **Claims lag:** expected claims are scaled by how complete each sales day's claims should be by now (from fully developed June cohorts), chain-ladder style, and compared with a pooled baseline.

## Results

```
python evals/run_mvp_stories.py --seeds 5
```

On the published dataset and four other random seeds, every story is found with the right type, direction and cause, and there are no false alarms: **precision 100%, recall 100%**.

## Honest limits

This shows the design works when the signal is clear. The thresholds were tuned on this synthetic data, real partner data is messier, and some stories are deliberately clean. On real data the next steps would be: back-testing on history, measuring precision and recall on labelled past incidents, and tuning thresholds per partner size with the data science team.
