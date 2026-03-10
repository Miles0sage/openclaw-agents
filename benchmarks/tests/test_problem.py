"""Tests for benchmark problem loading."""

from pathlib import Path

from benchmarks.problem import BenchmarkProblem, load_problem, load_suite

SAMPLE_YAML = """
id: test-problem
category: bug_fix
difficulty: easy
description: Fix the thing
setup:
  files:
    - path: src/app.py
      content: "print('hello')"
expected:
  files:
    - path: src/app.py
      contains:
        - world
      not_contains:
        - hello
"""



def test_load_problem(tmp_path: Path):
    p = tmp_path / "p.yaml"
    p.write_text(SAMPLE_YAML, encoding="utf-8")

    problem = load_problem(str(p))
    assert problem.id == "test-problem"
    assert problem.category == "bug_fix"
    assert problem.difficulty == "easy"
    assert len(problem.setup_files) == 1
    assert problem.setup_files[0].path == "src/app.py"
    assert len(problem.file_expectations) == 1
    assert "world" in problem.file_expectations[0].contains
    assert "hello" in problem.file_expectations[0].not_contains



def test_load_suite(tmp_path: Path):
    for i in range(3):
        p = tmp_path / f"p{i}.yaml"
        p.write_text(SAMPLE_YAML.replace("test-problem", f"test-{i}"), encoding="utf-8")

    problems = load_suite(str(tmp_path))
    assert len(problems) == 3
    assert [p.id for p in problems] == ["test-0", "test-1", "test-2"]



def test_to_job_request():
    p = BenchmarkProblem(id="t1", category="bug_fix", difficulty="easy", description="Do it")
    req = p.to_job_request("/tmp/workspace")
    assert req["task"] == "Do it"
    assert req["metadata"]["benchmark_id"] == "t1"


def test_default_suite_has_15_yaml_problems():
    suite_dir = Path(__file__).resolve().parents[1] / "problems"
    problems = load_suite(str(suite_dir))
    assert len(problems) == 15
