"""Tests for the AutonomousRunner class."""

import pytest
import asyncio
from autonomous_runner import AutonomousRunner, get_runner, init_runner


class TestRunnerInit:
    def test_default_init(self):
        runner = AutonomousRunner()
        assert runner.poll_interval == 10
        assert runner.max_concurrent == 3
        assert runner.budget_limit_usd == 5.0

    def test_custom_init(self):
        runner = AutonomousRunner(poll_interval=30, max_concurrent=5, budget_limit_usd=10.0)
        assert runner.poll_interval == 30
        assert runner.max_concurrent == 5
        assert runner.budget_limit_usd == 10.0

    def test_initial_state(self):
        runner = AutonomousRunner()
        assert runner._running is False
        assert runner._poll_task is None
        assert runner._active_jobs == {}

    def test_get_stats(self):
        runner = AutonomousRunner()
        stats = runner.get_stats()
        assert "running" in stats
        assert "active_jobs" in stats
        assert stats["running"] is False
        assert stats["active_jobs"] == 0


class TestRunnerSingleton:
    def test_init_runner_creates_instance(self):
        runner = init_runner(poll_interval=15)
        assert runner is not None
        assert runner.poll_interval == 15

    def test_get_runner_returns_instance(self):
        init_runner(poll_interval=20)
        runner = get_runner()
        assert runner is not None
        assert runner.poll_interval == 20
