"""
Review Cycle Engine for OpenClaw — Agent-to-Agent Multi-Turn Collaboration

Enables structured review cycles where agents produce work, review each other's
output, and iterate until quality thresholds are met or escalation occurs.

Cycle types:
  - code_review:    coder_agent → hacker_agent → coder_agent revises → PM approves
  - security_audit: hacker_agent audits → elite_coder fixes → hacker_agent re-checks
  - full_review:    coder → hacker (security) → elite_coder (architecture) → PM approval
  - quick_review:   coder → PM reviews → done

Usage:
    from review_cycle import ReviewCycleEngine

    engine = ReviewCycleEngine(call_agent_fn=gateway.call_model_for_agent)
    review_id = await engine.start_review("code_review", code_content, "coder_agent")
    status = engine.get_review_status(review_id)
"""

import json
import os
import logging
import uuid
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Callable, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum

logger = logging.getLogger("openclaw.review_cycle")

# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------

class CycleType(str, Enum):
    CODE_REVIEW = "code_review"
    SECURITY_AUDIT = "security_audit"
    FULL_REVIEW = "full_review"
    QUICK_REVIEW = "quick_review"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVISION = "revision"
    APPROVED = "approved"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ReviewIssue:
    line: Optional[int]
    severity: str
    description: str
    suggestion: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewFeedback:
    approved: bool
    issues: List[ReviewIssue]
    summary: str
    quality_score: int  # 1-10
    reviewer_agent: str
    round_number: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_response: str = ""
    cost_tokens: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issues"] = [i.to_dict() if isinstance(i, ReviewIssue) else i for i in self.issues]
        return d


@dataclass
class RevisionRecord:
    round_number: int
    author_agent: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issues_addressed: int = 0
    cost_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewCycle:
    review_id: str
    cycle_type: str
    status: str
    author_agent: str
    reviewer_agents: List[str]
    original_content: str
    current_content: str
    current_round: int
    max_rounds: int
    feedbacks: List[ReviewFeedback]
    revisions: List[RevisionRecord]
    conversation_thread: List[Dict[str, str]]
    quality_scores: List[int]
    created_at: str
    updated_at: str
    total_cost_tokens: int = 0
    escalation_reason: str = ""
    current_reviewer_index: int = 0

    def to_dict(self) -> dict:
        d = {
            "review_id": self.review_id,
            "cycle_type": self.cycle_type,
            "status": self.status,
            "author_agent": self.author_agent,
            "reviewer_agents": self.reviewer_agents,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "quality_scores": self.quality_scores,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_cost_tokens": self.total_cost_tokens,
            "escalation_reason": self.escalation_reason,
            "current_reviewer_index": self.current_reviewer_index,
            "feedbacks": [f.to_dict() for f in self.feedbacks],
            "revisions": [r.to_dict() for r in self.revisions],
            "conversation_thread_length": len(self.conversation_thread),
            "content_length": len(self.current_content),
        }
        return d


# ---------------------------------------------------------------------------
# Cycle Definitions — which agents participate and in what order
# ---------------------------------------------------------------------------

CYCLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    CycleType.CODE_REVIEW: {
        "author": "coder_agent",
        "reviewers": ["hacker_agent"],
        "final_approver": "project_manager",
        "description": "Code written by coder, security-reviewed by hacker, PM final approval",
    },
    CycleType.SECURITY_AUDIT: {
        "author": "hacker_agent",
        "reviewers": ["elite_coder"],
        "final_approver": "hacker_agent",
        "description": "Hacker audits, elite_coder fixes vulnerabilities, hacker re-checks",
    },
    CycleType.FULL_REVIEW: {
        "author": "coder_agent",
        "reviewers": ["hacker_agent", "elite_coder"],
        "final_approver": "project_manager",
        "description": "Full pipeline: coder writes, hacker reviews security, elite reviews architecture, PM approves",
    },
    CycleType.QUICK_REVIEW: {
        "author": "coder_agent",
        "reviewers": ["project_manager"],
        "final_approver": None,
        "description": "Fast path: coder writes, PM reviews, done",
    },
}

# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

REVIEW_PROMPT = """You are acting as a code reviewer for the OpenClaw platform.

Review the following {review_context} carefully and return your assessment as a JSON object.

## Content to Review

```
{content}
```

{previous_feedback_section}

## Instructions

Analyze the content for:
- Security vulnerabilities (SQL injection, XSS, auth bypass, etc.)
- Logic errors and edge cases
- Code quality and maintainability
- Performance concerns
- Best practice violations

Return ONLY a valid JSON object in this exact format (no markdown fences, no extra text):

{{
  "approved": false,
  "issues": [
    {{"line": 42, "severity": "high", "description": "SQL injection in user input", "suggestion": "Use parameterized queries"}}
  ],
  "summary": "2 critical issues found, 1 minor style issue",
  "quality_score": 6
}}

Rules:
- "approved" must be true or false
- "quality_score" is 1-10 (10 = perfect)
- "severity" must be one of: "low", "medium", "high", "critical"
- If there are no issues, set "approved": true, "issues": [], and quality_score >= 8
- Be thorough but fair — do not invent issues that are not present
- "line" can be null if the issue is not line-specific
"""

REVISION_PROMPT = """You are the author who wrote the following code/content. A reviewer has found issues that need fixing.

## Your Original Content

```
{content}
```

## Reviewer Feedback (Round {round_number})

{feedback_json}

## Instructions

Fix ALL issues listed above. For each issue:
1. Apply the suggested fix (or a better alternative if you have one)
2. Ensure the fix does not introduce new problems

Return the COMPLETE revised content. Do not omit any parts — return the full updated version.
After the content, add a brief summary line starting with "FIXES APPLIED:" listing what you changed.
"""

FINAL_APPROVAL_PROMPT = """You are the project manager performing final approval on reviewed content.

## Content (after {round_count} review rounds)

```
{content}
```

## Review History

{review_history}

## Instructions

Decide whether this content is ready for production. Consider:
- Were all critical and high-severity issues addressed?
- Is the overall quality acceptable (score >= 7)?
- Are there any remaining concerns?

Return ONLY a valid JSON object:

{{
  "approved": true,
  "issues": [],
  "summary": "All issues resolved. Ready for production.",
  "quality_score": 9
}}

Set "approved": true only if you are confident the content is production-ready.
"""

# ---------------------------------------------------------------------------
# Review Cycle Engine
# ---------------------------------------------------------------------------

class ReviewCycleEngine:
    """
    Multi-turn agent-to-agent review cycle engine.

    Orchestrates structured review cycles where one agent produces work,
    another reviews it, and the author revises until approved or escalated.

    Args:
        call_agent_fn: Callable that calls an agent. Signature:
            call_agent_fn(agent_key: str, prompt: str, conversation: list) -> tuple[str, int]
            Returns (response_text, token_count).
        max_rounds: Default maximum revision rounds before escalation.
        persist_dir: Directory to persist review state (optional).
    """

    def __init__(
        self,
        call_agent_fn: Callable[[str, str, list], Tuple[str, int]],
        max_rounds: int = 3,
        persist_dir: Optional[str] = None,
    ):
        self._call_agent = call_agent_fn
        self._max_rounds = max_rounds
        self._persist_dir = persist_dir
        self._reviews: Dict[str, ReviewCycle] = {}

        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)
            self._load_persisted_reviews()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_review(
        self,
        work_type: str,
        content: str,
        author_agent: Optional[str] = None,
        reviewer_agents: Optional[List[str]] = None,
        max_rounds: Optional[int] = None,
    ) -> str:
        """
        Start a new review cycle.

        Args:
            work_type: One of code_review, security_audit, full_review, quick_review.
            content: The content to be reviewed.
            author_agent: Override the default author agent for this cycle type.
            reviewer_agents: Override the default reviewer agents.
            max_rounds: Override the default max rounds.

        Returns:
            review_id: Unique identifier for this review cycle.
        """
        if work_type not in [ct.value for ct in CycleType]:
            raise ValueError(f"Unknown cycle type: {work_type}. Must be one of: {[ct.value for ct in CycleType]}")

        definition = CYCLE_DEFINITIONS[work_type]
        author = author_agent or definition["author"]
        reviewers = reviewer_agents or definition["reviewers"]
        rounds = max_rounds or self._max_rounds

        review_id = f"rev_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        cycle = ReviewCycle(
            review_id=review_id,
            cycle_type=work_type,
            status=ReviewStatus.IN_PROGRESS,
            author_agent=author,
            reviewer_agents=reviewers,
            original_content=content,
            current_content=content,
            current_round=1,
            max_rounds=rounds,
            feedbacks=[],
            revisions=[],
            conversation_thread=[
                {"role": "system", "content": f"Review cycle {review_id} started. Type: {work_type}. Author: {author}. Reviewers: {', '.join(reviewers)}."},
                {"role": "user", "content": f"Original content submitted for review:\n\n{content[:2000]}{'...[truncated]' if len(content) > 2000 else ''}"},
            ],
            quality_scores=[],
            created_at=now,
            updated_at=now,
        )

        self._reviews[review_id] = cycle
        logger.info("Review cycle %s started: type=%s author=%s reviewers=%s", review_id, work_type, author, reviewers)

        # Run the review loop
        await self._run_review_loop(cycle)

        return review_id

    def get_review_status(self, review_id: str) -> Dict[str, Any]:
        """Get the current status of a review cycle."""
        cycle = self._reviews.get(review_id)
        if not cycle:
            return {"error": f"Review {review_id} not found"}

        result = cycle.to_dict()

        # Add quality trend
        if len(cycle.quality_scores) >= 2:
            result["quality_trend"] = cycle.quality_scores[-1] - cycle.quality_scores[0]
            result["issues_per_round"] = [
                len(f.issues) for f in cycle.feedbacks
            ]
        else:
            result["quality_trend"] = 0
            result["issues_per_round"] = [len(f.issues) for f in cycle.feedbacks]

        return result

    def list_active_reviews(self) -> List[Dict[str, Any]]:
        """List all in-progress review cycles."""
        active = []
        for cycle in self._reviews.values():
            if cycle.status in (ReviewStatus.IN_PROGRESS, ReviewStatus.REVISION, ReviewStatus.PENDING):
                active.append({
                    "review_id": cycle.review_id,
                    "cycle_type": cycle.cycle_type,
                    "status": cycle.status,
                    "author_agent": cycle.author_agent,
                    "current_round": cycle.current_round,
                    "max_rounds": cycle.max_rounds,
                    "quality_scores": cycle.quality_scores,
                    "created_at": cycle.created_at,
                })
        return active

    def list_all_reviews(self) -> List[Dict[str, Any]]:
        """List all review cycles (active and completed)."""
        return [cycle.to_dict() for cycle in self._reviews.values()]

    def cancel_review(self, review_id: str) -> Dict[str, Any]:
        """Cancel an active review cycle."""
        cycle = self._reviews.get(review_id)
        if not cycle:
            return {"error": f"Review {review_id} not found"}

        if cycle.status in (ReviewStatus.APPROVED, ReviewStatus.CANCELLED):
            return {"error": f"Review {review_id} already in terminal state: {cycle.status}"}

        cycle.status = ReviewStatus.CANCELLED
        cycle.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist_review(cycle)

        logger.info("Review cycle %s cancelled at round %d", review_id, cycle.current_round)
        return {
            "review_id": review_id,
            "status": "cancelled",
            "rounds_completed": cycle.current_round,
            "total_cost_tokens": cycle.total_cost_tokens,
        }

    def get_review_content(self, review_id: str) -> Optional[str]:
        """Get the current (latest revised) content of a review cycle."""
        cycle = self._reviews.get(review_id)
        if not cycle:
            return None
        return cycle.current_content

    def get_review_thread(self, review_id: str) -> Optional[List[Dict[str, str]]]:
        """Get the full conversation thread for a review cycle."""
        cycle = self._reviews.get(review_id)
        if not cycle:
            return None
        return list(cycle.conversation_thread)

    # ------------------------------------------------------------------
    # Core Review Loop
    # ------------------------------------------------------------------

    async def _run_review_loop(self, cycle: ReviewCycle) -> None:
        """Execute the full review loop: review → revise → repeat."""
        try:
            while cycle.current_round <= cycle.max_rounds:
                if cycle.status == ReviewStatus.CANCELLED:
                    return

                # Step through each reviewer in sequence
                all_approved = True
                for idx in range(cycle.current_reviewer_index, len(cycle.reviewer_agents)):
                    cycle.current_reviewer_index = idx
                    reviewer = cycle.reviewer_agents[idx]

                    # Get review from this reviewer
                    feedback = await self._get_review(cycle, reviewer)
                    cycle.feedbacks.append(feedback)
                    cycle.quality_scores.append(feedback.quality_score)
                    cycle.total_cost_tokens += feedback.cost_tokens
                    cycle.updated_at = datetime.now(timezone.utc).isoformat()

                    # Add to conversation thread
                    cycle.conversation_thread.append({
                        "role": "assistant",
                        "content": f"[{reviewer} review, round {cycle.current_round}] {feedback.summary} (score: {feedback.quality_score}/10, approved: {feedback.approved})",
                    })

                    if not feedback.approved:
                        all_approved = False
                        # Author revises based on feedback
                        cycle.status = ReviewStatus.REVISION
                        revision = await self._get_revision(cycle, feedback)
                        cycle.revisions.append(revision)
                        cycle.current_content = revision.content
                        cycle.total_cost_tokens += revision.cost_tokens
                        cycle.updated_at = datetime.now(timezone.utc).isoformat()

                        cycle.conversation_thread.append({
                            "role": "user",
                            "content": f"[{cycle.author_agent} revision, round {cycle.current_round}] Addressed {revision.issues_addressed} issues.",
                        })

                        logger.info(
                            "Review %s round %d: %s found %d issues, %s revised (%d fixed)",
                            cycle.review_id, cycle.current_round, reviewer,
                            len(feedback.issues), cycle.author_agent, revision.issues_addressed,
                        )
                        # After revision, restart reviewers from the beginning for this round
                        break
                    else:
                        logger.info(
                            "Review %s round %d: %s approved (score %d/10)",
                            cycle.review_id, cycle.current_round, reviewer, feedback.quality_score,
                        )

                if all_approved:
                    # All reviewers approved — proceed to final approval if configured
                    definition = CYCLE_DEFINITIONS.get(cycle.cycle_type, {})
                    final_approver = definition.get("final_approver")

                    if final_approver and final_approver not in cycle.reviewer_agents:
                        final_feedback = await self._get_final_approval(cycle, final_approver)
                        cycle.feedbacks.append(final_feedback)
                        cycle.quality_scores.append(final_feedback.quality_score)
                        cycle.total_cost_tokens += final_feedback.cost_tokens

                        if final_feedback.approved:
                            cycle.status = ReviewStatus.APPROVED
                            logger.info("Review %s APPROVED by %s (final score %d/10)", cycle.review_id, final_approver, final_feedback.quality_score)
                        else:
                            # Final approver rejected — one more revision round
                            cycle.status = ReviewStatus.REVISION
                            revision = await self._get_revision(cycle, final_feedback)
                            cycle.revisions.append(revision)
                            cycle.current_content = revision.content
                            cycle.total_cost_tokens += revision.cost_tokens
                            cycle.current_round += 1
                            cycle.current_reviewer_index = 0
                            logger.info("Review %s: final approver %s rejected, round %d", cycle.review_id, final_approver, cycle.current_round)
                            continue
                    else:
                        cycle.status = ReviewStatus.APPROVED
                        logger.info("Review %s APPROVED by all reviewers (final score %d/10)", cycle.review_id, cycle.quality_scores[-1])

                    self._persist_review(cycle)
                    return
                else:
                    # Not all approved, increment round and reset reviewer index
                    cycle.current_round += 1
                    cycle.current_reviewer_index = 0
                    cycle.status = ReviewStatus.IN_PROGRESS

            # Max rounds exceeded — escalate to PM
            cycle.status = ReviewStatus.ESCALATED
            cycle.escalation_reason = (
                f"Maximum {cycle.max_rounds} revision rounds reached without full approval. "
                f"Last quality score: {cycle.quality_scores[-1] if cycle.quality_scores else 'N/A'}. "
                f"Remaining issues: {len(cycle.feedbacks[-1].issues) if cycle.feedbacks else 0}."
            )
            logger.warning("Review %s ESCALATED after %d rounds", cycle.review_id, cycle.max_rounds)
            self._persist_review(cycle)

        except Exception as e:
            cycle.status = ReviewStatus.FAILED
            cycle.escalation_reason = f"Error during review: {str(e)}"
            cycle.updated_at = datetime.now(timezone.utc).isoformat()
            self._persist_review(cycle)
            logger.exception("Review %s FAILED: %s", cycle.review_id, e)
            raise

    # ------------------------------------------------------------------
    # Agent Interaction — Review
    # ------------------------------------------------------------------

    async def _get_review(self, cycle: ReviewCycle, reviewer: str) -> ReviewFeedback:
        """Ask a reviewer agent to review the current content."""
        # Build previous feedback section if this is not the first round
        previous_section = ""
        reviewer_feedbacks = [f for f in cycle.feedbacks if f.reviewer_agent == reviewer]
        if reviewer_feedbacks:
            last = reviewer_feedbacks[-1]
            previous_section = (
                f"\n## Previous Review Feedback (Round {last.round_number})\n\n"
                f"You previously reviewed this content and found {len(last.issues)} issues "
                f"(quality score: {last.quality_score}/10). The author has revised the content. "
                f"Check whether the issues were fixed and look for any new problems.\n\n"
                f"Previous issues:\n{json.dumps([i.to_dict() if isinstance(i, ReviewIssue) else i for i in last.issues], indent=2)}\n"
            )

        review_context = {
            CycleType.CODE_REVIEW: "code for security vulnerabilities and quality",
            CycleType.SECURITY_AUDIT: "code for security vulnerabilities, attack vectors, and hardening",
            CycleType.FULL_REVIEW: "code for security, architecture, and production readiness",
            CycleType.QUICK_REVIEW: "code for correctness and basic quality",
        }.get(cycle.cycle_type, "content")

        prompt = REVIEW_PROMPT.format(
            review_context=review_context,
            content=cycle.current_content,
            previous_feedback_section=previous_section,
        )

        response_text, tokens = self._call_agent(reviewer, prompt, list(cycle.conversation_thread))

        # Parse the JSON response
        feedback_data = self._parse_review_response(response_text)

        issues = [
            ReviewIssue(
                line=iss.get("line"),
                severity=iss.get("severity", "medium"),
                description=iss.get("description", "No description"),
                suggestion=iss.get("suggestion", ""),
            )
            for iss in feedback_data.get("issues", [])
        ]

        return ReviewFeedback(
            approved=feedback_data.get("approved", False),
            issues=issues,
            summary=feedback_data.get("summary", "No summary provided"),
            quality_score=min(10, max(1, int(feedback_data.get("quality_score", 5)))),
            reviewer_agent=reviewer,
            round_number=cycle.current_round,
            raw_response=response_text,
            cost_tokens=tokens,
        )

    # ------------------------------------------------------------------
    # Agent Interaction — Revision
    # ------------------------------------------------------------------

    async def _get_revision(self, cycle: ReviewCycle, feedback: ReviewFeedback) -> RevisionRecord:
        """Ask the author agent to revise content based on reviewer feedback."""
        feedback_json = json.dumps(feedback.to_dict(), indent=2)

        prompt = REVISION_PROMPT.format(
            content=cycle.current_content,
            round_number=cycle.current_round,
            feedback_json=feedback_json,
        )

        response_text, tokens = self._call_agent(
            cycle.author_agent, prompt, list(cycle.conversation_thread)
        )

        # Extract revised content (everything before FIXES APPLIED line, or the whole response)
        revised_content = response_text
        issues_addressed = len(feedback.issues)  # optimistic count

        if "FIXES APPLIED:" in response_text:
            parts = response_text.rsplit("FIXES APPLIED:", 1)
            revised_content = parts[0].rstrip()
            fixes_line = parts[1].strip()
            # Count comma-separated fixes as a rough heuristic
            mentioned_fixes = [f.strip() for f in fixes_line.split(",") if f.strip()]
            if mentioned_fixes:
                issues_addressed = len(mentioned_fixes)

        # Strip markdown code fences if the agent wrapped the response
        revised_content = self._strip_code_fences(revised_content)

        return RevisionRecord(
            round_number=cycle.current_round,
            author_agent=cycle.author_agent,
            content=revised_content,
            issues_addressed=min(issues_addressed, len(feedback.issues)),
            cost_tokens=tokens,
        )

    # ------------------------------------------------------------------
    # Agent Interaction — Final Approval
    # ------------------------------------------------------------------

    async def _get_final_approval(self, cycle: ReviewCycle, approver: str) -> ReviewFeedback:
        """Ask the final approver to give the last sign-off."""
        review_history_lines = []
        for fb in cycle.feedbacks:
            review_history_lines.append(
                f"- Round {fb.round_number} by {fb.reviewer_agent}: "
                f"score={fb.quality_score}/10, approved={fb.approved}, "
                f"issues={len(fb.issues)} — {fb.summary}"
            )

        prompt = FINAL_APPROVAL_PROMPT.format(
            round_count=cycle.current_round,
            content=cycle.current_content,
            review_history="\n".join(review_history_lines) or "No prior reviews.",
        )

        response_text, tokens = self._call_agent(approver, prompt, list(cycle.conversation_thread))
        feedback_data = self._parse_review_response(response_text)

        issues = [
            ReviewIssue(
                line=iss.get("line"),
                severity=iss.get("severity", "medium"),
                description=iss.get("description", ""),
                suggestion=iss.get("suggestion", ""),
            )
            for iss in feedback_data.get("issues", [])
        ]

        return ReviewFeedback(
            approved=feedback_data.get("approved", False),
            issues=issues,
            summary=feedback_data.get("summary", "Final review complete"),
            quality_score=min(10, max(1, int(feedback_data.get("quality_score", 5)))),
            reviewer_agent=approver,
            round_number=cycle.current_round,
            raw_response=response_text,
            cost_tokens=tokens,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_review_response(self, response: str) -> dict:
        """
        Extract a JSON object from the agent response.

        Handles common cases: raw JSON, JSON inside markdown fences,
        JSON preceded/followed by extra text.
        """
        text = response.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences
        text = self._strip_code_fences(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find the first { ... } block
        start = text.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break

        # Fallback: return a conservative non-approved response
        logger.warning("Could not parse review JSON from agent response, returning fallback")
        return {
            "approved": False,
            "issues": [{"line": None, "severity": "medium", "description": "Unparseable review response — manual review required", "suggestion": ""}],
            "summary": "Agent response could not be parsed as structured feedback",
            "quality_score": 5,
        }

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences (```json ... ``` or ``` ... ```)."""
        stripped = text.strip()
        if stripped.startswith("```"):
            # Remove opening fence (possibly with language tag)
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1:]
            # Remove closing fence
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3].rstrip()
        return stripped

    def _persist_review(self, cycle: ReviewCycle) -> None:
        """Persist review state to disk if persist_dir is configured."""
        if not self._persist_dir:
            return
        try:
            filepath = os.path.join(self._persist_dir, f"{cycle.review_id}.json")
            data = cycle.to_dict()
            # Include full content for persistence
            data["current_content"] = cycle.current_content
            data["original_content"] = cycle.original_content
            data["conversation_thread"] = cycle.conversation_thread
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to persist review %s: %s", cycle.review_id, e)

    def _load_persisted_reviews(self) -> None:
        """Load previously persisted review states from disk."""
        if not self._persist_dir or not os.path.isdir(self._persist_dir):
            return
        count = 0
        for fname in os.listdir(self._persist_dir):
            if not fname.startswith("rev_") or not fname.endswith(".json"):
                continue
            try:
                filepath = os.path.join(self._persist_dir, fname)
                with open(filepath) as f:
                    data = json.load(f)
                # Reconstruct feedbacks
                feedbacks = []
                for fd in data.get("feedbacks", []):
                    issues = [ReviewIssue(**iss) for iss in fd.get("issues", [])]
                    feedbacks.append(ReviewFeedback(
                        approved=fd["approved"],
                        issues=issues,
                        summary=fd["summary"],
                        quality_score=fd["quality_score"],
                        reviewer_agent=fd["reviewer_agent"],
                        round_number=fd["round_number"],
                        timestamp=fd.get("timestamp", ""),
                        raw_response=fd.get("raw_response", ""),
                        cost_tokens=fd.get("cost_tokens", 0),
                    ))
                # Reconstruct revisions
                revisions = [RevisionRecord(**rv) for rv in data.get("revisions", [])]

                cycle = ReviewCycle(
                    review_id=data["review_id"],
                    cycle_type=data["cycle_type"],
                    status=data["status"],
                    author_agent=data["author_agent"],
                    reviewer_agents=data["reviewer_agents"],
                    original_content=data.get("original_content", ""),
                    current_content=data.get("current_content", ""),
                    current_round=data["current_round"],
                    max_rounds=data["max_rounds"],
                    feedbacks=feedbacks,
                    revisions=revisions,
                    conversation_thread=data.get("conversation_thread", []),
                    quality_scores=data.get("quality_scores", []),
                    created_at=data["created_at"],
                    updated_at=data["updated_at"],
                    total_cost_tokens=data.get("total_cost_tokens", 0),
                    escalation_reason=data.get("escalation_reason", ""),
                    current_reviewer_index=data.get("current_reviewer_index", 0),
                )
                self._reviews[cycle.review_id] = cycle
                count += 1
            except Exception as e:
                logger.warning("Failed to load persisted review %s: %s", fname, e)
        if count:
            logger.info("Loaded %d persisted review cycles from %s", count, self._persist_dir)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics across all review cycles."""
        total = len(self._reviews)
        if total == 0:
            return {"total_reviews": 0}

        by_status = {}
        by_type = {}
        total_rounds = 0
        total_tokens = 0
        quality_improvements = []

        for cycle in self._reviews.values():
            by_status[cycle.status] = by_status.get(cycle.status, 0) + 1
            by_type[cycle.cycle_type] = by_type.get(cycle.cycle_type, 0) + 1
            total_rounds += cycle.current_round
            total_tokens += cycle.total_cost_tokens

            if len(cycle.quality_scores) >= 2:
                quality_improvements.append(cycle.quality_scores[-1] - cycle.quality_scores[0])

        return {
            "total_reviews": total,
            "by_status": by_status,
            "by_type": by_type,
            "avg_rounds": round(total_rounds / total, 1) if total else 0,
            "total_tokens": total_tokens,
            "avg_quality_improvement": round(sum(quality_improvements) / len(quality_improvements), 1) if quality_improvements else 0,
            "approval_rate": round(by_status.get(ReviewStatus.APPROVED, 0) / total * 100, 1) if total else 0,
        }


# ---------------------------------------------------------------------------
# Convenience: synchronous wrapper for environments without async
# ---------------------------------------------------------------------------

def run_review_sync(
    engine: ReviewCycleEngine,
    work_type: str,
    content: str,
    author_agent: Optional[str] = None,
    reviewer_agents: Optional[List[str]] = None,
    max_rounds: Optional[int] = None,
) -> str:
    """
    Synchronous wrapper to run a review cycle.
    Uses asyncio.run() under the hood.
    """
    import asyncio
    return asyncio.run(engine.start_review(
        work_type=work_type,
        content=content,
        author_agent=author_agent,
        reviewer_agents=reviewer_agents,
        max_rounds=max_rounds,
    ))


# ---------------------------------------------------------------------------
# Self-test on import
# ---------------------------------------------------------------------------

def _self_test():
    """Verify the module loads and basic structures work."""
    # Enum checks
    assert CycleType.CODE_REVIEW == "code_review"
    assert ReviewStatus.APPROVED == "approved"

    # Data class checks
    issue = ReviewIssue(line=10, severity="high", description="test", suggestion="fix it")
    assert issue.to_dict()["line"] == 10

    feedback = ReviewFeedback(
        approved=False, issues=[issue], summary="test",
        quality_score=5, reviewer_agent="hacker_agent", round_number=1,
    )
    d = feedback.to_dict()
    assert d["approved"] is False
    assert len(d["issues"]) == 1

    # Cycle definitions check
    for ct in CycleType:
        assert ct.value in CYCLE_DEFINITIONS, f"Missing definition for {ct.value}"

    # JSON parsing check
    def mock_call(agent, prompt, conv):
        return ('{"approved": true, "issues": [], "summary": "ok", "quality_score": 9}', 100)

    engine = ReviewCycleEngine(call_agent_fn=mock_call)

    # Test parse
    result = engine._parse_review_response('```json\n{"approved": true, "issues": [], "summary": "ok", "quality_score": 9}\n```')
    assert result["approved"] is True

    result = engine._parse_review_response('Some preamble\n{"approved": false, "issues": [], "summary": "bad", "quality_score": 3}\nSome postamble')
    assert result["approved"] is False

    # Strip code fences
    assert ReviewCycleEngine._strip_code_fences("```python\nprint('hi')\n```") == "print('hi')"

    # Stats on empty engine
    stats = engine.get_stats()
    assert stats["total_reviews"] == 0

    # Cancel non-existent
    assert "error" in engine.cancel_review("nonexistent")

    # List active (empty)
    assert engine.list_active_reviews() == []

    logger.info("review_cycle.py self-test PASSED")


_self_test()
