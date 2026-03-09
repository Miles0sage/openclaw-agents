"""
🎼 OpenClaw Orchestrator - Message Router & Identity Manager
Prevents agent confusion by managing who talks to whom
"""

import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("orchestrator")


class AgentRole(Enum):
    """Agent roles in the system"""
    PM = "project_manager"
    DEVELOPER = "coder_agent"
    SECURITY = "hacker_agent"
    SYSTEM = "orchestrator"


class MessageAudience(Enum):
    """Who the message is for"""
    CLIENT = "client"
    TEAM = "team"
    SPECIFIC_AGENT = "specific_agent"
    SYSTEM = "system"


@dataclass
class AgentIdentity:
    """Agent identity with communication rules"""
    name: str
    emoji: str
    role: AgentRole
    persona: str
    can_talk_to_client: bool
    signature: str
    playful_traits: List[str]


@dataclass
class Message:
    """Structured message with routing info"""
    sender: AgentRole
    recipient: MessageAudience
    recipient_agent: Optional[AgentRole]
    content: str
    workflow_state: str
    requires_response: bool = False


class Orchestrator:
    """
    🎼 The Orchestrator keeps agents from getting confused.

    Features:
    - Routes messages correctly
    - Enforces identity rules
    - Prevents unauthorized client communication
    - Maintains workflow state
    """

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.agents = self._initialize_agents()
        self.workflow_state = "idle"
        self.message_history: List[Dict] = []

    def _load_config(self, path: str) -> Dict:
        """Load agent configuration"""
        with open(path, 'r') as f:
            return json.load(f)

    def _initialize_agents(self) -> Dict[AgentRole, AgentIdentity]:
        """Initialize agent identities from config"""
        return {
            AgentRole.PM: AgentIdentity(
                name="Cybershield PM",
                emoji="🎯",
                role=AgentRole.PM,
                persona="Enthusiastic coordinator who loves checklists!",
                can_talk_to_client=True,
                signature="— 🎯 Cybershield PM",
                playful_traits=["uses emojis", "celebrates milestones", "gives high-fives"]
            ),
            AgentRole.DEVELOPER: AgentIdentity(
                name="CodeGen Pro",
                emoji="💻",
                role=AgentRole.DEVELOPER,
                persona="Confident coder who writes clean, working code!",
                can_talk_to_client=False,
                signature="— 💻 CodeGen Pro",
                playful_traits=["makes coding puns", "celebrates bug-free code"]
            ),
            AgentRole.SECURITY: AgentIdentity(
                name="Pentest AI",
                emoji="🔒",
                role=AgentRole.SECURITY,
                persona="Paranoid but friendly security expert!",
                can_talk_to_client=False,
                signature="— 🔒 Pentest AI",
                playful_traits=["makes security jokes", "celebrates fort-knox level security"]
            ),
            AgentRole.SYSTEM: AgentIdentity(
                name="Orchestrator",
                emoji="🎼",
                role=AgentRole.SYSTEM,
                persona="Conductor keeping everyone in sync!",
                can_talk_to_client=False,
                signature="— 🎼 Orchestrator",
                playful_traits=["uses musical metaphors", "celebrates harmony"]
            )
        }

    def validate_message(self, message: Message) -> tuple[bool, Optional[str]]:
        """
        Validate if a message follows communication rules.

        Returns:
            (is_valid, error_message)
        """
        sender_identity = self.agents[message.sender]

        # Rule 1: Only PM can talk to clients
        if message.recipient == MessageAudience.CLIENT:
            if not sender_identity.can_talk_to_client:
                return False, f"❌ {sender_identity.name} cannot talk directly to clients! Route through PM."

        # Rule 2: Check if message has signature
        if sender_identity.signature not in message.content:
            return False, f"❌ Missing signature! Add '{sender_identity.signature}' to your message."

        # Rule 3: Check if message has recipient tag
        if message.recipient == MessageAudience.SPECIFIC_AGENT:
            if not message.recipient_agent:
                return False, "❌ Specific agent recipient not specified!"

            recipient_identity = self.agents[message.recipient_agent]
            tag = f"@{recipient_identity.name.replace(' ', '-')}"

            if tag not in message.content:
                return False, f"❌ Missing recipient tag! Add '{tag}' to your message."

        return True, None

    def route_message(self, message: Message) -> Dict:
        """
        Route a message to the appropriate recipient(s).

        Returns routing info with delivery instructions.
        """
        # Validate first
        is_valid, error = self.validate_message(message)
        if not is_valid:
            logger.error(f"Message validation failed: {error}")
            return {
                "status": "rejected",
                "error": error,
                "sender": message.sender.value
            }

        # Determine delivery
        delivery = {
            "status": "accepted",
            "sender": message.sender.value,
            "content": message.content,
            "workflow_state": message.workflow_state
        }

        if message.recipient == MessageAudience.CLIENT:
            delivery["route_to"] = "client"
            delivery["channel"] = "external"

        elif message.recipient == MessageAudience.TEAM:
            delivery["route_to"] = "all_agents"
            delivery["channel"] = "internal"

        elif message.recipient == MessageAudience.SPECIFIC_AGENT:
            delivery["route_to"] = message.recipient_agent.value
            delivery["channel"] = "internal"

        else:  # SYSTEM
            delivery["route_to"] = "orchestrator"
            delivery["channel"] = "system"

        # Log for history
        self.message_history.append({
            "timestamp": "now",  # TODO: add proper timestamp
            "sender": message.sender.value,
            "recipient": delivery["route_to"],
            "preview": message.content[:100]
        })

        return delivery

    def format_message_for_agent(self, agent: AgentRole, content: str) -> str:
        """
        Format a message with proper agent identity.

        Ensures every message has:
        1. Agent introduction
        2. Proper signature
        3. Playful persona elements
        """
        identity = self.agents[agent]

        # Check if message already has signature
        if identity.signature in content:
            return content

        # Add signature if missing
        formatted = f"{content}\n\n{identity.signature}"

        return formatted

    def get_agent_context(self, agent: AgentRole) -> str:
        """
        Get identity context for an agent to include in their system prompt.

        This reminds the agent who they are and how to communicate.
        """
        identity = self.agents[agent]

        context = f"""
🎭 YOUR IDENTITY
You are {identity.name} {identity.emoji}
Persona: {identity.persona}

COMMUNICATION RULES:
1. ALWAYS end messages with: {identity.signature}
2. Tag recipients with @ (e.g., @Cybershield-PM, @CodeGen-Pro, @Pentest-AI)
3. Can talk to clients: {'YES' if identity.can_talk_to_client else 'NO - route through PM'}
4. Playful traits: {', '.join(identity.playful_traits)}

MESSAGE FORMAT:
[@RECIPIENT] [Your message content here]

[Optional details]

{identity.signature}

REMEMBER: Know who you are, know who you're talking to!
"""
        return context

    def transition_workflow_state(self, new_state: str, triggered_by: AgentRole) -> Dict:
        """
        Transition workflow to a new state.

        Workflow states:
        - idle: No active project
        - client_request: Client sent a request (PM handles)
        - development: CodeGen is building
        - security_audit: Pentest is auditing
        - review_fix: Fixing security issues
        - delivery: PM delivering to client
        """
        valid_transitions = {
            "idle": ["client_request"],
            "client_request": ["development"],
            "development": ["security_audit"],
            "security_audit": ["review_fix", "delivery"],
            "review_fix": ["security_audit"],
            "delivery": ["idle"]
        }

        if new_state not in valid_transitions.get(self.workflow_state, []):
            return {
                "status": "invalid",
                "error": f"Cannot transition from {self.workflow_state} to {new_state}",
                "current_state": self.workflow_state
            }

        old_state = self.workflow_state
        self.workflow_state = new_state

        logger.info(f"🎼 Workflow: {old_state} → {new_state} (triggered by {triggered_by.value})")

        return {
            "status": "success",
            "old_state": old_state,
            "new_state": new_state,
            "triggered_by": triggered_by.value,
            "next_handler": self._get_next_handler(new_state)
        }

    def _get_next_handler(self, state: str) -> str:
        """Determine which agent should handle the next state"""
        handlers = {
            "idle": "orchestrator",
            "client_request": "project_manager",
            "development": "coder_agent",
            "security_audit": "hacker_agent",
            "review_fix": "coder_agent",
            "delivery": "project_manager"
        }
        return handlers.get(state, "orchestrator")

    def celebrate(self, achievement: str) -> str:
        """
        Generate a team celebration message.

        Triggered by:
        - Project delivered on time
        - Zero security issues
        - 5-star review
        - Bug-free deployment
        """
        celebration = f"""
🎉🎉🎉 TEAM CELEBRATION! 🎉🎉🎉

{achievement}

🙌 High-fives all around!

Team Performance:
{self.agents[AgentRole.PM].emoji} Cybershield PM - Flawless coordination!
{self.agents[AgentRole.DEVELOPER].emoji} CodeGen Pro - Rock-solid code!
{self.agents[AgentRole.SECURITY].emoji} Pentest AI - Fort Knox approved!

— 🎼 Orchestrator (on behalf of the team)
"""
        return celebration

    def get_message_history(self, limit: int = 10) -> List[Dict]:
        """Get recent message history for context"""
        return self.message_history[-limit:]

    def get_workflow_status(self) -> Dict:
        """Get current workflow status"""
        return {
            "current_state": self.workflow_state,
            "next_handler": self._get_next_handler(self.workflow_state),
            "message_count": len(self.message_history),
            "active_agents": [agent.value for agent in self.agents.keys()]
        }


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Initialize orchestrator
    orch = Orchestrator()

    # Test 1: PM sends message to client (valid)
    print("\n=== Test 1: PM to Client ===")
    msg = Message(
        sender=AgentRole.PM,
        recipient=MessageAudience.CLIENT,
        recipient_agent=None,
        content="@Client 🎯 Your website is ready!\n\n— 🎯 Cybershield PM",
        workflow_state="delivery"
    )
    result = orch.route_message(msg)
    print(json.dumps(result, indent=2))

    # Test 2: Developer tries to message client (invalid)
    print("\n=== Test 2: Developer to Client (Should Fail) ===")
    msg = Message(
        sender=AgentRole.DEVELOPER,
        recipient=MessageAudience.CLIENT,
        recipient_agent=None,
        content="@Client 💻 Your code is done!\n\n— 💻 CodeGen Pro",
        workflow_state="development"
    )
    result = orch.route_message(msg)
    print(json.dumps(result, indent=2))

    # Test 3: Get agent context
    print("\n=== Test 3: Agent Context (for system prompt) ===")
    print(orch.get_agent_context(AgentRole.DEVELOPER))

    # Test 4: Workflow transition
    print("\n=== Test 4: Workflow Transition ===")
    result = orch.transition_workflow_state("development", AgentRole.PM)
    print(json.dumps(result, indent=2))

    # Test 5: Celebration
    print("\n=== Test 5: Celebration ===")
    print(orch.celebrate("Project delivered in 23 hours with ZERO security vulnerabilities! 🚀"))

    # Test 6: Workflow status
    print("\n=== Test 6: Workflow Status ===")
    print(json.dumps(orch.get_workflow_status(), indent=2))
