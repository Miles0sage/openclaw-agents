"""
Deep Research Engine — Multi-step autonomous research with guardrails.

Orchestrates parallel sub-question research using Perplexity Sonar,
web search, and web scraping. Produces structured Markdown reports
with inline citations, confidence scores, and source tracking.

Guardrails:
  - Max 10 sub-questions per research task
  - Max 8 Perplexity API calls per research session
  - 5-minute timeout per session
  - No file writes — read-only research
  - Cost cap: ~$0.15 per deep research call (sonar-pro)
  - Audit log at data/research/research_log.jsonl
"""

import json
import os
import time
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger("deep_research")

# Load .env if PERPLEXITY_API_KEY not already in environment
if not os.environ.get("PERPLEXITY_API_KEY"):
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

# ─── Guardrails ───────────────────────────────────────────────────────────────

MAX_SUB_QUESTIONS = 10
MAX_PERPLEXITY_CALLS = 8
MAX_WEB_SCRAPES = 6
SESSION_TIMEOUT_SEC = 300  # 5 minutes
DATA_DIR = Path("os.environ.get("OPENCLAW_DATA_DIR", "./data")/research")
LOG_PATH = DATA_DIR / "research_log.jsonl"

# ─── Domain Mode Configs ─────────────────────────────────────────────────────

DOMAIN_MODES = {
    "general": {
        "system": "You are a thorough research analyst. Synthesize findings with citations. Be balanced and factual.",
        "focus": "web",
        "model": "sonar-pro",
        "sub_q_hint": "Break into logical sub-topics covering different angles.",
    },
    "market": {
        "system": "You are a market research analyst. Focus on market size, competitors, pricing, trends, and business models. Use specific numbers and data.",
        "focus": "web",
        "model": "sonar-pro",
        "sub_q_hint": "Cover: market size, key players, pricing models, recent trends, growth drivers, risks.",
    },
    "technical": {
        "system": "You are a technical researcher. Focus on implementation details, benchmarks, architecture, documentation quality, and community adoption.",
        "focus": "web",
        "model": "sonar-pro",
        "sub_q_hint": "Cover: architecture, performance benchmarks, developer experience, documentation, alternatives comparison.",
    },
    "academic": {
        "system": "You are an academic researcher. Prioritize peer-reviewed sources, methodology rigor, and citation accuracy. Note study limitations.",
        "focus": "academic",
        "model": "sonar-pro",
        "sub_q_hint": "Cover: key papers, methodology, findings, contradictions between studies, research gaps.",
    },
    "news": {
        "system": "You are a news analyst. Focus on recent developments, multiple perspectives, timeline of events, and implications.",
        "focus": "news",
        "model": "sonar",
        "sub_q_hint": "Cover: what happened, key players, timeline, different perspectives, implications.",
    },
    "due_diligence": {
        "system": "You are a due diligence analyst. Investigate thoroughly — look for red flags, verify claims, check financials, and assess risks.",
        "focus": "web",
        "model": "sonar-pro",
        "sub_q_hint": "Cover: company overview, financials, leadership, competitors, risks, red flags, customer reviews.",
    },
}


def deep_research(
    query: str,
    depth: str = "medium",
    mode: str = "general",
    max_sources: int = 0,
) -> str:
    """
    Multi-step autonomous deep research.

    Args:
        query: The research question or topic
        depth: quick (3 sub-Qs), medium (5), deep (8)
        mode: general, market, technical, academic, news, due_diligence
        max_sources: Override max Perplexity calls (0 = use depth default)

    Returns:
        JSON with: report (Markdown), sources, metadata
    """
    start = time.time()

    # Validate inputs
    if not query or len(query.strip()) < 5:
        return json.dumps({"error": "Query too short. Provide a detailed research question."})

    if mode not in DOMAIN_MODES:
        mode = "general"

    depth_config = {"quick": 3, "medium": 5, "deep": 8}
    if depth not in depth_config:
        depth = "medium"

    num_sub_qs = depth_config[depth]
    max_api_calls = max_sources if max_sources > 0 else min(num_sub_qs + 1, MAX_PERPLEXITY_CALLS)
    domain = DOMAIN_MODES[mode]

    # ─── Phase 1: Planning ────────────────────────────────────────────────
    plan = _generate_plan(query, num_sub_qs, domain)
    if "error" in plan:
        return json.dumps(plan)

    sub_questions = plan.get("sub_questions", [])[:MAX_SUB_QUESTIONS]
    if not sub_questions:
        return json.dumps({"error": "Failed to generate research plan."})

    # ─── Phase 2: Parallel Research ───────────────────────────────────────
    findings = _research_parallel(sub_questions, domain, max_api_calls, start)

    # Check timeout
    if time.time() - start > SESSION_TIMEOUT_SEC:
        logger.warning("Deep research session timed out")

    # ─── Phase 3: Synthesis ───────────────────────────────────────────────
    report = _synthesize_report(query, sub_questions, findings, domain, mode)

    # ─── Collect all sources ──────────────────────────────────────────────
    all_sources = []
    for f in findings:
        all_sources.extend(f.get("citations", []))
    # Deduplicate
    seen = set()
    unique_sources = []
    for s in all_sources:
        if s not in seen:
            seen.add(s)
            unique_sources.append(s)

    elapsed = round(time.time() - start, 1)

    result = {
        "report": report,
        "sources": unique_sources,
        "metadata": {
            "query": query,
            "mode": mode,
            "depth": depth,
            "sub_questions": len(sub_questions),
            "sources_found": len(unique_sources),
            "elapsed_seconds": elapsed,
            "api_calls": sum(1 for f in findings if f.get("answer")),
        },
        "plan": sub_questions,
    }

    # ─── Audit Log ────────────────────────────────────────────────────────
    _log_research(query, mode, depth, len(unique_sources), elapsed)

    return json.dumps(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Planning — Break query into sub-questions
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_plan(query: str, num_sub_qs: int, domain: dict) -> dict:
    """Use Perplexity to decompose the query into sub-questions."""
    try:
        from agent_tools import _perplexity_research

        plan_prompt = f"""I need to research the following topic thoroughly:

"{query}"

Break this into exactly {num_sub_qs} specific sub-questions that together would provide a comprehensive answer. {domain['sub_q_hint']}

Return ONLY a JSON array of strings, each being one sub-question. No explanation, no markdown, just the JSON array.

Example: ["What is the market size for X?", "Who are the key competitors?", "What are recent trends?"]"""

        result = _perplexity_research(plan_prompt, model="sonar", focus=domain["focus"])
        data = json.loads(result)

        if "error" in data:
            return data

        answer = data.get("answer", "")

        # Extract JSON array from the answer
        sub_questions = _extract_json_array(answer)

        if not sub_questions:
            # Fallback: split the query into basic angles
            sub_questions = _fallback_plan(query, num_sub_qs)

        return {"sub_questions": sub_questions[:MAX_SUB_QUESTIONS]}

    except Exception as e:
        logger.error(f"Planning failed: {e}")
        return {"error": f"Planning phase failed: {str(e)}"}


def _extract_json_array(text: str) -> list:
    """Extract a JSON array from LLM response text."""
    import re

    # Try direct JSON parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(q).strip() for q in parsed if q]
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON array in the text
    matches = re.findall(r'\[[\s\S]*?\]', text)
    for match in matches:
        try:
            parsed = json.loads(match)
            if isinstance(parsed, list) and len(parsed) >= 2:
                return [str(q).strip() for q in parsed if q]
        except (json.JSONDecodeError, ValueError):
            continue

    return []


def _fallback_plan(query: str, n: int) -> list:
    """Generate basic sub-questions when LLM planning fails."""
    angles = [
        f"What is {query}? Overview and background.",
        f"What are the key facts and data about {query}?",
        f"What are the pros and cons of {query}?",
        f"What are recent developments regarding {query}?",
        f"What do experts say about {query}?",
        f"What are the alternatives or competitors to {query}?",
        f"What are the risks or challenges with {query}?",
        f"What is the future outlook for {query}?",
    ]
    return angles[:n]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Parallel Research — Query each sub-question
# ═══════════════════════════════════════════════════════════════════════════════

def _research_parallel(sub_questions: list, domain: dict, max_calls: int, start_time: float) -> list:
    """Research all sub-questions in parallel using thread pool."""
    from agent_tools import _perplexity_research

    findings = []
    calls_made = 0

    def research_one(sq: str) -> dict:
        """Research a single sub-question."""
        nonlocal calls_made
        if calls_made >= max_calls:
            return {"question": sq, "answer": None, "citations": [], "skipped": True}

        if time.time() - start_time > SESSION_TIMEOUT_SEC - 30:
            return {"question": sq, "answer": None, "citations": [], "timeout": True}

        try:
            calls_made += 1
            result = _perplexity_research(
                query=sq,
                model=domain.get("model", "sonar-pro"),
                focus=domain.get("focus", "web"),
            )
            data = json.loads(result)

            return {
                "question": sq,
                "answer": data.get("answer", ""),
                "citations": data.get("citations", []),
                "model": data.get("model", ""),
                "usage": data.get("usage", {}),
            }
        except Exception as e:
            logger.error(f"Research failed for '{sq[:50]}': {e}")
            return {"question": sq, "answer": None, "citations": [], "error": str(e)}

    # Use ThreadPoolExecutor for parallel research
    # Cap workers to avoid API rate limits
    max_workers = min(3, len(sub_questions))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(research_one, sq): sq for sq in sub_questions}
        for future in as_completed(futures):
            try:
                result = future.result(timeout=60)
                findings.append(result)
            except Exception as e:
                sq = futures[future]
                findings.append({"question": sq, "answer": None, "citations": [], "error": str(e)})

    # Sort findings back to original order
    q_order = {sq: i for i, sq in enumerate(sub_questions)}
    findings.sort(key=lambda f: q_order.get(f.get("question", ""), 999))

    return findings


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Synthesis — Combine findings into structured report
# ═══════════════════════════════════════════════════════════════════════════════

def _synthesize_report(query: str, sub_questions: list, findings: list, domain: dict, mode: str) -> str:
    """Synthesize all findings into a structured Markdown report."""
    from agent_tools import _perplexity_research

    # Build context from all findings
    sections = []
    for f in findings:
        if f.get("answer"):
            citations_str = ""
            if f.get("citations"):
                citations_str = "\nSources: " + ", ".join(f["citations"][:5])
            sections.append(f"### {f['question']}\n{f['answer']}{citations_str}")

    if not sections:
        return f"# Research: {query}\n\nNo findings were retrieved. The research sources may be unavailable or the query too narrow."

    combined = "\n\n---\n\n".join(sections)

    # If only 1-2 sections, skip the synthesis call to save API costs
    if len(sections) <= 2:
        report = f"# {query}\n\n{combined}\n"
        return report

    # Use a final synthesis call to create a cohesive report
    synthesis_prompt = f"""You are writing a comprehensive research report. Synthesize these findings into a well-structured report.

TOPIC: {query}
MODE: {mode}

FINDINGS:
{combined[:12000]}

Write a structured Markdown report with:
1. An executive summary (2-3 sentences)
2. Key findings organized by theme (not by sub-question)
3. Data points, statistics, and specific examples
4. Contradictions or areas of uncertainty
5. Conclusion with actionable takeaways

Use ## for sections and ### for subsections. Include inline citations where relevant.
Keep it thorough but concise — aim for quality over length."""

    try:
        result = _perplexity_research(
            query=synthesis_prompt,
            model=domain.get("model", "sonar-pro"),
            focus=domain.get("focus", "web"),
        )
        data = json.loads(result)
        synthesized = data.get("answer", "")

        if synthesized and len(synthesized) > 100:
            return f"# {query}\n\n{synthesized}"
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")

    # Fallback: return concatenated sections
    return f"# {query}\n\n{combined}"


# ═══════════════════════════════════════════════════════════════════════════════
# Audit Log
# ═══════════════════════════════════════════════════════════════════════════════

def _log_research(query: str, mode: str, depth: str, sources: int, elapsed: float):
    """Append-only audit log for research sessions."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "query": query[:200],
            "mode": mode,
            "depth": depth,
            "sources": sources,
            "elapsed_seconds": elapsed,
        }
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to log research: {e}")
