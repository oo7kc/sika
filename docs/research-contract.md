# Sika Research Contract v0.1

Status: **Draft for review — not approved for implementation or trading**

Created: 2026-10-04
Primary purpose: define a falsifiable, reproducible first experiment for discretionary XAUUSD trade calls.

## 1. Objective

Sika will research whether information available at the close of an Exness XAUUSD M15 bar, combined with H1 market context, can identify selective long or short trade plans with positive expected value after realistic costs.

The system will not predict an unconstrained daily direction. For each eligible timestamp, it will construct explicit long and short candidates containing an entry, stop-loss, take-profit, and expiry, then estimate the probability of each possible trade outcome.

The eventual product may publish approved calls through Telegram, but execution will remain manual and discretionary. This contract covers offline research and the evidence required before any Telegram paper signals.

## 2. Confirmed product decisions

- Instrument: regular Exness `XAUUSD` spot CFD, exposed as `XAUUSDm` on the confirmed Standard demo account; not `XAUUSD247`.
- Trading platform and canonical execution feed: Exness MetaTrader 5.
- Account profile represented in v0: Exness Standard demo account.
- Signal timeframe: M15.
- Context timeframe: H1.
- Barrier and execution resolution: Exness ticks where available, otherwise M1 with conservative ordering.
- Primary trading period: New York session, active from 08:00 through 16:00 New York time; new candidates stop at 14:00.
- Order execution: manual and discretionary; no broker order placement by Sika.
- Delivery target after research approval: private Telegram chat.
- Default action: no trade.

Exness documents `XAUUSD` as a spot CFD with a 100-troy-ounce contract size and 0.01 pip size. `XAUUSD247` uses a Special Price Offset and is intentionally excluded from the first experiment. See [Exness commodity specifications](https://get.exness.help/hc/en-us/articles/17854173039388-Commodities).

## 3. Time and session contract

### 3.1 Canonical time

- Persist every timestamp as timezone-aware UTC.
- Interpret the trading session with the IANA timezone `America/New_York` so daylight-saving transitions are automatic.
- Never infer session membership from the machine's local timezone.
- Treat the Exness MT5 server as UTC+0, consistent with [Exness MetaTrader timezone documentation](https://get.exness.help/hc/en-us/articles/360014390760-What-is-the-default-timezone-set-for-MetaTrader).

### 3.2 New York operating window

- The system is active from 08:00 through 16:00 New York time.
- It evaluates every completed M15 bar during that operating window so regime, setup, and open-trade state remain current.
- New trade candidates may be created only from M15 bars closing between 08:15 and 14:00 New York time, inclusive.
- No new trade may be activated after 14:00 New York time.
- From 14:00 through 16:00, the system continues monitoring and managing existing trades but does not create new candidates.
- Every activated trade retains its maximum eight-M15-bar holding period and must exit no later than 16:00 New York time.
- Weekends, known Exness closures, quote-only periods, maintenance periods, and materially incomplete bars are ineligible.
- Positions are not carried into the Exness rollover period, where liquidity can fall and XAUUSD may close. See [Exness instrument trading hours](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours).

### 3.3 News handling

Offline research will retain a timestamped feature indicating proximity to scheduled high-impact USD events and compare results with and without a blackout.

For any later paper/live signal policy:

- Reject a new entry if a scheduled high-impact USD event occurred inside the signal bar or is scheduled within 30 minutes after the proposed entry.
- Resume eligibility only after a complete M15 bar has closed following the event.
- The historical and live economic-calendar provider must be named and versioned before this filter becomes an approval gate.

## 4. Market-data contract

### 4.1 Canonical sources

- Obtain H1 and M15 bars from the Exness MT5 account intended to represent execution.
- Obtain M1 bars and bid/ask ticks from the same Exness server for barrier ordering and execution-cost reconstruction.
- Do not mix Tiingo bars with Exness execution outcomes in the primary experiment.
- Retain the provider/server/account-type identifiers with every extraction.

The official MT5 Python integration returns bar time, OHLC, tick volume, spread, and real volume through `copy_rates_range`; it returns bid and ask ticks through `copy_ticks_range`. Both APIs use UTC timestamps. See [MT5 bar API](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py) and [MT5 tick API](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py).

### 4.2 Required history

- Target at least five years of M15 and H1 history where Exness makes it available.
- Accept no less than three years for the first feasibility report.
- The v0 backfill window is fixed to the 60 complete UTC calendar months from
  `2021-10-01 00:00:00` through, but excluding, `2026-10-01 00:00:00`.
- Export M1, M15, and H1 as matching monthly bundles. A month is complete only
  when its three bar files and final completion manifest are present and valid.
- Record the exact available interval rather than silently substituting another provider.
- Start retaining live ticks prospectively because terminal tick-history depth may be more limited than bar history.
- Increase MT5's chart-history limit before extraction and record the setting used.

### 4.3 Required fields

Bars must include:

- symbol and venue/server;
- UTC open and close timestamps;
- timeframe;
- open, high, low, and close;
- tick volume and real volume when supplied;
- spread in points;
- completeness/finality status; and
- extraction timestamp and source version.

Ticks must include:

- UTC timestamp at the highest available precision;
- bid;
- ask;
- last and volume when supplied; and
- MT5 tick flags.

### 4.4 Validation and failure policy

Reject or quarantine data containing:

- naive or non-monotonic timestamps;
- unhandled duplicate timestamps;
- impossible OHLC relationships;
- negative or crossed spreads;
- stale quotes;
- unexplained session gaps;
- incomplete signal bars;
- symbol/server mismatches; or
- revisions that cannot be reconciled with the stored source snapshot.

Missing data must fail closed. The pipeline must never replace a requested timestamp with the most recent available bar or price.

## 5. Information boundary

At a signal timestamp `t`, features may use only:

- M15 bars whose close time is less than or equal to `t`;
- H1 bars fully closed by `t`;
- ticks received at or before `t` for state/spread features; and
- calendar events published before `t`.

No feature may use the high, low, close, volume, revised value, or event outcome of a bar that was incomplete at `t`.

Training, backtesting, shadow inference, and live inference must call the same versioned causal feature builder. A train/serve-parity test is mandatory.

## 6. Feature hypotheses

Features are grouped into locked experiments so the value of candlestick encoding can be measured rather than assumed.

### 6.1 M15 continuous candle geometry

For each completed M15 candle, calculate at minimum:

- direction;
- absolute and signed return;
- `abs(close - open) / max(high - low, epsilon)`;
- upper wick divided by range;
- lower wick divided by range;
- range divided by M15 ATR(14) known at `t`;
- gap from the preceding close;
- close location within the candle range;
- tick-volume z-score fitted from past data only; and
- spread divided by ATR and proposed stop distance.

### 6.2 Alphabetical candle state

Retain an interpretable v1 state derived from the reviewed MQL5 article series:

- `A/a`: body-dominant bullish/bearish candle;
- `G/g`: spinning-top-like bullish/bearish candle;
- `H/h`: lower-wick-dominant bullish/bearish candle;
- `E/e`: upper-wick-dominant bullish/bearish candle;
- `D`: doji; and
- `N/n`: directional fallback for candles outside the named shapes.

Required adaptations:

- Define doji with a tolerance, not exact `close == open`.
- Initial doji tolerance: body no larger than the greater of two instrument ticks or 5% of total candle range.
- Preserve continuous geometry beside the categorical state.
- Version every threshold and fit any data-derived threshold on training history only.
- Use observed state sequences of length one, two, and three only.
- Treat state/sequence frequency as support and coverage, not as confidence or edge.

Article references:

- [Part 1 — deterministic encoding](https://www.mql5.com/en/articles/22469)
- [Part 2 — ordered sequences](https://www.mql5.com/en/articles/22709)
- [Part 3 — single-state frequency](https://www.mql5.com/en/articles/23009)
- [Part 4 — two-state frequency](https://www.mql5.com/en/articles/23263)
- [Part 5 — expanded taxonomy](https://www.mql5.com/en/articles/23684)

### 6.3 H1 market context

The initial locked H1 context set will contain:

- H1 log returns over 1, 3, and 6 completed bars;
- H1 ATR(14) divided by price;
- H1 close minus EMA(20), normalized by ATR(14);
- H1 ADX(14);
- distance to the trailing 20-bar high and low, normalized by ATR; and
- the slope of EMA(20) over the last three completed H1 bars.

These are context variables, not independent reasons to issue a call.

### 6.4 Time and execution context

Include:

- New York local hour and minute bucket;
- weekday;
- minutes to/from a scheduled high-impact USD event where available;
- current spread and its percentile for the same session bucket;
- signal delivery-latency assumption; and
- whether the session is subject to a holiday or abnormal trading schedule.

## 7. Candidate trade construction

At each eligible completed M15 bar, construct one hypothetical long candidate and one hypothetical short candidate before observing future prices.

### 7.1 Reference entry

- Apply a fixed 60-second delivery/execution latency after the M15 close.
- Long reference entry is the first valid ask at or after `t + 60 seconds`.
- Short reference entry is the first valid bid at or after `t + 60 seconds`.
- If no valid tick is available within the next four minutes, reject the candidate.
- The eventual Telegram entry zone remains valid until the next M15 close.
- Cancel a discretionary entry if the current executable price differs from the reference by more than `0.10R` in either direction or if the structural invalidation has traded.
- The strategy ledger always uses the deterministic reference entry; discretionary fills belong in a separate ledger.

### 7.2 Structural stop

For a long candidate:

- structural anchor is the minimum low of the last four completed M15 bars;
- stop is below that anchor by a buffer.

For a short candidate:

- structural anchor is the maximum high of the last four completed M15 bars;
- stop is above that anchor by a buffer.

The buffer is the greater of:

- current executable spread; or
- `0.10 × M15 ATR(14)`.

Reject a candidate if entry-to-stop distance is:

- less than `0.75 × M15 ATR(14)`; or
- greater than `1.50 × M15 ATR(14)`.

These bounds are hypotheses to be tested only on development data. They may be changed before contract approval, but not after the final holdout is opened.

### 7.3 Take-profit

- Use one target in v0.
- Gross target distance is exactly `2R`, where `1R` is entry-to-stop distance.
- Do not use partial take-profits, trailing stops, or discretionary target movement in the primary experiment.

### 7.4 Expiry

- Maximum holding period is eight M15 bars after entry, equal to two hours.
- Exit earlier at 16:00 New York time.
- A pending, unfilled discretionary entry expires at the next M15 close.
- At trade expiry, close the research position at the first executable bid for a long or ask for a short.

## 8. Outcome labeling

Persist both the categorical outcome and realized return in R.

Possible outcomes:

- `tp`: the 2R target is executable before the stop and expiry;
- `sl`: the stop is executable before the target and expiry;
- `timeout`: neither barrier is reached and the position exits at the expiry quote;
- `unfilled`: the entry rule is not satisfied;
- `ambiguous`: data cannot establish ordering; and
- `invalid`: a required data or market-integrity rule failed.

Barrier evaluation must use executable sides:

- Long entry at ask; long TP/SL/expiry exit at bid.
- Short entry at bid; short TP/SL/expiry exit at ask.

If TP and SL occur in the same M1 bar:

1. Use stored ticks to determine ordering.
2. If ticks are unavailable or incomplete, assign the stop-loss outcome for evaluation.
3. Report the rate of conservatively resolved collisions.

Timeouts retain their actual realized R at the expiry quote. They must not automatically be relabeled as full losses.

## 9. Cost model

Backtests must include:

- observed bid/ask spread;
- Exness commission for the modeled account type;
- empirical slippage or a conservative proxy fitted without holdout data;
- the 60-second execution delay;
- missed/unfilled entries; and
- expiry liquidation costs.

Exness documents dynamic spreads. It currently lists XAUUSD commission per lot per side as USD 3.50 for Raw Spread accounts and USD 5.50 for Zero accounts, while Standard and Pro accounts are commission-free. See [Exness spread documentation](https://get.exness.help/hc/en-us/articles/360014690880-About-spread) and [commission documentation](https://get.exness.help/hc/en-us/articles/360012007919-Are-trading-accounts-charged-a-commission-fee).

The v0 execution account is confirmed as Exness Standard demo. The primary cost
model therefore uses observed Standard-account spread, zero explicit commission,
and the locked slippage and latency assumptions. A Raw Spread scenario may be
reported separately as a robustness check, but it must not be blended with the
primary result. Changing the execution account profile requires a new research
contract version and a new evidence run.

Reject a candidate when either condition is true:

- current spread is greater than 5% of proposed stop distance; or
- current spread is above the development-data 95th percentile for the same New York 15-minute bucket.

## 10. Research experiments

Run experiments in this order:

1. `E0 — null baselines`: always-long, always-short, random candidates at equal frequency, trend-only, and volatility-only.
2. `E1 — categorical patterns`: alphabetical states and observed sequences of length one through three, with no technical context.
3. `E2 — continuous geometry`: continuous M15 candle measurements without categorical names.
4. `E3 — context`: locked H1 and execution context without candle-state features.
5. `E4 — combined`: best locked pattern representation plus locked context.

Pattern features survive only if `E4` adds stable out-of-sample value over `E3`.

Initial model families are deliberately limited:

- regularized logistic regression as the interpretable probability baseline; and
- one tree-based boosting model as the nonlinear challenger.

No MLP or deep sequence model will be introduced unless the simpler models establish a repeatable edge and a later plan justifies the additional complexity.

## 11. Chronological evaluation

### 11.1 Splits

- Sort all eligible events chronologically.
- Reserve the latest 20% of eligible dates, with a minimum duration of six months, as the untouched final holdout.
- Run expanding walk-forward folds on the earlier 80%.
- Within every fold, reserve a later chronological calibration block that is disjoint from model fitting.
- Purge at least the maximum entry-validity plus holding horizon around split boundaries so outcome windows do not overlap training and evaluation.
- Never use shuffled cross-validation.

### 11.2 Multiple-testing control

- Register every experiment and parameter set before its evaluation result is inspected.
- Preserve failed experiments.
- Limit pattern length to three.
- Select thresholds and model parameters using development folds only.
- Open the final holdout once for the contract version.
- Any material change after opening the holdout creates a new contract version and a new future holdout.

### 11.3 Required reports

Report at minimum:

- candidate, rejected, unfilled, and published counts;
- long/short balance;
- TP, SL, and timeout rates;
- realized expectancy in R after costs;
- confidence intervals for expectancy and win probability;
- profit factor;
- maximum drawdown in R;
- turnover and average holding time;
- results by fold, month, session bucket, side, volatility regime, and news proximity;
- Brier score and log loss;
- probability reliability/calibration curves;
- expected calibration error;
- collision/ambiguous-data rates; and
- sensitivity to Standard versus Raw Spread costs.

## 12. Confidence and selection policy

The primary displayed confidence is:

`P(TP is reached before SL and expiry | candidate information available at signal time)`

The research model must also account for stop and timeout outcomes. Expected value is:

`EV_R = 2 × P(TP) - 1 × P(SL) + P(timeout) × E[R_at_expiry | timeout] - costs_R`

A future Telegram call is eligible only when:

- the model is calibrated on chronological out-of-sample predictions;
- estimated confidence exceeds cost-adjusted break-even by at least eight percentage points;
- expected value is at least `+0.20R` after modeled costs;
- the lower 90% uncertainty/calibration-adjusted bound remains above break-even;
- the applicable out-of-sample probability region has adequate support;
- data, spread, news, entry, and exposure gates pass; and
- only one of the long/short candidates has the highest approved conservative expected value.

If both candidates fail, conflict, or have indistinguishable conservative value, publish no trade.

The exact calibration method will be selected using development data only. With limited calibration samples, sigmoid calibration is the default challenger to uncalibrated probabilities; isotonic calibration requires enough observations to avoid fitting noise.

## 13. Risk policy for a future discretionary pilot

- Suggested maximum account risk per manually executed trade: 0.25%.
- Confidence filters entry eligibility; it does not increase position size.
- Maximum one active XAUUSD signal.
- Maximum two published calls per New York day.
- Stop publishing new calls after two strategy stop-loss outcomes in one day.
- No martingale, averaging down, or moving the stop farther away.
- Do not chase an expired or out-of-zone entry.
- User discretion and actual fills are recorded separately from strategy performance.

These limits are product safety defaults for review, not personalized financial advice.

## 14. Promotion gates

### Gate A — offline feasibility

- Data contract and causal feature tests pass.
- Train/serve-parity tests pass.
- Combined research results beat the locked baselines on future folds.
- Cost-adjusted expectancy is positive in a conservative account-cost scenario.

### Gate B — final holdout

- At least 150 completed out-of-sample eligible signals exist across walk-forward evaluation and holdout, including at least 30 in the final holdout.
- Aggregate lower 90% confidence bound for after-cost expectancy is above zero.
- At least 70% of chronological evaluation folds have positive after-cost expectancy.
- No fold has expectancy below `-0.10R`.
- Maximum drawdown does not exceed `10R`.
- Probability calibration improves on the unconditional baseline and expected calibration error is no greater than 0.05.

These numeric gates are initial conservative proposals and must be reviewed before the holdout is opened.

### Gate C — shadow replay

- Run the live Exness feed and generate internal signals without Telegram delivery.
- Replaying the same stored data produces the same candidates, features, probabilities, and trade plans.
- No unexplained timestamp, spread, or session discrepancies remain.

### Gate D — private Telegram paper trading

- Publish signals to an allowlisted private chat with no capital at risk.
- Reconcile every signal from the canonical Exness feed.
- Complete at least three calendar months and 50 closed paper signals, whichever takes longer.
- Lock the strategy during the evaluation window; material changes restart the evidence period.

### Gate E — discretionary live pilot

- Requires a separate explicit review and approval.
- Manual execution only.
- Risk remains capped independently of confidence.
- Automatic broker execution remains out of scope.

## 15. Telegram call contract for the later paper phase

Each call must eventually include:

- unique signal ID and model/contract version;
- `XAUUSD`, Exness venue/server, and M15 signal timeframe;
- New York and UTC timestamps;
- long/short side and market-call semantics;
- reference bid/ask and allowed entry zone;
- do-not-chase boundary;
- stop-loss and one take-profit;
- gross R:R and estimated after-cost EV in R;
- calibrated TP-first confidence and evidence/support summary;
- maximum suggested risk percentage;
- entry expiry and final trade expiry;
- invalidation reason;
- concise H1 context and M15 setup explanation; and
- lifecycle state: pending, triggered, cancelled, expired, TP, SL, or timeout.

The strategy ledger uses the exact published reference entry and rules. A separate optional user-execution ledger records whether the user entered, actual price, size, exit, and notes. The two performance records must never be merged.

## 16. Approval checklist

- [x] Confirm Exness account type to be represented: Standard.
- [x] Confirm that regular `XAUUSD`, exposed as `XAUUSDm`, is available on the intended Standard demo account; exclude `XAUUSD247`.
- [x] Confirm full-session monitoring from 08:00–16:00 and new candidates from 08:15–14:00 New York time.
- [ ] Confirm 60-second reference-entry latency and one-M15-bar discretionary entry validity.
- [ ] Confirm four-bar M15 structural stop, 0.75–1.50 ATR bounds, and buffer rule.
- [ ] Confirm fixed 2R target and eight-M15-bar/16:00 expiry.
- [ ] Confirm the proposed confidence, EV, drawdown, and minimum-sample gates before the final holdout is opened.
- [ ] Name the historical/live high-impact USD calendar provider or defer the news gate from v0 research.
- [ ] Approve this contract before functional implementation begins.

## 17. Change control

- This document is the source of truth for contract version `v0.1`.
- Every feature, label, cost, split, calibration, and selection policy must record the contract version.
- Changes made before holdout evaluation increment the draft version and are documented.
- Changes made after final-holdout inspection create a new research cycle with a new untouched future holdout.
- No result may be presented without the data interval, contract version, code revision, artifact manifest, and cost scenario that produced it.
