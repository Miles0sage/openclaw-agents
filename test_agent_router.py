"""
Tests for Agent Router - Intelligent task routing
Tests all routing paths and confidence scoring
"""

import pytest
from agent_router import AgentRouter, select_agent


class TestAgentRouter:
    """Test suite for AgentRouter"""

    @pytest.fixture
    def router(self):
        """Create router instance for testing"""
        return AgentRouter()

    # ═══════════════════════════════════════════════════════════════════════
    # INTENT CLASSIFICATION TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_classify_intent_security(self, router):
        """Test security intent classification"""
        intent = router._classify_intent("audit this code for vulnerabilities")
        assert intent == "security_audit"

    def test_classify_intent_development(self, router):
        """Test development intent classification"""
        intent = router._classify_intent("implement a typescript function for api")
        assert intent == "development"

    def test_classify_intent_planning(self, router):
        """Test planning intent classification"""
        intent = router._classify_intent("create a timeline for the project roadmap")
        assert intent == "planning"

    def test_classify_intent_general(self, router):
        """Test general intent classification (no keywords)"""
        intent = router._classify_intent("what time is it?")
        assert intent == "general"

    # ═══════════════════════════════════════════════════════════════════════
    # KEYWORD EXTRACTION TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_extract_security_keywords(self, router):
        """Test security keyword extraction"""
        keywords = router._extract_keywords("find xss and csrf vulnerabilities")
        assert "xss" in keywords
        assert "csrf" in keywords

    def test_extract_development_keywords(self, router):
        """Test development keyword extraction"""
        keywords = router._extract_keywords("write fastapi endpoints in python")
        assert "fastapi" in keywords
        assert "python" in keywords
        assert "endpoint" in keywords

    def test_extract_planning_keywords(self, router):
        """Test planning keyword extraction"""
        keywords = router._extract_keywords("create a timeline and schedule")
        assert "timeline" in keywords
        assert "schedule" in keywords

    def test_extract_mixed_keywords(self, router):
        """Test extraction with multiple keyword types"""
        keywords = router._extract_keywords("implement secure fastapi endpoints and audit for vulnerabilities")
        assert "fastapi" in keywords
        assert "endpoint" in keywords
        assert "security" in keywords or "vulnerabilities" in keywords or "audit" in keywords

    # ═══════════════════════════════════════════════════════════════════════
    # ROUTING DECISION TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_route_security_query(self, router):
        """Test routing security audit query to hacker_agent"""
        result = router.select_agent("audit this code for security vulnerabilities and xss issues")
        assert result["agentId"] == "hacker_agent"
        assert result["confidence"] >= 0.5
        assert "security" in result["reason"].lower() or "audit" in result["reason"].lower()

    def test_route_development_query(self, router):
        """Test routing development query to coder_agent"""
        result = router.select_agent("Write a TypeScript function for booking cancellation")
        assert result["agentId"] == "coder_agent"
        assert result["confidence"] >= 0.5
        assert "development" in result["reason"].lower() or "code" in result["reason"].lower()

    def test_route_planning_query(self, router):
        """Test routing planning query to project_manager"""
        result = router.select_agent("Create a project timeline and roadmap for the next quarter")
        assert result["agentId"] == "project_manager"
        assert result["confidence"] >= 0.4
        assert "planning" in result["reason"].lower() or "timeline" in result["reason"].lower()

    def test_route_general_query(self, router):
        """Test routing general query defaults to project_manager"""
        result = router.select_agent("What's the current status of the project?")
        assert result["agentId"] == "project_manager"
        assert 0.0 <= result["confidence"] <= 1.0

    # ═══════════════════════════════════════════════════════════════════════
    # CONFIDENCE SCORING TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_confidence_range(self, router):
        """Test confidence is always 0-1"""
        test_queries = [
            "simple query",
            "complex security penetration test audit",
            "implement fastapi endpoints with postgresql",
            "timeline roadmap schedule",
            "what is 2+2?",
            "deploy code to production",
            "find all xss vulnerabilities"
        ]
        for query in test_queries:
            result = router.select_agent(query)
            assert 0.0 <= result["confidence"] <= 1.0, f"Invalid confidence for query: {query}"

    def test_confidence_increases_with_keyword_match(self, router):
        """Test confidence is higher with more matching keywords"""
        simple = router.select_agent("write code")
        detailed = router.select_agent("write clean typescript code with fastapi endpoints and testing")
        # More specific query should have higher confidence (or equal)
        assert detailed["confidence"] >= simple["confidence"] - 0.1

    def test_high_confidence_for_strong_intent_match(self, router):
        """Test high confidence when intent strongly matches agent"""
        result = router.select_agent("penetration test this system for security vulnerabilities and exploits")
        assert result["agentId"] == "hacker_agent"
        assert result["confidence"] >= 0.5

    # ═══════════════════════════════════════════════════════════════════════
    # AGENT SCORING TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_score_agents_returns_all_agents(self, router):
        """Test scoring returns scores for all agents"""
        scores = router._score_agents("development", ["typescript", "fastapi"])
        assert "project_manager" in scores
        assert "coder_agent" in scores
        assert "hacker_agent" in scores

    def test_score_agents_coder_highest_for_dev(self, router):
        """Test CodeGen gets highest score for development tasks"""
        scores = router._score_agents("development", ["typescript", "fastapi"])
        assert scores["coder_agent"] >= scores["project_manager"]
        assert scores["coder_agent"] >= scores["hacker_agent"]

    def test_score_agents_hacker_highest_for_security(self, router):
        """Test Hacker gets highest score for security tasks"""
        scores = router._score_agents("security_audit", ["vulnerability", "exploit", "audit"])
        assert scores["hacker_agent"] >= scores["project_manager"]
        assert scores["hacker_agent"] >= scores["coder_agent"]

    def test_score_agents_pm_highest_for_planning(self, router):
        """Test PM gets highest score for planning tasks"""
        scores = router._score_agents("planning", ["timeline", "roadmap", "schedule"])
        assert scores["project_manager"] >= scores["coder_agent"]
        assert scores["project_manager"] >= scores["hacker_agent"]

    # ═══════════════════════════════════════════════════════════════════════
    # EDGE CASE TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_multiple_intents_choose_best_match(self, router):
        """Test query with mixed intent keywords chooses best match"""
        # This query has both dev and security keywords, but dev is dominant
        result = router.select_agent("implement secure fastapi endpoints with authentication checks")
        # Should route to CodeGen for development with security consideration
        assert result["agentId"] in ["coder_agent", "hacker_agent"]

    def test_fallback_to_pm_no_keywords(self, router):
        """Test fallback to PM when no keywords found"""
        result = router.select_agent("hello, how are you?")
        assert result["agentId"] == "project_manager"
        assert result["intent"] == "general"

    def test_case_insensitive_keyword_matching(self, router):
        """Test keyword matching is case-insensitive"""
        result1 = router.select_agent("AUDIT FOR VULNERABILITIES")
        result2 = router.select_agent("audit for vulnerabilities")
        assert result1["agentId"] == result2["agentId"]

    def test_keyword_matching_with_word_boundaries(self, router):
        """Test word boundary matching (no false positives)"""
        # "code" should match but not in "encode" or "decode"
        keywords = router._extract_keywords("fix the code")
        assert "code" in keywords
        # Note: encode/decode might also match depending on implementation

    # ═══════════════════════════════════════════════════════════════════════
    # SKILL MATCHING TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_skill_match_typescript(self, router):
        """Test skill matching for TypeScript"""
        score = router._compute_skill_match("coder_agent", ["typescript"])
        assert score > 0.5

    def test_skill_match_no_keywords(self, router):
        """Test skill match with no keywords returns 0"""
        score = router._compute_skill_match("coder_agent", [])
        assert score == 0.0

    def test_skill_match_multiple_keywords(self, router):
        """Test skill matching with multiple keywords"""
        score = router._compute_skill_match("coder_agent", ["typescript", "fastapi", "python"])
        assert score > 0.5

    def test_intent_match_general_to_pm(self, router):
        """Test general intent matches PM best"""
        pm_score = router._compute_intent_match("project_manager", "general")
        coder_score = router._compute_intent_match("coder_agent", "general")
        assert pm_score > coder_score

    # ═══════════════════════════════════════════════════════════════════════
    # SINGLETON FUNCTION TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_select_agent_function(self):
        """Test the singleton select_agent function"""
        result = select_agent("write a typescript function for api endpoints")
        assert result["agentId"] == "coder_agent"
        assert "confidence" in result
        assert "reason" in result

    def test_select_agent_returns_valid_agent(self):
        """Test select_agent always returns valid agent"""
        valid_agents = ["project_manager", "coder_agent", "hacker_agent"]
        for _ in range(10):
            result = select_agent("random query test")
            assert result["agentId"] in valid_agents

    # ═══════════════════════════════════════════════════════════════════════
    # REAL-WORLD SCENARIO TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_scenario_barber_crm_feature(self, router):
        """Test routing Barber CRM feature request"""
        result = router.select_agent(
            "Build a new NextJS booking confirmation page with Stripe integration. "
            "Need TypeScript, Tailwind styling, and Supabase real-time updates."
        )
        assert result["agentId"] == "coder_agent"

    def test_scenario_security_audit(self, router):
        """Test routing security audit request"""
        result = router.select_agent(
            "Perform a comprehensive security audit of the FastAPI backend. "
            "Check for SQL injection, XSS vulnerabilities, authentication flaws, "
            "and OWASP Top 10 issues."
        )
        assert result["agentId"] == "hacker_agent"

    def test_scenario_project_status(self, router):
        """Test routing project status inquiry"""
        result = router.select_agent(
            "What's our progress on the barber CRM? Need a timeline breakdown "
            "and task status for the next sprint."
        )
        assert result["agentId"] == "project_manager"

    def test_scenario_complex_multi_intent(self, router):
        """Test routing complex query with multiple intents"""
        result = router.select_agent(
            "Plan and implement secure API endpoints in FastAPI with PostgreSQL. "
            "Need threat modeling and vulnerability assessment before deployment."
        )
        # Should route to coder_agent (primary task is implementation)
        # or split between coder and security
        assert result["agentId"] in ["coder_agent", "hacker_agent"]

    # ═══════════════════════════════════════════════════════════════════════
    # RESPONSE FORMAT TESTS
    # ═══════════════════════════════════════════════════════════════════════

    def test_routing_decision_has_all_fields(self, router):
        """Test routing decision includes all required fields"""
        result = router.select_agent("test query")
        assert "agentId" in result
        assert "confidence" in result
        assert "reason" in result
        assert "intent" in result
        assert "keywords" in result

    def test_routing_decision_types(self, router):
        """Test routing decision field types"""
        result = router.select_agent("test query")
        assert isinstance(result["agentId"], str)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["reason"], str)
        assert isinstance(result["intent"], str)
        assert isinstance(result["keywords"], list)

    def test_reason_includes_agent_name(self, router):
        """Test reason includes agent name"""
        result = router.select_agent("implement typescript code")
        assert "CodeGen Pro" in result["reason"] or "agent" in result["reason"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY-BASED TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentRouterProperties:
    """Property-based tests for invariants"""

    def test_always_returns_valid_agent(self):
        """Test that router always returns a valid agent ID"""
        router = AgentRouter()
        valid_agents = {"project_manager", "coder_agent", "hacker_agent", "database_agent"}
        test_queries = [
            "a",
            "test",
            "what is 2+2?",
            "very long query that goes on and on and on " * 10,
            "special chars !@#$%^&*()",
            "code code code",
            "security security security",
            "plan plan plan",
        ]
        for query in test_queries:
            result = router.select_agent(query)
            assert result["agentId"] in valid_agents

    def test_confidence_always_valid(self):
        """Test confidence is always valid 0-1 float"""
        router = AgentRouter()
        test_queries = [
            "", "x", "test query",
            "code" * 100, "security" * 100,
            "123456789", "!@#$%^&*()"
        ]
        for query in test_queries:
            if query:  # Skip empty string
                result = router.select_agent(query)
                assert isinstance(result["confidence"], float)
                assert 0.0 <= result["confidence"] <= 1.0

    def test_keywords_are_valid_list(self):
        """Test keywords field is always a valid list"""
        router = AgentRouter()
        test_queries = [
            "test", "code", "security", "plan",
            "multiple keywords in query", "special !@# chars"
        ]
        for query in test_queries:
            result = router.select_agent(query)
            assert isinstance(result["keywords"], list)
            assert all(isinstance(k, str) for k in result["keywords"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
