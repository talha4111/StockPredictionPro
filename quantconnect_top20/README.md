# QuantConnect Top20 Independent Validation

This cloud backtest preserves the local Factor v3.1 strategy definition while
replacing the current static stock list with historical SPY ETF constituents
and point-in-time Morningstar fundamentals.

## Strategy contract

- Monthly signal at 09:20 ET and Market-On-Open execution in the official
  opening auction.
- Completed daily bars only: 12-1 and 6-1 momentum, distance from the 52-week
  high, 63-day volatility/downside volatility, and one-year maximum drawdown.
- Point-in-time quality and value data from QuantConnect Morningstar.
- Factor weights: quality 35%, value 20%, momentum 30%, risk 15%.
- Top 20, 5% maximum per stock, 25% maximum per sector.
- 0.5% cash buffer for fees and overnight opening gaps.
- Minimum 75% feature coverage and $5 million 20-day average dollar volume.
- Approximate 25 bps round-trip all-in cost as 12.5 bps per traded leg.
- No live orders. This project is validation-only.

## Cloud files

Create a Python project in QuantConnect Cloud and place these two files in it:

1. `main.py`
2. `factor_core.py`

Default backtest parameters:

| Parameter | Value |
| --- | ---: |
| `start_date` | `2021-07-01` |
| `end_date` | `2026-06-30` |
| `initial_cash` | `1000000` |
| `top_n` | `20` |
| `min_positions` | `5` |
| `max_position_weight` | `0.05` |
| `sector_cap` | `0.25` |
| `min_avg_dollar_volume` | `5000000` |
| `round_trip_cost_bps` | `25` |
| `cash_buffer` | `0.005` |
| `quality_weight` | `0.35` |
| `value_weight` | `0.20` |
| `momentum_weight` | `0.30` |
| `risk_weight` | `0.15` |

Factor weights are normalized by the research core. A zero weight is allowed
for controlled ablation runs, but negative weights, unknown factors, and an
all-zero mix fail closed. These parameters are for validation only; changing a
cloud run does not change the live stock scanner.

## Decision rule

Do not connect the strategy to a broker from this result. First compare total
return, annualized return, Sharpe ratio, maximum drawdown, turnover/order count,
and performance versus SPY. The model only advances if the independent result
remains positive after costs, beats SPY over the validation period, and does
not rely on one short interval or a handful of names.

SPY ETF holdings are a practical free historical universe, but they are not an
exact official S&P 500 membership file and can be reported with a short lag.
That limitation must remain attached to the result.

## Cloud validation result

The clean QuantConnect Cloud run completed on 2026-07-16. The requested end
date was 2026-06-30, but the cloud data available to the run ended on
2026-04-17.

| Metric | Top20 | SPY |
| --- | ---: | ---: |
| Total return | 50.886% | 77.045% |
| Annualized return | 8.950% | 12.649% |
| Maximum drawdown | 16.800% | 24.496% |
| Sharpe ratio | 0.234 | 0.644 (zero risk-free estimate) |

The strategy made money after the modeled costs and reduced drawdown, but it
lagged SPY by 26.159 percentage points and did not pass the production gate.
All 1,487 orders were filled as Market-On-Open orders; there were no rejected
orders or Market-On-Close conversion warnings. The last 90 calendar days were
slightly positive relative to SPY, but that interval is too short to establish
persistent alpha.

The machine-readable audit is stored in
`data/quantconnect_top20_validation.json`. Keep this model in research mode
until rolling walk-forward factor and market-regime tests improve both the
full-period benchmark comparison and risk-adjusted return.

## Factor ablation result

All four controlled leave-one-factor-out runs completed in QuantConnect Cloud:

| Variant | Return | CAGR | Max drawdown | Sharpe | Sortino | Fees | Orders |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 50.886% | 8.950% | 16.800% | 0.234 | 0.267 | $54,128.12 | 1,487 |
| No value | 49.960% | 8.810% | 18.100% | 0.221 | 0.249 | $60,602.98 | 1,517 |
| No quality | 36.250% | 6.642% | 17.300% | 0.092 | 0.110 | $64,066.42 | 1,593 |
| No momentum | 64.564% | 10.911% | 14.800% | 0.360 | 0.427 | $41,242.24 | 1,383 |
| No risk | 76.478% | 12.535% | 18.000% | 0.414 | 0.478 | $55,982.85 | 1,488 |

Quality and value remain active. Removing either factor weakened the strategy,
and removing quality caused the largest deterioration. The momentum sleeve is
the clearest candidate for a lower weight: its removal improved every recorded
full-period metric and reduced both costs and order count. Removing the risk
sleeve produced the highest return and Sharpe, but maximum drawdown increased
from 16.8% to 18.0%, so the defensive sleeve should be reduced and retested
rather than deleted.

These are same-period ablations, not independent proof of a better production
model. Selecting the best result directly would introduce multiple-testing and
period-selection bias. The next gate is a rolling walk-forward and market-regime
grid over lower momentum and lower risk weights while keeping quality and value
active.

All temporary cloud parameter overrides were removed. The QuantConnect project
is back on the default 35/20/30/15 factor mix, and it remains validation-only
with no live orders. The structured result is stored in
`data/quantconnect_factor_ablation.json`.

## Reduced-weight cloud validation

The local rolling grid was used only to shortlist candidates. Its stitched
out-of-sample selector returned 63.735% versus 63.971% for the fixed baseline
over the same months, while maximum drawdown improved from 6.212% to 4.958%.
Because the local test uses a static current-stock pool, it remains a
survivorship-biased diagnostic rather than production evidence.

The reduced-weight shortlist was then tested in QuantConnect Cloud with
historical SPY ETF constituents, point-in-time Morningstar fundamentals, and
the same cost and portfolio constraints:

| Raw Q/V/M/R | Return | CAGR | Max drawdown | Sharpe | Sortino | Fees | Orders |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 35/20/30/15 | 50.886% | 8.950% | 16.800% | 0.234 | 0.267 | $54,128.12 | 1,487 |
| 35/20/0/15 | 64.564% | 10.911% | 14.800% | 0.360 | 0.427 | $41,242.24 | 1,383 |
| 35/20/10/15 | 56.086% | 9.693% | 15.000% | 0.282 | 0.327 | $41,741.76 | 1,392 |
| 35/20/20/15 | 45.253% | 8.065% | 17.200% | 0.179 | 0.205 | $46,962.77 | 1,443 |
| 35/20/20/10 | 56.481% | 9.750% | 17.000% | 0.279 | 0.322 | $46,126.74 | 1,430 |

The zero-momentum variant is the current research leader: it improved return,
drawdown, risk-adjusted results, fees, and order count versus the baseline. It
still lagged SPY by 12.481 percentage points and was selected on the same full
sample, so it remains a fixed challenger rather than a production model. The
35/20/10/15 mix is retained as a second, more balanced challenger.

All temporary QuantConnect parameters were removed after the comparison. The
cloud project was restored to the default 35/20/30/15 mix, saved, and built.
The machine-readable audit is in `data/stock_factor_weight_grid.json`.

## Pre-registered regime validation

The baseline, zero-momentum, and 10% momentum variants were frozen before the
cloud runs and tested over three non-overlapping market windows. All other
portfolio, cost, execution, universe, and fundamental-data settings remained
unchanged.

| Regime | Variant Q/V/M/R | Return | Max drawdown | Sharpe | Fees | Orders |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2021-07 to 2022-12 stress | 35/20/30/15 | 6.302% | 15.900% | 0.174 | $14,927.62 | 461 |
| 2021-07 to 2022-12 stress | 35/20/0/15 | 6.588% | 14.800% | 0.186 | $12,770.87 | 437 |
| 2021-07 to 2022-12 stress | 35/20/10/15 | 1.225% | 15.000% | -0.010 | $12,773.85 | 443 |
| 2023-01 to 2024-12 recovery | 35/20/30/15 | 30.479% | 11.000% | 0.503 | $21,031.08 | 610 |
| 2023-01 to 2024-12 recovery | 35/20/0/15 | 31.013% | 10.700% | 0.550 | $13,842.33 | 552 |
| 2023-01 to 2024-12 recovery | 35/20/10/15 | 36.413% | 10.600% | 0.721 | $15,533.48 | 559 |
| 2025-01 to 2026-04 recent | 35/20/30/15 | 8.386% | 11.500% | -0.056 | $12,718.08 | 399 |
| 2025-01 to 2026-04 recent | 35/20/0/15 | 16.543% | 11.100% | 0.325 | $10,397.20 | 376 |
| 2025-01 to 2026-04 recent | 35/20/10/15 | 12.484% | 10.800% | 0.144 | $10,173.82 | 375 |

The zero-momentum candidate beat the baseline on return and Sharpe in all
three regimes while also reducing drawdown in every regime. The 10% momentum
candidate passed the pre-registered rule in two regimes, but failed badly in
the stress window. Therefore 35/20/0/15 remains the research leader and
35/20/10/15 remains only a secondary diagnostic challenger.

This is still not a production authorization. The candidates were selected
using the enclosing full period, so the next evidence must come from genuinely
new paper observations without further weight tuning. The full run names,
metrics, and decision audit are stored in
`data/stock_factor_regime_manifest.json`. The cloud project was restored to
the default 35/20/30/15 source and built after all nine runs.
## Genuinely new monthly paper comparison

The local stock scanner now freezes one paired Top20 cohort on the first
successful scan of each market month. The production baseline remains
35/20/30/15; the 35/20/0/15 research leader is recorded only as a shadow
challenger. Both cohorts use the same point-in-time input snapshot, 5% maximum
position weight, and 25% maximum sector weight. Any unused allocation remains
cash and is included in the portfolio-return calculation.

This layer sends no extra Telegram message and places no order. A model cannot
be promoted automatically. Review starts only after at least three paired,
20-business-day-mature cohorts with at least ten valid names per side. The
challenger must win on SPY-relative return in at least two thirds of paired
months, improve average absolute and excess return, and avoid material MAE
deterioration.

Check the audit without changing the scanner with:

```powershell
.\venv\Scripts\python.exe stock_shadow_status.py --update-manifest
```

The frozen contract and latest status live in
`data/stock_shadow_paper_manifest.json`.
