# Task 1 report: Loan Demo Status contract and aggregation

## RED/GREEN evidence

- RED command: `cd archived-apps/loan-preprocessing-agents/backend && uv run python -m unittest tests.test_status_aggregation -v`
- RED result: `ModuleNotFoundError: No module named 'status_models'` (expected missing implementation).
- Additional RED command after adding the `checking` edge-case test: same focused command.
- Additional RED result: one failure, `checking` was incorrectly returned as `ready`.
- GREEN command: `uv run python -m unittest tests.test_status_aggregation -v`
- GREEN result: `Ran 7 tests ... OK`.
- Full suite command: `uv run python -m unittest discover -s tests -v`
- Full suite result: `Ran 138 tests ... OK (skipped=2)`; exit code 0.

## Changed files

- `archived-apps/loan-preprocessing-agents/backend/status_models.py`
- `archived-apps/loan-preprocessing-agents/backend/services/status_aggregation.py`
- `archived-apps/loan-preprocessing-agents/backend/tests/test_status_aggregation.py`

## Self-check

- Public Pydantic models use `extra="forbid"` and expose only the specified fields.
- Capability dependency mapping and status precedence are fixed and deterministic.
- Missing dependencies are treated as `unknown`; `checking` is treated as limited until verified.
- `openllmetry` is intentionally not a capability dependency.
- No network, database, FastAPI, `loan_app.db`, or `logs.json` changes were made by this task.

## Concerns

- Existing suite emits a passlib/bcrypt compatibility traceback and a Pydantic deprecation warning, but tests still pass. These pre-existing warnings are outside Task 1.
