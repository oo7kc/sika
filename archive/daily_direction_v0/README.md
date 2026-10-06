# Daily-direction prototype (frozen)

This directory preserves the predecessor Sika implementation as it existed
before the project moved to executable, research-validated `XAUUSDm` trade
plans. It is historical source, not an alternative active application.

The prototype predicted a broad daily direction from technical indicators and a
multi-layer perceptron. That output did not define a tradable entry, stop-loss,
take-profit, risk/reward, or expiry, and its prior accuracy claims are not
accepted evidence under the current research contract.

Contents:

- `main.py` — the former interactive CLI;
- `config.py` — the former environment-driven model configuration;
- `scripts/` — data, indicator, training, prediction, display, and logging code;
- `requirements.txt` — the frozen dependency list for historical reference;
- `runtime/` — ignored local data, credentials, models, and logs, if retained on
  a developer machine.

This directory is excluded from active packaging, dependency resolution, tests,
and product documentation. Do not import from it or build new work on it. Use
Git history if a previous revision is needed; use the active `src/sika` package
for all current development.
