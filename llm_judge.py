"""
OpenClaw LLM-as-Judge Evaluation System
=========================================
Auto-grades agent output quality using a structured rubric.
Runs after DELIVER phase to score correctness, completeness, and code quality.

Usage:
    judge = LLMJudge()
    score = await judge.score_output(job_context)
    # score.overall = 0.85, score.reasoning = "Code is correct but missing edge case..."

Architecture:
    - Rubric-based scoring (per agent type)
    - Uses cheapest available model for grading (Kimi 2.5 by default)
    - Structured JSON output with confidence scores
    - Stores scores in job results for analytics
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

logger = logging.getLogger("openclaw.judge")


# ---------------------------------------------------------------------------
# Score Models
# ---------------------------------------------------------------------------

class ScoreDimension(str, Enum):
    """Dimensions on which agent output is evaluated."""
    CORRECTNESS = "correctness"          # Does the output actually solve the task?
    COMPLETENESS = "completeness"        # Are all requirements addressed?
    CODE_QUALITY = "code_quality"        # Clean, readable, maintainable?
    SECURITY = "security"                # No vulnerabilities introduced?
    EFFICIENCY = "efficiency"            # Reasonable performance characteristics?
    INSTRUCTION_FOLLOWING = "instruction_following"  # Did agent follow the prompt?


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""
    dimension: str
    score: float          # 0.0 to 1.0
    reasoning: str        # Why this score
    weight: float = 1.0   # Relative weight in overall score


@dataclass
class JudgeResult:
    """Complete evaluation result from LLM Judge."""
    job_id: str
    agent_key: str
    overall_score: float           # 0.0 to 1.0 (weighted average)
    confidence: float              # 0.0 to 1.0 (judge's self-assessed confidence)
    dimensions: List[DimensionScore] = field(default_factory=list)
    reasoning: str = ""            # Overall reasoning
    pass_threshold: float = 0.6    # Score needed to "pass"
    passed: bool = False
    eval_model: str = ""           # Which model did the judging
    eval_cost_usd: float = 0.0
    eval_duration_sec: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.passed = self.overall_score >= self.pass_threshold

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dimensions"] = [asdict(dim) for dim in self.dimensions]
        return d


# ---------------------------------------------------------------------------
# Rubrics — per agent type
# ---------------------------------------------------------------------------

RUBRICS: Dict[str, List[Dict[str, Any]]] = {
    "coder_agent": [
        {"dimension": "correctness", "weight": 3.0, "criteria": "Code compiles/runs without errors and produces correct output for the stated task"},
        {"dimension": "completeness", "weight": 2.0, "criteria": "All requirements from the task description are implemented"},
        {"dimension": "code_quality", "weight": 1.5, "criteria": "Clean variable names, proper error handling, no dead code, follows existing patterns"},
        {"dimension": "security", "weight": 1.5, "criteria": "No SQL injection, XSS, command injection, hardcoded secrets, or OWASP Top 10 issues"},
        {"dimension": "instruction_following", "weight": 2.0, "criteria": "Agent followed the task instructions exactly, didn't over-engineer or add unrequested features"},
    ],
    "elite_coder_agent": [
        {"dimension": "correctness", "weight": 3.0, "criteria": "Code solves the problem correctly, including edge cases and error paths"},
        {"dimension": "completeness", "weight": 2.5, "criteria": "All files affected by the change are updated consistently, no broken imports/interfaces"},
        {"dimension": "code_quality", "weight": 2.0, "criteria": "Architecture is sound, abstractions are appropriate, tests are included"},
        {"dimension": "security", "weight": 2.0, "criteria": "Security audit passes, no new vulnerabilities, auth/authz properly handled"},
        {"dimension": "efficiency", "weight": 1.5, "criteria": "No N+1 queries, reasonable algorithmic complexity, no obvious performance issues"},
    ],
    "database_agent": [
        {"dimension": "correctness", "weight": 3.0, "criteria": "SQL queries return correct results, JOINs are appropriate, no phantom duplicates"},
        {"dimension": "security", "weight": 3.0, "criteria": "RLS policies respected, no data leaks, parameterized queries used"},
        {"dimension": "completeness", "weight": 2.0, "criteria": "All requested data points returned, aggregations are correct"},
        {"dimension": "efficiency", "weight": 2.0, "criteria": "Queries use indexes, no full table scans on large tables, LIMIT applied"},
    ],
    "security_agent": [
        {"dimension": "correctness", "weight": 3.0, "criteria": "Vulnerabilities identified are real (not false positives), severity ratings are accurate"},
        {"dimension": "completeness", "weight": 2.5, "criteria": "All attack vectors analyzed, OWASP Top 10 covered, RLS policies checked"},
        {"dimension": "instruction_following", "weight": 2.0, "criteria": "Specific remediation steps provided, not just generic advice"},
    ],
    "researcher_agent": [
        {"dimension": "correctness", "weight": 2.5, "criteria": "Facts are accurate, citations are real and verifiable"},
        {"dimension": "completeness", "weight": 3.0, "criteria": "All sub-questions answered, contradictions flagged, confidence scores included"},
        {"dimension": "instruction_following", "weight": 2.0, "criteria": "Output format matches request, no opinions presented as facts"},
    ],
    # Default rubric for any agent type not listed
    "default": [
        {"dimension": "correctness", "weight": 3.0, "criteria": "Output correctly addresses the task requirements"},
        {"dimension": "completeness", "weight": 2.0, "criteria": "All parts of the task are addressed"},
        {"dimension": "instruction_following", "weight": 2.0, "criteria": "Agent followed instructions without adding unrequested changes"},
    ],
}

# Map agent router keys to rubric keys
AGENT_TO_RUBRIC = {
    "coder_agent": "coder_agent",
    "elite_coder_agent": "elite_coder_agent",
    "database_agent": "database_agent",
    "security_agent": "security_agent",
    "researcher_agent": "researcher_agent",
    "debugger_agent": "coder_agent",
    "test_agent": "coder_agent",
    "reviewer_agent": "coder_agent",
    "architect_agent": "elite_coder_agent",
    "content_agent": "researcher_agent",
    "finance_agent": "researcher_agent",
    "betting_agent": "default",
    "overseer_agent": "default",
}


# ---------------------------------------------------------------------------
# Judge Prompt Builder
# ---------------------------------------------------------------------------

def _build_judge_prompt(task: str, agent_output: str, rubric_items: List[dict]) -> str:
    """Build the structured prompt for the LLM judge."""
    rubric_text = ""
    for i, item in enumerate(rubric_items, 1):
        rubric_text += f"\n{i}. **{item['dimension']}** (weight: {item['weight']}x)\n"
        rubric_text += f"   Criteria: {item['criteria']}\n"

    return f"""You are an expert evaluator grading an AI agent's output. Be strict but fair.

## TASK GIVEN TO AGENT
{task[:2000]}

## AGENT'S OUTPUT
{agent_output[:4000]}

## EVALUATION RUBRIC
Score each dimension from 0.0 to 1.0:{rubric_text}

## INSTRUCTIONS
1. Evaluate each dimension independently
2. Provide specific reasoning (cite exact issues or strengths)
3. Be critical — a score of 0.8+ means genuinely excellent work
4. A score of 0.5 means significant issues found
5. A score below 0.3 means the output is largely incorrect or incomplete

## REQUIRED OUTPUT FORMAT (JSON only, no markdown)
{{
  "dimensions": [
    {{"dimension": "correctness", "score": 0.85, "reasoning": "..."}},
    {{"dimension": "completeness", "score": 0.70, "reasoning": "..."}}
  ],
  "overall_reasoning": "Brief summary of evaluation",
  "confidence": 0.8
}}"""


# ---------------------------------------------------------------------------
# LLMJudge
# ---------------------------------------------------------------------------

class LLMJudge:
    """LLM-based output quality evaluator.

    Evaluates agent outputs against rubrics using a cheap model (Kimi 2.5 default).
    Can be configured to use any model via call_model_fn.
    """

    def __init__(self, call_model_fn: Optional[Callable] = None,
                 default_model: str = "kimi-2.5",
                 pass_threshold: float = 0.6):
        """
        Args:
            call_model_fn: async function(system_prompt, user_message, model) -> str
                          If None, uses a simple fallback.
            default_model: Model to use for judging.
            pass_threshold: Minimum overall score to "pass".
        """
        self._call_model = call_model_fn
        self._default_model = default_model
        self._pass_threshold = pass_threshold
        logger.info(f"LLMJudge initialized (model={default_model}, threshold={pass_threshold})")

    def get_rubric(self, agent_key: str) -> List[dict]:
        """Get the evaluation rubric for an agent type."""
        rubric_key = AGENT_TO_RUBRIC.get(agent_key, "default")
        return RUBRICS.get(rubric_key, RUBRICS["default"])

    async def score_output(self, job_id: str, agent_key: str,
                           task_description: str, agent_output: str,
                           model: Optional[str] = None) -> JudgeResult:
        """Score an agent's output using LLM-as-Judge.

        Args:
            job_id: The job being evaluated.
            agent_key: Which agent produced the output.
            task_description: What was the agent asked to do.
            agent_output: What the agent produced.
            model: Override the default judge model.

        Returns:
            JudgeResult with dimension scores and overall rating.
        """
        start = time.perf_counter()
        rubric = self.get_rubric(agent_key)
        judge_prompt = _build_judge_prompt(task_description, agent_output, rubric)
        eval_model = model or self._default_model

        # Call the LLM for evaluation
        try:
            if self._call_model:
                raw_response = await self._call_model(
                    "You are a strict but fair code/output evaluator. Return ONLY valid JSON.",
                    judge_prompt,
                    eval_model,
                )
            else:
                # Fallback: heuristic scoring (no LLM available)
                return self._heuristic_score(job_id, agent_key, task_description, agent_output, rubric)

            # Parse structured response
            result = self._parse_judge_response(raw_response, job_id, agent_key, rubric)
            result.eval_model = eval_model
            result.eval_duration_sec = round(time.perf_counter() - start, 3)
            return result

        except Exception as e:
            logger.error(f"LLM Judge failed for job {job_id}: {e}")
            # Fallback to heuristic
            result = self._heuristic_score(job_id, agent_key, task_description, agent_output, rubric)
            result.eval_model = "heuristic_fallback"
            result.eval_duration_sec = round(time.perf_counter() - start, 3)
            return result

    def _parse_judge_response(self, raw: str, job_id: str, agent_key: str,
                              rubric: List[dict]) -> JudgeResult:
        """Parse the LLM's JSON response into a JudgeResult."""
        # Extract JSON from response (handle markdown code blocks)
        json_str = raw.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse judge JSON for job {job_id}, using defaults")
            return self._default_result(job_id, agent_key, rubric)

        # Build dimension scores
        dimensions = []
        rubric_weights = {item["dimension"]: item["weight"] for item in rubric}

        for dim_data in data.get("dimensions", []):
            dim_name = dim_data.get("dimension", "unknown")
            score = max(0.0, min(1.0, float(dim_data.get("score", 0.5))))
            weight = rubric_weights.get(dim_name, 1.0)
            dimensions.append(DimensionScore(
                dimension=dim_name,
                score=score,
                reasoning=dim_data.get("reasoning", ""),
                weight=weight,
            ))

        # Calculate weighted average
        if dimensions:
            total_weight = sum(d.weight for d in dimensions)
            overall = sum(d.score * d.weight for d in dimensions) / total_weight if total_weight > 0 else 0.5
        else:
            overall = 0.5

        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.7))))

        return JudgeResult(
            job_id=job_id,
            agent_key=agent_key,
            overall_score=round(overall, 3),
            confidence=confidence,
            dimensions=dimensions,
            reasoning=data.get("overall_reasoning", ""),
            pass_threshold=self._pass_threshold,
        )

    def _default_result(self, job_id: str, agent_key: str, rubric: List[dict]) -> JudgeResult:
        """Default result when parsing fails."""
        return JudgeResult(
            job_id=job_id,
            agent_key=agent_key,
            overall_score=0.5,
            confidence=0.3,
            reasoning="Could not parse judge response. Default score assigned.",
            pass_threshold=self._pass_threshold,
        )

    def _heuristic_score(self, job_id: str, agent_key: str,
                         task: str, output: str, rubric: List[dict]) -> JudgeResult:
        """Quick heuristic scoring when no LLM is available.

        Uses simple text analysis:
        - Output length relative to task complexity
        - Presence of error indicators
        - Code structure markers (functions, tests, etc.)
        """
        dimensions = []
        task_lower = task.lower()
        output_lower = output.lower()

        # Correctness heuristic: check for error indicators
        error_markers = ["error", "traceback", "exception", "failed", "cannot", "unable"]
        error_count = sum(1 for m in error_markers if m in output_lower)
        correctness = max(0.2, 1.0 - (error_count * 0.15))

        # Completeness heuristic: output length relative to task
        min_expected_length = max(50, len(task) * 0.5)
        completeness = min(1.0, len(output) / min_expected_length) if min_expected_length > 0 else 0.5

        # Code quality heuristic: structural markers
        quality_markers = ["def ", "class ", "import ", "return ", "function ", "const ", "export "]
        has_code = any(m in output for m in quality_markers)
        code_quality = 0.7 if has_code else 0.5

        rubric_map = {item["dimension"]: item["weight"] for item in rubric}

        for dim_name, weight in rubric_map.items():
            if dim_name == "correctness":
                score = correctness
            elif dim_name == "completeness":
                score = completeness
            elif dim_name == "code_quality":
                score = code_quality
            else:
                score = 0.6  # Default for dimensions we can't heuristically check
            dimensions.append(DimensionScore(
                dimension=dim_name,
                score=round(score, 2),
                reasoning="Heuristic evaluation (no LLM available)",
                weight=weight,
            ))

        total_weight = sum(d.weight for d in dimensions)
        overall = sum(d.score * d.weight for d in dimensions) / total_weight if total_weight > 0 else 0.5

        return JudgeResult(
            job_id=job_id,
            agent_key=agent_key,
            overall_score=round(overall, 3),
            confidence=0.3,  # Low confidence for heuristic
            dimensions=dimensions,
            reasoning="Heuristic evaluation (LLM judge not available)",
            pass_threshold=self._pass_threshold,
            eval_model="heuristic",
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_judge: Optional[LLMJudge] = None


def get_judge() -> LLMJudge:
    """Get the global LLMJudge instance."""
    global _judge
    if _judge is None:
        _judge = LLMJudge()
    return _judge


def init_judge(call_model_fn: Optional[Callable] = None, **kwargs) -> LLMJudge:
    """Initialize the global LLMJudge with a model calling function."""
    global _judge
    _judge = LLMJudge(call_model_fn=call_model_fn, **kwargs)
    return _judge
