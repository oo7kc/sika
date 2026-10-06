# Plan

Transform Sika from a daily direction classifier into a research-validated trade-call system that can publish actionable, venue-specific signals to Telegram for discretionary execution. The work will proceed through explicit research, calibration, risk, paper-trading, and operational gates; no live signal will be promoted merely because a model or backtest looks promising.

## Scope
- In:
  - Produce timestamped long, short, or no-trade decisions for one initially approved instrument, venue, and timeframe.
  - Define each call with an executable entry convention, stop-loss, take-profit, expiry, planned risk/reward, calibrated confidence, and fixed risk guidance.
  - Use fully closed candles, normalized candle geometry, the reviewed alphabetical candle taxonomy, short observed sequences, and market context as candidate features.
  - Estimate the probability that the stated target trades before the stated stop within a fixed horizon, rather than predicting an unconstrained daily direction.
  - Evaluate baselines, pattern-only, context-only, and combined models with chronological out-of-sample testing and realistic execution costs.
  - Deliver approved signals and lifecycle updates through a private Telegram bot while leaving order execution to the user.
  - Maintain separate ledgers for the strategy's exact hypothetical signals and the user's discretionary executions.
- Out:
  - Automatic broker/exchange order placement, broker credentials, copy trading, or autonomous position management.
  - Confidence-based leverage or increasing position size because a model reports a higher probability.
  - Exhaustive mining of long candle permutations, unconstrained hyperparameter searches, or selecting strategies on the final holdout.
  - Claims of profitability, public signal distribution, or production promotion before the research and paper-trading gates pass.
  - Multi-asset portfolio optimization, multiple take-profit ladders, trailing stops, and complex order management in the first release.

## Action items
[ ] **1. Approve and freeze the initial research contract before implementation.**
  - Record the chosen instrument, execution venue, price feed, timeframe, timezone, trading sessions, and bar-closing convention in `docs/research-contract.md`.
  - Define when a setup is observed, when an entry is considered executable, whether the first experiment uses market/next-quote, limit, or stop entries, and how long an untriggered entry remains valid.
  - Define one initial stop method, one target method or reward multiple, one maximum holding horizon, and one conservative rule for bars in which TP and SL both appear to trade.
  - Lock spread, commission, slippage, missed-entry, stale-price, and market-closure assumptions before examining results.
  - State the research hypotheses, permitted model families, allowed parameter ranges, primary metrics, minimum sample requirements, and promotion thresholds.
  - Require plan and research-contract approval before any model or Telegram implementation begins.

[ ] **2. Preserve the current project as a reproducible baseline and remove it from decision use.**
  - Capture the current Git revision, environment, data ranges, configuration, saved artifacts, reported metrics, and the previously measured train/serve-skew diagnostics in a versioned baseline report.
  - Mark the existing MLP artifacts and 80–99% accuracy claims as historical and unsuitable for trade calls; do not silently overwrite or reuse them.
  - Add deterministic fixtures that reproduce the current leakage: completed same-day OHLC features during training versus the synthetic open-only bar during inference.
  - Establish simple baseline results for majority direction, previous direction, random entries at matching frequency, trend-only, and volatility-only rules.
  - Commit the application lockfile and define one supported Python range so all later experiments can be reproduced.

[ ] **3. Build a causal, auditable market-data and feature specification.**
  - Introduce a venue-aware bar/quote contract containing symbol, venue, timeframe, UTC timestamp, bid, ask, OHLCV, spread, completeness status, and provider provenance.
  - Accept only data available at signal time; generate signals from fully closed bars and use executable bid/ask prices for entries and barrier evaluation.
  - Validate monotonic timestamps, duplicates, gaps, timezone/session boundaries, OHLC integrity, stale quotes, abnormal spreads, and provider revisions; fail closed instead of substituting another date or price.
  - Implement continuous candle features alongside interpretable states: body/range, upper-wick/range, lower-wick/range, direction, range/known ATR, volume state, gap, and distance to recent structure.
  - Adapt the article taxonomy rather than copy it literally: use a tick-/volatility-aware doji tolerance, retain `N/n` directional fallbacks, normalize magnitude, and version all thresholds.
  - Use only observed one-, two-, and three-state sequences initially; treat marginal and sequence frequency as coverage/support diagnostics, never as confidence or profitability.
  - Add context features selected in advance, such as trend, volatility regime, trading session, spread, gap, and location relative to rolling highs/lows; keep news/event filters as an explicitly evaluated optional layer.

[ ] **4. Replace daily-direction labels with executable trade-event outcomes.**
  - For every candidate event at closed bar `t`, persist the side, planned entry, SL, TP, gross R:R, costs in R, expiry, and every input known at the decision timestamp.
  - Label a win only when TP trades before SL within the locked horizon, a loss when SL trades first, and a timeout when neither barrier trades before expiry.
  - Resolve same-bar TP/SL collisions with lower-resolution or tick data where available; otherwise assign the conservative outcome defined in the research contract.
  - Distinguish setup detection from entry activation so unfilled limit/stop orders become cancelled or expired rather than hypothetical filled trades.
  - Make label generation deterministic and idempotent, and store the exact data/model/label-policy versions that produced each event.
  - Add tests for long and short symmetry, gaps through barriers, spread crossing, weekend/holiday bars, missing lower-timeframe data, late provider corrections, and timeouts.

[ ] **5. Run the research programme in a locked sequence.**
  - Evaluate `E0` null baselines: always-long, always-short, random-at-equal-frequency, trend-only, and volatility-only.
  - Evaluate `E1` alphabetical candle states and one- to three-state sequences without indicators.
  - Evaluate `E2` continuous candle geometry without categorical pattern names to test whether the hard taxonomy discards information.
  - Evaluate `E3` market context without candle-state features.
  - Evaluate `E4` the locked best pattern representation plus the locked context representation; retain patterns only if they add stable future lift over `E3`.
  - Use expanding walk-forward folds with a purge/gap covering overlapping trade horizons, train-only feature thresholds, a separate chronological calibration set, and one untouched final holdout.
  - Control data-snooping and multiple-hypothesis risk, record every attempted experiment including failures, and prohibit tuning on the final holdout.
  - Report trade count, coverage, win/loss/timeout rates, expectancy in R after costs, profit factor, maximum drawdown, turnover, calibration error, Brier/log loss, regime stability, and uncertainty intervals—not accuracy alone.

[ ] **6. Define confidence, trade selection, and risk policy.**
  - Define confidence as `P(TP before SL within the stated horizon | setup and context)` for the exact published entry, stop, and target.
  - Calibrate probabilities only on chronological observations not used to fit the underlying model, and verify reliability by probability bin, instrument, session, volatility regime, and time period.
  - Calculate `EV_R = p_win * reward_R - (1 - p_win) - costs_R` and the cost-adjusted break-even probability for every candidate.
  - Make no-trade the default; publish only when data freshness, spread, entry validity, minimum support, probability reliability, expected value, and portfolio-risk gates all pass.
  - Attach support count and uncertainty to the internal decision so a high probability based on a sparse pattern cannot masquerade as high confidence.
  - Keep the suggested account-risk percentage fixed and conservatively capped during research and paper trading; use confidence to filter trades, not to increase leverage.
  - Add exposure gates for duplicate signals, correlated instruments, maximum simultaneous risk, daily loss limits, and stale or materially moved entries.

[ ] **7. Refactor the codebase around research, domain, and delivery boundaries.**
  - Move from the generic `scripts/` layout toward an installable `src/sika/` package with separate modules for domain types, settings, data providers, features, labels, research/evaluation, models/calibration, signal construction, persistence, and delivery.
  - Keep candle encoding and indicators pure and deterministic; expose one shared causal feature builder to training, backtesting, paper trading, and live inference.
  - Define typed domain records for `MarketSnapshot`, `Setup`, `TradePlan`, `Prediction`, `Signal`, `SignalOutcome`, and optional `UserExecution` rather than passing unvalidated dictionaries.
  - Replace import-time environment configuration with validated settings, project-root `Path` values, symbol allowlists, explicit provider selection, and rejected unknown/misspelled configuration.
  - Replace broad catch-and-overwrite recovery with typed failures, schema validation, atomic writes, backups/quarantine for corrupt files, and transactional or idempotent state transitions.
  - Save an immutable artifact manifest containing training range, data checksum, feature/label versions, estimator and calibration parameters, dependency versions, Git revision, evaluation report, and promotion status.
  - Keep presentation labels and Telegram formatting outside the prediction domain, and return non-zero CLI status codes for failed automated commands.

[ ] **8. Implement the Telegram discretionary-signal lifecycle only after a model is research-approved.**
  - Keep the bot read-only with respect to brokers/exchanges; store only the Telegram token and chat allowlist, never trading credentials.
  - Publish each new call with instrument and venue, side and order type, closed-bar timestamp/timeframe/timezone, entry or entry zone, do-not-chase boundary, SL, TP, gross R:R, cost-adjusted expectancy, calibrated confidence, risk cap, expiry, invalidation, setup/context explanation, support, and model version.
  - Model explicit states such as `candidate`, `rejected`, `pending`, `triggered`, `cancelled`, `expired`, `tp`, and `sl`; send edits or threaded updates without duplicating calls after retries or restarts.
  - Cancel or expire a pending call when price moves beyond its allowed entry, spread exceeds limits, data becomes stale, the market closes, or the research-defined invalidation occurs.
  - Maintain an immutable strategy ledger based on the exact published rules and market feed, regardless of whether the user takes the trade.
  - Optionally let the user record a discretionary execution with actual entry, size, exit, and notes in a separate ledger; never merge these results into the strategy's backtest/paper performance.
  - Include a clear manual-execution warning that delayed or modified entries change the published R:R and that missed entry zones should be skipped rather than chased.

[ ] **9. Add quality, security, and operational gates.**
  - Add unit tests for candle geometry, taxonomy boundaries, causal feature timing, barrier labels, expected-value math, calibration gates, trade construction, and lifecycle transitions.
  - Add provider contract tests, malformed/stale payload tests, deterministic end-to-end fixture tests, walk-forward leakage tests, Telegram formatting tests, and duplicate-delivery/idempotency tests.
  - Configure formatting, linting, strict type checking, secret scanning, dependency auditing, and CI across the supported Python versions; require all gates before artifact promotion.
  - Use structured logs and metrics for data age, missing bars, spread rejection, candidate/rejection counts, sent signals, delivery failures, calibration drift, and outcome reconciliation.
  - Protect Telegram commands and callbacks with a chat allowlist, rate limits, redacted logs, least-privilege secrets, and an emergency delivery kill switch.
  - Test provider outages, partial writes, clock drift, DST/session changes, Telegram outages, process restarts, duplicate bars, model incompatibility, and rollback to the last approved artifact.

[ ] **10. Promote through staged evidence rather than a single release.**
  - Stage A — offline research: accept a representation only if it beats locked baselines across future folds and remains positive after conservative costs.
  - Stage B — shadow replay: run the live data path without sending Telegram messages and compare timestamped decisions with offline replay for train/serve parity.
  - Stage C — private paper Telegram: send calls to an allowlisted private chat, assume no capital is at risk, and reconcile every signal automatically.
  - Stage D — locked forward paper period: prohibit strategy changes for the approved evaluation window; restart the evidence period after any material model/rule change.
  - Stage E — discretionary live pilot: allow manual execution only after explicit review of calibration, expectancy, drawdown, delivery reliability, and failure handling; cap risk independently of backtest confidence.
  - Define rollback triggers for data-quality failures, calibration drift, abnormal drawdown, unexplained train/serve divergence, stale models, or delivery/state inconsistencies.
  - Keep automatic execution out of scope; require a new threat model, broker-integration design, approval process, and separate plan if it is ever proposed.

## Open questions
- Should the proposed reference entry—first executable quote 60 seconds after publication, valid until the next M15 close—be approved or made more conservative for manual execution?
- Should the proposed four-bar structural stop with volatility/spread buffer, fixed 2R target, and eight-M15-bar maximum holding period be approved unchanged?
- Which economic-calendar source should provide reproducible high-impact USD event timestamps, or should the news gate be deferred from the first offline experiment?
- What conservative live-policy limits should be reviewed up front: risk percentage per call, minimum gross R:R, minimum calibrated edge/support, maximum simultaneous exposure, and required paper-trading duration?
