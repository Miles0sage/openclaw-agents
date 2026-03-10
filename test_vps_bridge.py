"""
Tests for VPS Integration Bridge
=================================
"""

import pytest
import asyncio
import json
from datetime import datetime
from vps_integration_bridge import (
    VPSIntegrationBridge,
    VPSAgentConfig,
    SessionContext,
    VPSCallResult,
    VPSProtocol,
    get_default_bridge,
    setup_default_bridge
)
from error_handler import ErrorType, TimeoutException


class TestVPSAgentConfig:
    """Test VPS agent configuration"""
    
    def test_config_creation(self):
        """Test creating VPS agent config"""
        config = VPSAgentConfig(
            name="test-agent",
            host="localhost",
            port=5000
        )
        assert config.name == "test-agent"
        assert config.host == "localhost"
        assert config.port == 5000
        assert config.protocol == VPSProtocol.HTTP
    
    def test_config_url_generation(self):
        """Test URL generation from config"""
        config = VPSAgentConfig(
            name="test-agent",
            host="192.168.1.100",
            port=5000,
            protocol=VPSProtocol.HTTP
        )
        url = config.get_url("/v1/messages")
        assert url == "http://192.168.1.100:5000/v1/messages"
    
    def test_config_https(self):
        """Test HTTPS protocol"""
        config = VPSAgentConfig(
            name="secure-agent",
            host="example.com",
            port=443,
            protocol=VPSProtocol.HTTPS
        )
        url = config.get_url("/api/chat")
        assert url.startswith("https://")
    
    def test_config_auth_headers(self):
        """Test auth token in headers"""
        config = VPSAgentConfig(
            name="secure-agent",
            host="localhost",
            port=5000,
            auth_token="secret-token-123"
        )
        headers = config.get_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer secret-token-123"
    
    def test_config_without_auth(self):
        """Test headers without auth"""
        config = VPSAgentConfig(
            name="public-agent",
            host="localhost",
            port=5000
        )
        headers = config.get_headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"


class TestSessionContext:
    """Test session context"""
    
    def test_session_creation(self):
        """Test creating session context"""
        session = SessionContext(
            session_id="sess-123",
            user_id="user-456"
        )
        assert session.session_id == "sess-123"
        assert session.user_id == "user-456"
        assert len(session.messages) == 0
    
    def test_add_message(self):
        """Test adding messages to session"""
        session = SessionContext(
            session_id="sess-123",
            user_id="user-456"
        )
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there", "pm-agent")
        
        assert len(session.messages) == 2
        assert session.messages[0]["role"] == "user"
        assert session.messages[1]["agent"] == "pm-agent"
    
    def test_session_to_dict(self):
        """Test session serialization"""
        session = SessionContext(
            session_id="sess-123",
            user_id="user-456"
        )
        session.add_message("user", "Test message")
        session.metadata["context"] = "test"
        
        data = session.to_dict()
        assert data["session_id"] == "sess-123"
        assert data["user_id"] == "user-456"
        assert len(data["messages"]) == 1
        assert data["metadata"]["context"] == "test"
    
    def test_session_last_activity_updates(self):
        """Test that last_activity updates on message"""
        session = SessionContext(
            session_id="sess-123",
            user_id="user-456"
        )
        old_time = session.last_activity
        
        import time
        time.sleep(0.01)  # Small delay
        session.add_message("user", "Message")
        
        assert session.last_activity > old_time


class TestVPSCallResult:
    """Test VPS call result"""
    
    def test_success_result(self):
        """Test successful call result"""
        result = VPSCallResult(
            success=True,
            agent_name="pm-agent",
            response="Hello from agent"
        )
        assert result.success
        assert result.response == "Hello from agent"
    
    def test_failure_result(self):
        """Test failed call result"""
        result = VPSCallResult(
            success=False,
            agent_name="pm-agent",
            error="Agent unreachable",
            error_type=ErrorType.TIMEOUT
        )
        assert not result.success
        assert result.error_type == ErrorType.TIMEOUT
    
    def test_result_to_dict(self):
        """Test result serialization"""
        result = VPSCallResult(
            success=True,
            agent_name="pm-agent",
            response="Test response",
            latency_ms=123.45,
            fallback_chain=["pm-agent", "sonnet"]
        )
        data = result.to_dict()
        assert data["success"]
        assert data["agent_name"] == "pm-agent"
        assert data["latency_ms"] == 123.45
        assert "pm-agent" in data["fallback_chain"]


class TestVPSIntegrationBridge:
    """Test VPS integration bridge"""
    
    def test_bridge_creation(self):
        """Test creating bridge"""
        bridge = VPSIntegrationBridge()
        assert len(bridge.agents) == 0
        assert len(bridge.sessions) == 0
    
    def test_register_agent(self):
        """Test registering agent"""
        bridge = VPSIntegrationBridge()
        config = VPSAgentConfig(
            name="pm-agent",
            host="localhost",
            port=5000
        )
        bridge.register_agent(config)
        
        assert "pm-agent" in bridge.agents
        assert bridge.get_agent_config("pm-agent") == config
    
    def test_register_multiple_agents(self):
        """Test registering multiple agents"""
        bridge = VPSIntegrationBridge()
        
        for i in range(3):
            config = VPSAgentConfig(
                name=f"agent-{i}",
                host="localhost",
                port=5000 + i
            )
            bridge.register_agent(config)
        
        assert len(bridge.agents) == 3
    
    def test_session_registration(self):
        """Test session registration"""
        bridge = VPSIntegrationBridge()
        
        session = bridge.register_session("sess-123", "user-456")
        
        assert session.session_id == "sess-123"
        assert session.user_id == "user-456"
        assert bridge.get_session("sess-123") == session
    
    def test_session_persistence(self):
        """Test that sessions persist"""
        bridge = VPSIntegrationBridge()
        
        session1 = bridge.register_session("sess-123", "user-456")
        session1.add_message("user", "First message")
        
        # Get existing session
        session2 = bridge.register_session("sess-123", "user-456")
        
        # Should have same messages
        assert len(session2.messages) == 1
        assert session2.messages[0]["content"] == "First message"
    
    def test_cleanup_sessions(self):
        """Test session cleanup"""
        from datetime import datetime, timedelta
        
        bridge = VPSIntegrationBridge()
        
        # Create sessions
        bridge.register_session("old-sess", "user-1")
        bridge.register_session("new-sess", "user-2")
        
        # Manually age the first session
        old_session = bridge.get_session("old-sess")
        old_session.last_activity = datetime.now() - timedelta(hours=48)
        
        # Cleanup
        cleaned = bridge.cleanup_sessions(max_age_hours=24)
        
        assert cleaned == 1
        assert "old-sess" not in bridge.sessions
        assert "new-sess" in bridge.sessions
    
    def test_get_nonexistent_agent(self):
        """Test getting non-existent agent"""
        bridge = VPSIntegrationBridge()
        config = bridge.get_agent_config("nonexistent")
        assert config is None
    
    def test_fallback_chain_registration(self):
        """Test fallback chain registration"""
        bridge = VPSIntegrationBridge()
        
        config = VPSAgentConfig(
            name="primary",
            host="localhost",
            port=5000,
            fallback_agents=["secondary", "tertiary"]
        )
        bridge.register_agent(config)
        
        assert bridge._fallback_chains["primary"] == ["secondary", "tertiary"]
    
    def test_health_tracking(self):
        """Test health tracking"""
        bridge = VPSIntegrationBridge()
        config = VPSAgentConfig(
            name="test-agent",
            host="localhost",
            port=5000
        )
        bridge.register_agent(config)
        
        # Record success
        bridge.health_tracker.record_agent_success("test-agent")
        status = bridge.get_agent_health("test-agent")
        
        assert status["status"] == "healthy"
        assert status["total_requests"] == 1
    
    def test_health_summary(self):
        """Test health summary"""
        bridge = VPSIntegrationBridge()
        
        for i in range(3):
            config = VPSAgentConfig(
                name=f"agent-{i}",
                host="localhost",
                port=5000 + i
            )
            bridge.register_agent(config)
            bridge.health_tracker.record_agent_success(f"agent-{i}")
        
        summary = bridge.get_health_summary()
        
        assert summary["total_agents"] == 3
        assert summary["healthy_agents"] == 3


class TestSessionSerialization:
    """Test session export/import"""
    
    def test_export_sessions(self, tmp_path):
        """Test exporting sessions"""
        bridge = VPSIntegrationBridge()
        
        session1 = bridge.register_session("sess-1", "user-1")
        session1.add_message("user", "Message 1")
        
        session2 = bridge.register_session("sess-2", "user-2")
        session2.add_message("user", "Message 2")
        
        filepath = tmp_path / "sessions.json"
        exported = bridge.export_sessions(str(filepath))
        
        assert exported == 2
        assert filepath.exists()
        
        # Verify content
        with open(filepath) as f:
            data = json.load(f)
        assert len(data["sessions"]) == 2
    
    def test_import_sessions(self, tmp_path):
        """Test importing sessions"""
        # Create and export
        bridge1 = VPSIntegrationBridge()
        session = bridge1.register_session("sess-1", "user-1")
        session.add_message("user", "Original message")
        
        filepath = tmp_path / "sessions.json"
        bridge1.export_sessions(str(filepath))
        
        # Import into new bridge
        bridge2 = VPSIntegrationBridge()
        imported = bridge2.import_sessions(str(filepath))
        
        assert imported == 1
        
        # Verify data
        imported_session = bridge2.get_session("sess-1")
        assert imported_session.user_id == "user-1"
        assert len(imported_session.messages) == 1


class TestVPSCallValidation:
    """Test VPS call validation"""
    
    def test_call_nonexistent_agent(self):
        """Test calling non-existent agent"""
        bridge = VPSIntegrationBridge()
        
        result = bridge.call_agent(
            "nonexistent",
            "test prompt"
        )
        
        assert not result.success
        assert "not registered" in result.error
    
    def test_call_with_session(self):
        """Test call with session tracking"""
        bridge = VPSIntegrationBridge()
        
        config = VPSAgentConfig(
            name="test-agent",
            host="192.168.1.1",  # Non-existent
            port=5000
        )
        bridge.register_agent(config)
        
        result = bridge.call_agent(
            "test-agent",
            "test prompt",
            session_id="sess-1",
            user_id="user-1"
        )
        
        # Would fail on actual call, but session should be created
        session = bridge.get_session("sess-1")
        assert session is not None
        assert session.user_id == "user-1"


class TestDefaultBridgeGlobal:
    """Test default bridge global instance"""
    
    def test_get_default_bridge(self):
        """Test getting default bridge"""
        bridge = get_default_bridge()
        assert bridge is not None
        assert isinstance(bridge, VPSIntegrationBridge)
    
    def test_default_bridge_singleton(self):
        """Test that default bridge is singleton"""
        bridge1 = get_default_bridge()
        bridge2 = get_default_bridge()
        assert bridge1 is bridge2
    
    def test_setup_default_bridge(self):
        """Test setup with agents"""
        # Reset global
        import vps_integration_bridge
        vps_integration_bridge._default_bridge = None
        
        agents = [
            VPSAgentConfig("agent-1", "localhost", 5000),
            VPSAgentConfig("agent-2", "localhost", 5001)
        ]
        
        bridge = setup_default_bridge(agents)
        
        assert len(bridge.agents) == 2
        assert "agent-1" in bridge.agents


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
