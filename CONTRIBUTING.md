# Contributing to Sika

Sika is still in its research phase. Changes should improve evidence quality,
reproducibility, or safety before they expand product scope.

## Start here

Read these documents before changing behavior:

1. [`README.md`](README.md) for the current product boundary.
2. [`docs/research-contract.md`](docs/research-contract.md) for normative rules.
3. [`THOUGHT_PROCESS.md`](THOUGHT_PROCESS.md) for decisions and current status.
4. [`docs/operations/mt5.md`](docs/operations/mt5.md) for terminal workflows.

Create the exact Python environment and run the baseline checks:

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uvx --from ruff==0.15.20 ruff check .
```

## Change standard

- Keep active Python code inside `src/sika/`; do not add new root scripts.
- Use descriptive snake-case module and function names and PascalCase classes.
- Keep command-line parsing at the boundary and domain logic in testable
  functions.
- Fail closed when identity, time, data completeness, or configuration is
  uncertain.
- Add tests for contracts whose failure could invalidate research, leak private
  information, or enable unsafe behavior. Do not add tests merely to increase a
  coverage number.
- Update `THOUGHT_PROCESS.md` when a product, research, architecture, safety, or
  operating decision changes. Small formatting-only edits do not need an entry.
- Keep documentation about purpose, contracts, and operation; avoid prose that
  just repeats implementation line by line.

Research-changing values belong in a reviewed file under `config/`. Environment
variables are for operational concerns such as logging, never for silently
changing labels, sessions, risk, or evaluation rules.

## Data and secrets

Do not commit:

- MT5 credentials, account numbers, holder details, or Telegram tokens;
- broker exports, generated audit receipts, logs, or trained models;
- `.env` files, virtual environments, caches, or compiled `.ex5` files.

Use synthetic fixtures in tests. If a defect requires a real-data example,
reduce and anonymize it before review.

## MQL5 changes

Every MQL5 change must preserve the read-only safety boundary, pass
`tests/test_mql5_safety_boundary.py`, and compile in the supported MetaEditor
build with zero errors and zero warnings. Record the compiler result in the pull
request.

## Before requesting review

- Rebase or merge the latest `main` without discarding another contributor's
  work.
- Run all Python tests and Ruff checks.
- Review `git diff --check` and `git status --short`.
- Explain the user-visible effect, evidence, remaining uncertainty, and any
  intentional nonzero status.
- Use focused commits with imperative subjects, for example
  `feat(market-data): enforce excluded research sessions`.
