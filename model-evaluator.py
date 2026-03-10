"""
🧪 OpenClaw Model Evaluator
Tests and compares capabilities across different AI models
"""

import asyncio
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import anthropic
import requests


@dataclass
class ModelConfig:
    """Configuration for a model to test"""
    id: str
    name: str
    provider: str
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    max_tokens: int = 2048


@dataclass
class TestResult:
    """Result of a single test"""
    model_id: str
    test_name: str
    passed: bool
    score: float  # 0-100
    response: str
    latency_ms: int
    tokens_used: int
    error: Optional[str] = None


class ModelEvaluator:
    """
    Evaluates and compares AI model capabilities

    Tests:
    1. Code generation
    2. Reasoning/logic
    3. Tool use
    4. Context understanding
    5. Following instructions
    6. Speed/latency
    7. Cost efficiency
    """

    def __init__(self):
        self.models: List[ModelConfig] = []
        self.results: List[TestResult] = []
        self.anthropic_client = None

    def add_model(self, model: ModelConfig):
        """Add a model to evaluate"""
        self.models.append(model)
        print(f"✅ Added model: {model.name} ({model.provider})")

    def add_anthropic_models(self, api_key: str):
        """Add all available Anthropic models"""
        self.anthropic_client = anthropic.Anthropic(api_key=api_key)

        models = [
            ModelConfig(
                id="claude-sonnet-4-5-20250929",
                name="Claude Sonnet 4.5",
                provider="anthropic",
                api_key=api_key,
                max_tokens=4096
            ),
            ModelConfig(
                id="claude-opus-4-6",
                name="Claude Opus 4.6",
                provider="anthropic",
                api_key=api_key,
                max_tokens=4096
            ),
            ModelConfig(
                id="claude-haiku-4-5-20251001",
                name="Claude Haiku 4.5",
                provider="anthropic",
                api_key=api_key,
                max_tokens=2048
            )
        ]

        for model in models:
            self.add_model(model)

    def add_ollama_models(self, endpoint: str = "http://localhost:11434"):
        """Add all available Ollama models"""
        try:
            response = requests.get(f"{endpoint}/api/tags")
            data = response.json()

            for model in data.get("models", []):
                model_name = model.get("name", "")

                self.add_model(ModelConfig(
                    id=f"ollama/{model_name}",
                    name=model_name,
                    provider="ollama",
                    endpoint=endpoint,
                    max_tokens=4096
                ))
        except Exception as e:
            print(f"⚠️  Failed to load Ollama models: {e}")

    async def test_code_generation(self, model: ModelConfig) -> TestResult:
        """Test 1: Code generation capability"""
        prompt = """Write a Python function that:
1. Takes a list of numbers
2. Filters out negative numbers
3. Squares the remaining numbers
4. Returns the sum

Include type hints and a docstring."""

        start_time = time.time()

        try:
            response, tokens = await self._call_model(model, prompt)
            latency_ms = int((time.time() - start_time) * 1000)

            # Check if response contains code
            has_code = "def" in response and "return" in response
            has_docstring = '"""' in response or "'''" in response
            has_type_hints = "->" in response

            score = 0
            if has_code:
                score += 50
            if has_docstring:
                score += 25
            if has_type_hints:
                score += 25

            return TestResult(
                model_id=model.id,
                test_name="Code Generation",
                passed=has_code,
                score=score,
                response=response[:500],  # Truncate
                latency_ms=latency_ms,
                tokens_used=tokens
            )

        except Exception as e:
            return TestResult(
                model_id=model.id,
                test_name="Code Generation",
                passed=False,
                score=0,
                response="",
                latency_ms=0,
                tokens_used=0,
                error=str(e)
            )

    async def test_reasoning(self, model: ModelConfig) -> TestResult:
        """Test 2: Logical reasoning"""
        prompt = """Solve this logic puzzle:

There are 3 boxes: red, blue, green.
- One contains gold, one contains silver, one is empty.
- All labels are incorrect.
- The red box is labeled "gold"
- The blue box is labeled "empty"
- The green box is labeled "silver"

Which box contains gold? Explain your reasoning step by step."""

        start_time = time.time()

        try:
            response, tokens = await self._call_model(model, prompt)
            latency_ms = int((time.time() - start_time) * 1000)

            # Correct answer is "blue box contains gold"
            has_answer = "blue" in response.lower()
            has_reasoning = "because" in response.lower() or "since" in response.lower()
            has_steps = response.count("\n") > 3

            score = 0
            if has_answer:
                score += 50
            if has_reasoning:
                score += 30
            if has_steps:
                score += 20

            return TestResult(
                model_id=model.id,
                test_name="Logical Reasoning",
                passed=has_answer,
                score=score,
                response=response[:500],
                latency_ms=latency_ms,
                tokens_used=tokens
            )

        except Exception as e:
            return TestResult(
                model_id=model.id,
                test_name="Logical Reasoning",
                passed=False,
                score=0,
                response="",
                latency_ms=0,
                tokens_used=0,
                error=str(e)
            )

    async def test_instruction_following(self, model: ModelConfig) -> TestResult:
        """Test 3: Following complex instructions"""
        prompt = """Follow these exact instructions:
1. Count backwards from 5 to 1
2. For each number, write the word "Number" followed by the digit
3. After each line, add an emoji (🔢)
4. End with "Done!"
5. Do NOT add any other text or explanation"""

        start_time = time.time()

        try:
            response, tokens = await self._call_model(model, prompt)
            latency_ms = int((time.time() - start_time) * 1000)

            # Check if instructions were followed
            has_numbers = all(str(i) in response for i in range(1, 6))
            has_word_number = response.count("Number") >= 5
            has_emoji = "🔢" in response
            has_done = "Done!" in response
            no_extra_text = len(response.split("\n")) <= 8

            score = 0
            if has_numbers:
                score += 25
            if has_word_number:
                score += 25
            if has_emoji:
                score += 20
            if has_done:
                score += 15
            if no_extra_text:
                score += 15

            return TestResult(
                model_id=model.id,
                test_name="Instruction Following",
                passed=all([has_numbers, has_word_number, has_done]),
                score=score,
                response=response[:500],
                latency_ms=latency_ms,
                tokens_used=tokens
            )

        except Exception as e:
            return TestResult(
                model_id=model.id,
                test_name="Instruction Following",
                passed=False,
                score=0,
                response="",
                latency_ms=0,
                tokens_used=0,
                error=str(e)
            )

    async def test_context_understanding(self, model: ModelConfig) -> TestResult:
        """Test 4: Understanding context and making connections"""
        prompt = """Context:
- Alice is a software engineer
- Bob is Alice's manager
- Carol reports to Bob
- David is Carol's teammate

Question: If Alice gets promoted to Bob's level, who would Carol report to?
Answer in one sentence with clear reasoning."""

        start_time = time.time()

        try:
            response, tokens = await self._call_model(model, prompt)
            latency_ms = int((time.time() - start_time) * 1000)

            # Check understanding
            mentions_carol = "carol" in response.lower()
            mentions_relationship = any(word in response.lower() for word in ["report", "manager", "superior"])
            concise = len(response.split()) < 50

            score = 0
            if mentions_carol:
                score += 40
            if mentions_relationship:
                score += 40
            if concise:
                score += 20

            return TestResult(
                model_id=model.id,
                test_name="Context Understanding",
                passed=mentions_carol and mentions_relationship,
                score=score,
                response=response[:500],
                latency_ms=latency_ms,
                tokens_used=tokens
            )

        except Exception as e:
            return TestResult(
                model_id=model.id,
                test_name="Context Understanding",
                passed=False,
                score=0,
                response="",
                latency_ms=0,
                tokens_used=0,
                error=str(e)
            )

    async def test_speed(self, model: ModelConfig) -> TestResult:
        """Test 5: Response speed"""
        prompt = "Say 'Hello, World!' and nothing else."

        start_time = time.time()

        try:
            response, tokens = await self._call_model(model, prompt)
            latency_ms = int((time.time() - start_time) * 1000)

            # Score based on speed
            if latency_ms < 1000:
                score = 100
            elif latency_ms < 2000:
                score = 80
            elif latency_ms < 3000:
                score = 60
            elif latency_ms < 5000:
                score = 40
            else:
                score = 20

            return TestResult(
                model_id=model.id,
                test_name="Speed Test",
                passed=True,
                score=score,
                response=response[:500],
                latency_ms=latency_ms,
                tokens_used=tokens
            )

        except Exception as e:
            return TestResult(
                model_id=model.id,
                test_name="Speed Test",
                passed=False,
                score=0,
                response="",
                latency_ms=0,
                tokens_used=0,
                error=str(e)
            )

    async def _call_model(self, model: ModelConfig, prompt: str) -> tuple[str, int]:
        """Call a model and return (response, tokens_used)"""

        if model.provider == "anthropic":
            response = self.anthropic_client.messages.create(
                model=model.id,
                max_tokens=model.max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text, response.usage.output_tokens

        elif model.provider == "ollama":
            response = requests.post(
                f"{model.endpoint}/api/generate",
                json={
                    "model": model.id.replace("ollama/", ""),
                    "prompt": prompt,
                    "stream": False
                }
            )
            data = response.json()
            return data.get("response", ""), len(data.get("response", "").split())

        else:
            raise ValueError(f"Unsupported provider: {model.provider}")

    async def run_all_tests(self):
        """Run all tests on all models"""
        print("\n🧪 Starting Model Evaluation")
        print("=" * 60)
        print(f"Testing {len(self.models)} models")
        print("=" * 60)
        print()

        tests = [
            self.test_code_generation,
            self.test_reasoning,
            self.test_instruction_following,
            self.test_context_understanding,
            self.test_speed
        ]

        for model in self.models:
            print(f"\n📊 Testing: {model.name}")
            print("-" * 60)

            for test_func in tests:
                result = await test_func(model)
                self.results.append(result)

                status = "✅" if result.passed else "❌"
                print(f"{status} {result.test_name}: {result.score}/100 ({result.latency_ms}ms)")

                if result.error:
                    print(f"   Error: {result.error}")

    def generate_report(self) -> str:
        """Generate comparison report"""
        report = []
        report.append("\n" + "=" * 80)
        report.append("📊 MODEL EVALUATION REPORT")
        report.append("=" * 80)
        report.append("")

        # Overall scores by model
        report.append("🏆 OVERALL SCORES")
        report.append("-" * 80)

        model_scores = {}
        for model in self.models:
            model_results = [r for r in self.results if r.model_id == model.id]
            if model_results:
                avg_score = sum(r.score for r in model_results) / len(model_results)
                avg_latency = sum(r.latency_ms for r in model_results) / len(model_results)
                total_tokens = sum(r.tokens_used for r in model_results)

                model_scores[model.id] = {
                    "name": model.name,
                    "score": avg_score,
                    "latency": avg_latency,
                    "tokens": total_tokens
                }

                report.append(f"{model.name:30} | Score: {avg_score:5.1f} | Latency: {avg_latency:6.0f}ms | Tokens: {total_tokens}")

        report.append("")

        # Test breakdown
        report.append("📋 TEST BREAKDOWN")
        report.append("-" * 80)

        test_names = list(set(r.test_name for r in self.results))
        for test_name in test_names:
            report.append(f"\n{test_name}:")
            test_results = [r for r in self.results if r.test_name == test_name]

            for result in sorted(test_results, key=lambda x: x.score, reverse=True):
                model = next(m for m in self.models if m.id == result.model_id)
                status = "✅" if result.passed else "❌"
                report.append(f"  {status} {model.name:25} {result.score:5.1f}/100 ({result.latency_ms}ms)")

        # Recommendations
        report.append("")
        report.append("🎯 RECOMMENDATIONS")
        report.append("-" * 80)

        # Best overall
        best_overall = max(model_scores.items(), key=lambda x: x[1]["score"])
        report.append(f"Best Overall:     {best_overall[1]['name']} ({best_overall[1]['score']:.1f}/100)")

        # Fastest
        fastest = min(model_scores.items(), key=lambda x: x[1]["latency"])
        report.append(f"Fastest:          {fastest[1]['name']} ({fastest[1]['latency']:.0f}ms)")

        # Most efficient (score/latency ratio)
        efficient = max(model_scores.items(), key=lambda x: x[1]["score"] / (x[1]["latency"] + 1))
        report.append(f"Most Efficient:   {efficient[1]['name']}")

        report.append("")
        report.append("=" * 80)

        return "\n".join(report)

    def save_results(self, filename: str = "model_evaluation_results.json"):
        """Save results to JSON file"""
        data = {
            "models": [
                {
                    "id": m.id,
                    "name": m.name,
                    "provider": m.provider
                }
                for m in self.models
            ],
            "results": [
                {
                    "model_id": r.model_id,
                    "test_name": r.test_name,
                    "passed": r.passed,
                    "score": r.score,
                    "latency_ms": r.latency_ms,
                    "tokens_used": r.tokens_used,
                    "error": r.error
                }
                for r in self.results
            ]
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\n💾 Results saved to: {filename}")


async def main():
    """Run the evaluator"""
    import os

    evaluator = ModelEvaluator()

    # Add Anthropic models (if API key available)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        print("✅ Adding Anthropic models...")
        evaluator.add_anthropic_models(anthropic_key)
    else:
        print("⚠️  ANTHROPIC_API_KEY not set - skipping Anthropic models")

    # Add Ollama models (if available)
    try:
        print("✅ Checking for Ollama models...")
        evaluator.add_ollama_models()
    except Exception as e:
        print(f"⚠️  Ollama not available: {e}")

    if not evaluator.models:
        print("❌ No models to evaluate!")
        print("   Set ANTHROPIC_API_KEY or start Ollama")
        return

    # Run tests
    await evaluator.run_all_tests()

    # Generate report
    report = evaluator.generate_report()
    print(report)

    # Save results
    evaluator.save_results()


if __name__ == "__main__":
    asyncio.run(main())
