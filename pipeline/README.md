# OpenClaw Pipeline Package

Modular components extracted from `autonomous_runner.py` (4700+ lines).

## Modules

| Module | What it contains | Lines |
|--------|-----------------|-------|
| `models.py` | `Phase`, `PlanStep`, `ExecutionPlan`, `JobProgress` | ~75 |
| `errors.py` | Error classification (6 categories), loop detection | ~120 |
| `guardrails.py` | `JobGuardrails`, kill flags, budget/iteration limits | ~230 |

## Usage

```python
# New (preferred)
from pipeline import Phase, JobGuardrails, classify_error

# Old (still works for backward compat)
from autonomous_runner import Phase, JobGuardrails, _classify_error
```

## Next Extractions

These are still in `autonomous_runner.py` and will be extracted:
- **context.py** — `_load_project_context`, `_build_context_bundle`, worktree management
- **agents.py** — `_select_agent_for_job`, `_classify_department`, `_call_agent`
- **phases.py** — Research, Plan, Execute, Review, Verify, Deliver phase functions
