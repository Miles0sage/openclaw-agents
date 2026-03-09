"""Benchmark problem definition and YAML loader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml


@dataclass
class FileSetup:
    """A file to create in the workspace before the agent runs."""

    path: str
    content: str


@dataclass
class FileExpectation:
    """Expected state of a file after the agent runs."""

    path: str
    must_exist: bool = True
    contains: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)
    regex_match: list[str] = field(default_factory=list)


@dataclass
class CommandExpectation:
    """A shell command expectation after the agent runs."""

    command: str
    exit_code: int = 0
    stdout_contains: list[str] = field(default_factory=list)
    stdout_not_contains: list[str] = field(default_factory=list)


@dataclass
class BenchmarkProblem:
    """A single benchmark problem."""

    id: str
    category: str
    difficulty: str
    description: str
    agent_key: str = "coder_agent"
    department: str = "engineering"

    setup_files: list[FileSetup] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)

    file_expectations: list[FileExpectation] = field(default_factory=list)
    command_expectations: list[CommandExpectation] = field(default_factory=list)

    max_cost_usd: float = 0.10
    max_duration_sec: float = 120.0
    min_quality_score: float = 0.6

    tags: list[str] = field(default_factory=list)
    source: str = "custom"

    def to_job_request(self, workspace_dir: str) -> dict[str, Any]:
        return {
            "task": self.description,
            "department": self.department,
            "priority": "P2",
            "metadata": {
                "benchmark_id": self.id,
                "category": self.category,
                "difficulty": self.difficulty,
                "workspace": workspace_dir,
            },
        }



def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]



def load_problem(yaml_path: str) -> BenchmarkProblem:
    """Load a benchmark problem from a YAML file."""

    with open(yaml_path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if "id" not in raw:
        raise ValueError(f"Benchmark problem missing required 'id': {yaml_path}")
    if "description" not in raw:
        raise ValueError(f"Benchmark problem missing required 'description': {yaml_path}")

    setup = raw.get("setup", {}) if isinstance(raw.get("setup", {}), dict) else {}
    expected = raw.get("expected", {}) if isinstance(raw.get("expected", {}), dict) else {}

    setup_files = [
        FileSetup(path=str(fs["path"]), content=str(fs.get("content", "")))
        for fs in setup.get("files", [])
        if isinstance(fs, dict) and "path" in fs
    ]

    file_expectations = [
        FileExpectation(
            path=str(fe["path"]),
            must_exist=bool(fe.get("must_exist", True)),
            contains=_as_list(fe.get("contains")),
            not_contains=_as_list(fe.get("not_contains")),
            regex_match=_as_list(fe.get("regex_match")),
        )
        for fe in expected.get("files", [])
        if isinstance(fe, dict) and "path" in fe
    ]

    command_expectations = [
        CommandExpectation(
            command=str(ce["command"]),
            exit_code=int(ce.get("exit_code", 0)),
            stdout_contains=_as_list(ce.get("stdout_contains")),
            stdout_not_contains=_as_list(ce.get("stdout_not_contains")),
        )
        for ce in expected.get("commands", [])
        if isinstance(ce, dict) and "command" in ce
    ]

    return BenchmarkProblem(
        id=str(raw["id"]),
        category=str(raw.get("category", "general")),
        difficulty=str(raw.get("difficulty", "medium")),
        description=str(raw["description"]),
        agent_key=str(raw.get("agent_key", "coder_agent")),
        department=str(raw.get("department", "engineering")),
        setup_files=setup_files,
        setup_commands=[str(cmd) for cmd in setup.get("commands", [])],
        file_expectations=file_expectations,
        command_expectations=command_expectations,
        max_cost_usd=float(raw.get("max_cost_usd", 0.10)),
        max_duration_sec=float(raw.get("max_duration_sec", 120.0)),
        min_quality_score=float(raw.get("min_quality_score", 0.6)),
        tags=[str(t) for t in raw.get("tags", [])],
        source=str(raw.get("source", "custom")),
    )



def load_suite(suite_dir: str) -> list[BenchmarkProblem]:
    """Load all YAML problems from a directory recursively."""

    problems: list[BenchmarkProblem] = []
    for dirpath, _, names in os.walk(suite_dir):
        for name in sorted(names):
            if name.endswith((".yaml", ".yml")):
                problems.append(load_problem(os.path.join(dirpath, name)))
    return problems
