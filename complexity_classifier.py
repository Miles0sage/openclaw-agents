"""
Complexity Classifier for OpenClaw Router (Python port)
Mirrors src/routing/complexity-classifier.ts logic exactly.
Analyzes query text and determines optimal model selection (Haiku, Sonnet, Opus).
Achieves 60-70% cost reduction through intelligent routing.
"""

import re
import math
from dataclasses import dataclass
from typing import List, Tuple

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
