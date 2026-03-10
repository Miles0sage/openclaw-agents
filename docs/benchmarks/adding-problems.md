# Adding Problems

Add benchmark tasks with clear acceptance checks and deterministic grading.

## Problem Guidelines

- Single objective per problem
- Explicit input/output constraints
- Include edge-case tests
- Provide a rubric if judged by LLM

## Workflow

1. Add task file in `tasks/`
2. Add expected output or tests
3. Register in benchmark suite definition
4. Run `/api/eval/run` and validate scoring behavior
