---
description: PrestressCalc — ACI 318-19 prestressed concrete beam calculator, engineering portfolio piece
agent: codegen
tags: [project, engineering, python, calculator, aci]
priority: medium
---

# PrestressCalc

Engineering calculator for prestressed concrete beams per ACI 318-19. Portfolio piece for landing a prestressed concrete engineering job.

## Stack

- Python 3.13, pint (units), numpy, scipy, matplotlib
- Streamlit (UI), fpdf2 (PDF reports)
- 358/358 tests passing
- Repo: github.com/Miles0sage/Mathcad-Scripts
- Local: /root/Mathcad-Scripts/

## Modules (Phase 1-4B Complete)

- `prestressed/beam_design.py` — master wrapper, complete_beam_design()
- `prestressed/shear_design.py` — Vci, Vcw, stirrups per ACI 22.5.8
- `prestressed/deflection.py` — camber, L/240, L/360 per ACI 24.2
- `prestressed/load_cases.py` — LoadCase, LoadCaseManager, ACI combinations
- `prestressed/cost_analysis.py` — CostOptimizer, sensitivity analysis, multi-objective

## Key Decisions

- [[codegen-development]] handles all code changes (Python only)
- Always run full test suite (358 tests) before committing
- Use pint for all unit conversions — never hardcode conversion factors
- ACI code references must be cited in docstrings

## Sensitive Areas

- Engineering calculations must be accurate — lives depend on this
- Unit handling (pint) — mixed unit bugs are silent and dangerous
- Cost data must reflect real market rates for credibility
- Never use approximate formulas when ACI provides exact ones

## Current Status

Phase 4B complete. 358/358 tests. Ready for Phase 5 (optional GUI optimization).

## Cost

- Zero runtime cost (local Python)
- Only cost is [[codegen-development]] agent time for changes
