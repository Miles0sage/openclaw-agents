"""
Supervisor for OpenClaw — Complexity Classification + Task Decomposition

1. ComplexityClassifier: Routes queries to optimal model (Haiku/Sonnet/Opus).
2. maybe_decompose_and_execute: Analyzes if a job should be split into parallel
   sub-tasks via tmux agents. Returns aggregated result or None (skip).
"""

import re
import math
import os
import json
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger("supervisor")

# Feb 2026 Claude API pricing (per million tokens)
MODEL_PRICING = {
    "haiku": {"input": 0.8, "output": 4.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "opus": {"input": 15.0, "output": 75.0},
}

MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-6",
}

MODEL_RATE_LIMITS = {
    "haiku": {"requestsPerMinute": 100, "tokensPerMinute": 500000},
    "sonnet": {"requestsPerMinute": 50, "tokensPerMinute": 200000},
    "opus": {"requestsPerMinute": 25, "tokensPerMinute": 100000},
}


@dataclass
class ClassificationResult:
    complexity: int  # 0-100
    model: str  # "haiku" | "sonnet" | "opus"
    confidence: float  # 0-1
    reasoning: str
    estimated_tokens: int
    cost_estimate: float  # USD


class ComplexityClassifier:
    HAIKU_THRESHOLD = 30
    SONNET_THRESHOLD = 70

    HIGH_COMPLEXITY_KEYWORDS = [
        "architect", "design", "pattern", "refactor", "optimization",
        "performance", "scalability", "security", "vulnerability", "exploit",
        "threat", "strategy", "algorithm", "system design", "infrastructure",
        "deployment", "deployment strategy", "framework", "machine learning",
        "distributed", "consensus", "transaction", "atomic", "fault tolerance",
        "complex reasoning", "tradeoffs", "trade-offs", "scale", "global",
        "concurrent", "pipeline", "microservice", "approach",
        "failover", "multi-region", "latency", "throughput",
    ]

    MEDIUM_COMPLEXITY_KEYWORDS = [
        "review", "fix", "bug", "error", "issue", "debug", "refactoring",
        "improve", "enhancement", "feature", "implement", "integration",
        "testing", "test case", "coverage", "documentation", "explain",
        "how to", "guide", "setup", "authentication", "api", "endpoint",
        "module", "component", "state", "pr",
    ]

    LOW_COMPLEXITY_KEYWORDS = [
        "hello", "hi", "thank", "thanks", "please", "help", "format",
        "convert", "change", "replace", "simple", "basic", "quick",
    ]

    def match_keyword(self, query: str, keyword: str) -> bool:
        """Match keyword with word-start boundary awareness."""
        if " " in keyword:
            return keyword in query
        if len(keyword) <= 3:
            return bool(re.search(rf"\b{re.escape(keyword)}\b", query))
        return bool(re.search(rf"\b{re.escape(keyword)}", query))

    def classify(self, query: str) -> ClassificationResult:
        normalized = query.lower()
        complexity = 0
        factors: List[str] = []

        # 1. Keyword analysis
        ks = self._analyze_keywords(normalized)
        complexity += ks[0]
        factors.extend(ks[1])

        # 2. Length analysis
        ls = self._analyze_length(query)
        complexity += ls[0]
        factors.extend(ls[1])

        # 3. Code block analysis
        cs = self._analyze_code_blocks(query)
        complexity += cs[0]
        factors.extend(cs[1])

        # 4. Context analysis
        ctx = self._analyze_context(normalized)
        complexity += ctx[0]
        factors.extend(ctx[1])

        # 5. Question analysis
        qs = self._analyze_questions(normalized)
        complexity += qs[0]
        factors.extend(qs[1])

        complexity = max(0, min(100, complexity))
        model, confidence = self._select_model(complexity, normalized)
        estimated_tokens = self._estimate_tokens(query)
        cost_estimate = self._estimate_cost(model, estimated_tokens)

        reasoning = self._build_reasoning(factors, complexity, model)

        return ClassificationResult(
            complexity=round(complexity),
            model=model,
            confidence=round(confidence * 100) / 100,
            reasoning=reasoning,
            estimated_tokens=estimated_tokens,
            cost_estimate=round(cost_estimate * 1000000) / 1000000,
        )

    def _analyze_keywords(self, query: str) -> Tuple[int, List[str]]:
        score = 0
        factors: List[str] = []

        high_kws = [kw for kw in self.HIGH_COMPLEXITY_KEYWORDS if self.match_keyword(query, kw.lower())]
        if high_kws:
            score += 30 + len(high_kws) * 18
            factors.append(f"High complexity keywords ({', '.join(high_kws)})")

        medium_kws = [kw for kw in self.MEDIUM_COMPLEXITY_KEYWORDS if self.match_keyword(query, kw.lower())]
        if medium_kws:
            medium_base = 5 if high_kws else 22
            medium_per = 5 if high_kws else 10
            score += medium_base + len(medium_kws) * medium_per
            factors.append(f"Medium complexity keywords ({', '.join(medium_kws)})")

        low_kws = [kw for kw in self.LOW_COMPLEXITY_KEYWORDS if self.match_keyword(query, kw.lower())]
        if low_kws and not high_kws and not medium_kws:
            score -= len(low_kws) * 8
            factors.append(f"Low complexity keywords ({', '.join(low_kws)})")
        elif low_kws:
            score -= len(low_kws) * 3
            factors.append(f"Low complexity keywords ({', '.join(low_kws)})")

        return max(0, score), factors

    def _analyze_length(self, query: str) -> Tuple[int, List[str]]:
        length = len(query)
        factors: List[str] = []

        if length < 30:
            score = -5
            factors.append("Very short query")
        elif length < 100:
            score = 0
            factors.append("Short query")
        elif length < 200:
            score = 3
            factors.append("Medium-short query")
        elif length < 500:
            score = 8
            factors.append("Medium query length")
        elif length < 1000:
            score = 12
            factors.append("Long query")
        elif length < 3000:
            score = 18
            factors.append("Very long query")
        else:
            score = 25
            factors.append("Extensive query with substantial context")

        return score, factors

    def _analyze_code_blocks(self, query: str) -> Tuple[int, List[str]]:
        factors: List[str] = []
        score = 0

        backtick_count = len(re.findall(r"```", query))
        inline_code_count = len(re.findall(r"`[^`]+`", query))

        if backtick_count > 0:
            score += backtick_count * 8
            factors.append(f"{backtick_count} code block(s)")
        if inline_code_count > 0:
            score += inline_code_count * 3
            factors.append(f"{inline_code_count} inline code snippet(s)")

        file_exts = re.findall(r"\.\w{2,4}\b", query)
        code_exts = [ext for ext in file_exts if re.match(r"\.(ts|js|py|java|go|rs|rb|php|sql|json|yaml|xml|html|css)$", ext, re.I)]
        if code_exts:
            score += len(code_exts) * 3
            factors.append(f"File references ({', '.join(code_exts)})")

        return max(0, score), factors

    def _analyze_context(self, query: str) -> Tuple[int, List[str]]:
        factors: List[str] = []
        score = 0

        if any(x in query for x in ["also,", "additionally,", "furthermore,"]):
            score += 5
            factors.append("Multi-part question")
        if any(x in query for x in ["based on", "given the", "considering"]):
            score += 8
            factors.append("Contextual dependency")
        if any(x in query for x in ["compared to", "difference between", "vs."]):
            score += 5
            factors.append("Comparative analysis")

        return max(0, score), factors

    def _analyze_questions(self, query: str) -> Tuple[int, List[str]]:
        factors: List[str] = []
        score = 0

        q_count = query.count("?")
        why_count = len(re.findall(r"\bwhy\b", query, re.I))
        how_count = len(re.findall(r"\bhow\b", query, re.I))
        what_if_count = len(re.findall(r"\bwhat if\b", query, re.I))

        if q_count > 0:
            score += min(q_count * 3, 15)
            factors.append(f"{q_count} question(s)")
        if why_count > 0:
            score += why_count * 5
            factors.append("Deep reasoning requested (why)")
        if how_count > 0:
            score += how_count * 4
            factors.append("Implementation guidance requested (how)")
        if what_if_count > 0:
            score += what_if_count * 8
            factors.append("Hypothetical scenario analysis (what if)")

        return max(0, score), factors

    def _select_model(self, complexity: int, query: str) -> Tuple[str, float]:
        if complexity <= self.HAIKU_THRESHOLD:
            model = "haiku"
            confidence = min(1.0, 0.7 + (1 - complexity / self.HAIKU_THRESHOLD) * 0.3)
        elif complexity < self.SONNET_THRESHOLD:
            model = "sonnet"
            relative_pos = (complexity - self.HAIKU_THRESHOLD) / (self.SONNET_THRESHOLD - self.HAIKU_THRESHOLD)
            confidence = 0.6 + relative_pos * 0.2
        else:
            model = "opus"
            confidence = min(1.0, 0.72 + ((complexity - self.SONNET_THRESHOLD) / (100 - self.SONNET_THRESHOLD)) * 0.28)

        return model, confidence

    def _estimate_tokens(self, query: str) -> int:
        base = math.ceil(len(query) / 4)
        return math.ceil(base * 2)

    def _estimate_cost(self, model: str, tokens: int) -> float:
        pricing = MODEL_PRICING[model]
        input_tokens = tokens // 3
        output_tokens = tokens - input_tokens
        return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    def _build_reasoning(self, factors: List[str], complexity: int, model: str) -> str:
        unique = list(dict.fromkeys(factors))[:3]
        factor_str = "; ".join(unique) if unique else "minimal"
        return f"Complexity: {complexity}/100. Factors: {factor_str}. Recommended: {model.upper()}."


# Singleton instance
_classifier = ComplexityClassifier()


def classify(query: str) -> ClassificationResult:
    """Convenience function for single classification."""
    return _classifier.classify(query)


# ═══════════════════════════════════════════════════════════════════════════════
# Task Decomposition + Parallel Execution via TmuxSpawner
# ═══════════════════════════════════════════════════════════════════════════════

# Signals that a task might benefit from parallel decomposition
DECOMPOSITION_SIGNALS = [
    # Multi-file indicators
    r"\b\d+\s*files?\b",
    r"multiple\s+(files?|components?|modules?|endpoints?)",
    r"across\s+(the\s+)?(codebase|project|repo)",
    # Parallel-friendly task patterns
    r"\band\b.*\band\b",  # "do X and Y and Z"
    r"(?:first|then|also|additionally).*(?:first|then|also|additionally)",
    # Explicit multi-step
    r"\b(step\s*\d|phase\s*\d|part\s*\d)\b",
]

# Tasks that should NEVER be decomposed (ordering matters)
NO_DECOMPOSE_PATTERNS = [
    r"simple\s+fix",
    r"\btypo\b",
    r"change\s+color",
    r"update\s+text",
    r"rename\s+\w+",
    r"add\s+a?\s*comment",
]

# Minimum estimated duration (seconds) to justify decomposition overhead
MIN_DURATION_FOR_DECOMPOSE = 300  # 5 minutes

# Max sub-tasks to prevent resource exhaustion
MAX_SUB_TASKS = 4

# Timeout for waiting on all sub-tasks
SUB_TASK_TIMEOUT = 1800  # 30 minutes


def _should_decompose(job: dict) -> Tuple[bool, str]:
    """
    Analyze whether a job should be decomposed into parallel sub-tasks.
    Returns (should_decompose, reason).
    """
    task = job.get("task", "")
    task_lower = task.lower()

    # Never decompose simple tasks
    for pat in NO_DECOMPOSE_PATTERNS:
        if re.search(pat, task_lower):
            return False, f"Simple task pattern: {pat}"

    # Check for decomposition signals
    signals_found = []
    for pat in DECOMPOSITION_SIGNALS:
        if re.search(pat, task_lower):
            signals_found.append(pat)

    if not signals_found:
        return False, "No decomposition signals found"

    # Need at least 2 signals to justify the overhead
    if len(signals_found) < 2:
        # Unless the task is explicitly long
        word_count = len(task.split())
        if word_count < 50:
            return False, f"Only {len(signals_found)} signal(s) and short task ({word_count} words)"

    # Check complexity via classifier
    result = _classifier.classify(task)
    if result.complexity < 50:
        return False, f"Complexity too low ({result.complexity}/100) for decomposition"

    return True, f"Decomposition justified: {len(signals_found)} signals, complexity={result.complexity}"


def _decompose_task(job: dict) -> List[dict]:
    """
    Split a job's task into independent sub-tasks.
    Uses heuristic parsing — looks for bullet points, numbered steps,
    "and" conjunctions, or multi-file references.
    """
    task = job.get("task", "")
    sub_tasks = []

    # Strategy 1: Explicit numbered steps or bullets
    # Match "1. ...", "- ...", "* ..."
    numbered = re.findall(r"(?:^|\n)\s*(?:\d+[.)]\s+|[-*]\s+)(.+?)(?=\n\s*(?:\d+[.)]\s+|[-*]\s+)|\Z)", task, re.DOTALL)
    if len(numbered) >= 2:
        for i, step in enumerate(numbered[:MAX_SUB_TASKS]):
            sub_tasks.append({
                "index": i,
                "description": step.strip(),
                "independent": True,
            })
        return sub_tasks

    # Strategy 2: Split on "and" / "also" / "additionally" conjunctions
    # Only if the task has clear independent clauses
    parts = re.split(r"\.\s+(?:Also|Additionally|Then|Next|Furthermore)\s*,?\s*", task, flags=re.IGNORECASE)
    if len(parts) >= 2:
        for i, part in enumerate(parts[:MAX_SUB_TASKS]):
            part = part.strip().rstrip(".")
            if len(part) > 20:  # Skip trivially short fragments
                sub_tasks.append({
                    "index": i,
                    "description": part,
                    "independent": True,
                })
        if len(sub_tasks) >= 2:
            return sub_tasks

    # Strategy 3: If task mentions multiple files, split by file
    file_refs = re.findall(r"(?:[\w./]+\.(?:py|ts|js|tsx|jsx|html|css|json|yaml|md))", task)
    if len(file_refs) >= 3:
        # Group by file — create one sub-task per unique file
        seen = set()
        for f in file_refs[:MAX_SUB_TASKS]:
            if f not in seen:
                seen.add(f)
                sub_tasks.append({
                    "index": len(sub_tasks),
                    "description": f"Handle changes for {f}: {task[:200]}",
                    "independent": True,
                    "target_file": f,
                })
        if len(sub_tasks) >= 2:
            return sub_tasks

    # Can't decompose cleanly — return empty
    return []


async def maybe_decompose_and_execute(job: dict, project_root: str = "/root/openclaw") -> Optional[dict]:
    """
    Analyze if a job should be decomposed into parallel sub-tasks.
    If yes, spawn tmux agents for each sub-task, wait for completion,
    and return aggregated results.

    Returns None if the job should NOT be decomposed (normal pipeline continues).
    Returns a result dict if decomposition was used.
    """
    should, reason = _should_decompose(job)
    if not should:
        logger.info(f"Job {job.get('id', '?')}: No decomposition — {reason}")
        return None

    sub_tasks = _decompose_task(job)
    if len(sub_tasks) < 2:
        logger.info(f"Job {job.get('id', '?')}: Decomposition produced <2 sub-tasks, skipping")
        return None

    job_id = job.get("id", "unknown")
    logger.info(f"Job {job_id}: Decomposing into {len(sub_tasks)} parallel sub-tasks")

    # Import tmux_spawner here to avoid circular imports
    try:
        from tmux_spawner import TmuxSpawner
    except ImportError:
        logger.warning(f"Job {job_id}: tmux_spawner not available, skipping decomposition")
        return None

    spawner = TmuxSpawner()

    # Build prompts for each sub-task
    project = job.get("project", "openclaw")
    base_context = (
        f"You are working on project '{project}'. "
        f"Project root: {project_root}\n"
        f"Original task: {job.get('task', '')}\n\n"
        f"Your specific sub-task:\n"
    )

    spawn_jobs = []
    for st in sub_tasks:
        sub_job_id = f"{job_id}-sub{st['index']}"
        prompt = base_context + st["description"]
        spawn_jobs.append({
            "job_id": sub_job_id,
            "prompt": prompt,
            "cwd": project_root,
            "timeout_minutes": 15,
        })

    # Spawn all sub-tasks in parallel
    spawn_results = spawner.spawn_parallel(spawn_jobs)
    spawned = [r for r in spawn_results if r["status"] == "spawned"]

    if not spawned:
        logger.error(f"Job {job_id}: All sub-task spawns failed")
        return None

    logger.info(f"Job {job_id}: {len(spawned)}/{len(spawn_jobs)} agents spawned")

    # Wait for all agents to complete (poll every 10s, timeout after SUB_TASK_TIMEOUT)
    start_time = time.time()
    completed = {}
    while time.time() - start_time < SUB_TASK_TIMEOUT:
        all_done = True
        for sr in spawned:
            if sr["job_id"] in completed:
                continue
            agent_status = spawner.get_agent_status(sr["pane_id"])
            is_exited = agent_status and agent_status.get("status") == "exited"
            is_gone = agent_status is None
            # Also check for completion marker in pane output (agent prints this before sleep)
            has_marker = False
            if agent_status and agent_status.get("status") == "running":
                try:
                    pane_text = spawner.collect_output(sr["pane_id"], lines=20, job_id=sr["job_id"])
                    if pane_text and "[AGENT_EXIT" in pane_text:
                        has_marker = True
                except Exception:
                    pass
            if is_exited or is_gone or has_marker:
                output = spawner.collect_output(sr["pane_id"], job_id=sr["job_id"])
                runtime = agent_status.get("runtime_seconds", 0) if agent_status else int(time.time() - start_time)
                completed[sr["job_id"]] = {
                    "job_id": sr["job_id"],
                    "status": "completed",
                    "output": output[:5000] if output else "",
                    "runtime_seconds": runtime,
                }
                how = "exited" if is_exited else ("marker" if has_marker else "pane gone")
                logger.info(f"Sub-task {sr['job_id']} completed ({runtime}s, detected via {how})")
            else:
                all_done = False

        if all_done:
            break
        await asyncio.sleep(10)

    # Kill any still-running agents after timeout
    for sr in spawned:
        if sr["job_id"] not in completed:
            try:
                spawner.kill_agent(sr["pane_id"])
            except Exception:
                pass
            completed[sr["job_id"]] = {
                "job_id": sr["job_id"],
                "status": "timeout",
                "output": "",
                "runtime_seconds": int(time.time() - start_time),
            }
            logger.warning(f"Sub-task {sr['job_id']} timed out after {SUB_TASK_TIMEOUT}s")

    # Aggregate results
    successful = [c for c in completed.values() if c["status"] == "completed"]
    total_runtime = sum(c.get("runtime_seconds", 0) for c in completed.values())

    result = {
        "success": len(successful) == len(spawned),
        "sub_tasks_completed": len(successful),
        "sub_tasks_total": len(spawned),
        "decomposition": {
            "reason": reason,
            "sub_task_count": len(sub_tasks),
            "descriptions": [st["description"][:200] for st in sub_tasks],
        },
        "sub_tasks": list(completed.values()),
        "summary": (
            f"Decomposed into {len(sub_tasks)} sub-tasks. "
            f"{len(successful)}/{len(spawned)} completed successfully. "
            f"Total agent runtime: {total_runtime}s."
        ),
        "total_runtime_seconds": total_runtime,
    }

    logger.info(f"Job {job_id}: Decomposition complete — {result['summary']}")
    return result
