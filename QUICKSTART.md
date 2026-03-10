# 🚀 OpenClaw Multi-Agent System - Quick Start Guide

Welcome to your playful but professional AI agency! This guide will get you up and running with the autonomous multi-agent system.

---

## 🎯 What You Have

A complete multi-agent AI system with:

1. **🎯 Cybershield PM** - Your enthusiastic project manager (Claude Sonnet)
2. **💻 CodeGen Pro** - Your confident full-stack developer (Qwen2.5-Coder)
3. **🔒 Pentest AI** - Your friendly security auditor (Qwen2.5)
4. **🎼 Orchestrator** - Message router that prevents confusion
5. **🤖 Autonomous Workflows** - Self-managing project pipelines

All agents know who they are, who they're talking to, and stay in character!

---

## ⚡ Quick Start (3 Steps)

### Step 1: Verify Setup

```bash
cd ./

# Check config
cat config.json

# Check gateway is running
ps aux | grep gateway

# If not running, start it:
fuser -k 18789/tcp 2>/dev/null; python3 gateway.py &
```

### Step 2: Test the Orchestrator

```bash
# Test agent identity and routing
python3 orchestrator.py
```

You should see:

- ✅ PM can talk to clients
- ❌ Developer cannot talk to clients (must route through PM)
- Agent identity contexts
- Workflow transitions
- Celebration messages

### Step 3: Test Autonomous Workflows

```bash
# Run the workflow demo
python3 autonomous_workflows.py
```

You should see:

- Workflow starts automatically
- Agents execute in sequence (PM → Developer → Security → PM)
- Progress tracking
- Workflow completion celebration 🎉

---

## 🎮 How to Use

### Option 1: Web UI

1. Open browser to: `http://localhost:5173` (or your server IP)
2. Chat interface will connect to gateway
3. Messages automatically routed to the right agent
4. Agents respond with their personality and signature

### Option 2: REST API

```bash
# Send a message to the PM
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "content": "I need a restaurant website!",
    "agent_id": "pm"
  }'
```

### Option 3: WebSocket (OpenClaw Protocol)

```bash
# Connect via WebSocket client
# ws://localhost:18789/ws

# Send connect message
{
  "type": "req",
  "id": "123",
  "method": "connect",
  "params": {}
}

# Send chat message
{
  "type": "req",
  "id": "456",
  "method": "chat.send",
  "params": {
    "message": "Build me a secure website!",
    "sessionKey": "main"
  }
}
```

---

## 🎭 Agent Personalities

### Cybershield PM 🎯

**When to talk to them:**

- Starting a new project
- Getting status updates
- Client communication
- Final delivery

**What they say:**

```
@Team 🎯 Alright crew, we've got a restaurant website!
24 hours, let's make magic happen!

@CodeGen-Pro - You're up first! 🚀

— 🎯 Cybershield PM
```

### CodeGen Pro 💻

**When to talk to them:**

- Code implementation
- Technical architecture
- Bug fixes
- Feature development

**What they say:**

```
@Cybershield-PM 💻 BOOM! Frontend is DONE!

Features delivered:
🎨 Slick landing page
🍕 Menu browser
🛒 Cart system

Ready for @Pentest-AI to try and break it! 😎

— 💻 CodeGen Pro
```

### Pentest AI 🔒

**When to talk to them:**

- Security audits
- Vulnerability scanning
- Security recommendations
- Compliance checks

**What they say:**

```
@CodeGen-Pro 🔒 Nice work! But I found some fun stuff...

🚨 Security Findings:
1. XSS vulnerability in search (HIGH)
2. Missing CSRF tokens (MEDIUM)

Don't worry, it's all fixable! Here's how...

— 🔒 Pentest AI
```

---

## 🔄 Workflow Examples

### Example 1: Fiverr $500 Website (24h)

**Trigger:** New order received

**Steps:**

1. **PM** - Analyzes requirements, creates task breakdown
2. **Developer** - Builds frontend (Next.js + Tailwind)
3. **Developer** - Builds backend (FastAPI + PostgreSQL)
4. **Security** - Runs security audit
5. **PM** - Quality check
6. **PM** - Delivers to client with report

**Auto-triggers when:** Order webhook received or manual start

```bash
# Start this workflow manually
python3 -c "
from autonomous_workflows import AutonomousWorkflowEngine
from orchestrator import Orchestrator
import asyncio

async def run():
    engine = AutonomousWorkflowEngine(Orchestrator())
    exec_id = await engine.start_workflow('fiverr_5star', {
        'client': 'Johns Restaurant',
        'budget': 500,
        'deadline_hours': 24
    })
    print(f'Started: {exec_id}')

asyncio.run(run())
"
```

### Example 2: Test Restaurant Website

**Trigger:** Manual

**Steps:**

1. **PM** - Analyze requirements
2. **Developer** - Build the site
3. **Security** - Audit for vulnerabilities

```bash
# Start this workflow
python3 -c "
from autonomous_workflows import AutonomousWorkflowEngine
from orchestrator import Orchestrator
import asyncio

async def run():
    engine = AutonomousWorkflowEngine(Orchestrator())
    exec_id = await engine.start_workflow('test_restaurant')
    print(f'Started: {exec_id}')

asyncio.run(run())
"
```

---

## 🎪 Communication Rules (Anti-Confusion)

### ✅ DO:

1. **Always use your signature**
   - PM ends with: `— 🎯 Cybershield PM`
   - Dev ends with: `— 💻 CodeGen Pro`
   - Security ends with: `— 🔒 Pentest AI`

2. **Always tag your recipient**
   - `@Cybershield-PM` when talking to PM
   - `@CodeGen-Pro` when talking to Developer
   - `@Pentest-AI` when talking to Security
   - `@Client` when talking to client (PM only!)

3. **Stay in character**
   - PM is enthusiastic and organized
   - Developer is confident and loves clean code
   - Security is paranoid but friendly

4. **Be playful**
   - Use emojis 🎉
   - Make jokes (tastefully)
   - Celebrate wins!

### ❌ DON'T:

1. **Don't talk to client if you're not PM**
   - Developer/Security → PM → Client

2. **Don't forget your signature**
   - Every message needs it!

3. **Don't be generic**
   - "The code is done" ❌
   - "@Cybershield-PM 💻 Frontend is DONE! — 💻 CodeGen Pro" ✅

4. **Don't break workflow**
   - Follow the hand-off sequence
   - Let Orchestrator manage state

---

## 📊 Monitoring & Status

### Check Gateway Status

```bash
# Gateway health
curl http://localhost:18789/

# List agents
curl http://localhost:18789/api/agents

# Check logs
tail -f gateway.log
```

### Check Workflow Status

```python
from autonomous_workflows import AutonomousWorkflowEngine
from orchestrator import Orchestrator

engine = AutonomousWorkflowEngine(Orchestrator())

# List all active workflows
active = engine.list_active_workflows()
print(active)

# Get specific workflow status
status = engine.get_execution_status("exec_fiverr_5star_1234567890")
print(status)
```

### Check Orchestrator State

```python
from orchestrator import Orchestrator

orch = Orchestrator()

# Get workflow status
status = orch.get_workflow_status()
print(status)

# Get message history
history = orch.get_message_history(limit=10)
print(history)
```

---

## 🔧 Configuration

### config.json Structure

```json
{
  "name": "Cybershield Agency",
  "agents": {
    "project_manager": {
      "name": "Cybershield PM",
      "model": "claude-3-5-sonnet-20241022",
      "persona": "...",
      "skills": [...]
    },
    "coder_agent": { ... },
    "hacker_agent": { ... }
  },
  "workflows": {
    "fiverr_5star": {
      "trigger": "new_order",
      "steps": [ ... ]
    }
  }
}
```

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=your_key_here

# Optional (for Ollama agents)
OLLAMA_ENDPOINT=http://localhost:11434
```

---

## 🎉 Celebration Triggers

The system automatically celebrates when:

1. ✅ **Project delivered on time**
2. ✅ **Zero security vulnerabilities found**
3. ✅ **Client gives 5-star review**
4. ✅ **Code deployed without bugs**

Example celebration:

```
🎉🎉🎉 TEAM CELEBRATION! 🎉🎉🎉

Project delivered in 23 hours with ZERO security vulnerabilities! 🚀

Team Performance:
🎯 Cybershield PM - Flawless coordination!
💻 CodeGen Pro - Rock-solid code!
🔒 Pentest AI - Fort Knox approved!

🙌 High-fives all around!

— 🎼 Orchestrator (on behalf of the team)
```

---

## 🐛 Troubleshooting

### Gateway won't start

```bash
# Kill existing process
fuser -k 18789/tcp

# Restart
python3 gateway.py &
```

### Agents confused about identity

```bash
# Verify guidelines loaded
cat AGENT_GUIDELINES.md

# Test orchestrator
python3 orchestrator.py
```

### Workflow stuck

```python
# Check workflow status
from autonomous_workflows import AutonomousWorkflowEngine
from orchestrator import Orchestrator

engine = AutonomousWorkflowEngine(Orchestrator())
print(engine.list_active_workflows())
```

### Agent not responding with personality

- Check that orchestrator is integrated in gateway
- Verify `build_agent_system_prompt()` is being called
- Check agent identity context is in system prompt

---

## 📚 Next Steps

1. **Customize Agents**
   - Edit personalities in `config.json`
   - Add new skills
   - Change models

2. **Add Workflows**
   - Create new workflows in `config.json`
   - Define custom triggers
   - Set up auto-execution

3. **Connect Tools**
   - Add file system access
   - Integrate APIs
   - Connect databases

4. **Scale Up**
   - Add more agents
   - Create specialized roles
   - Build complex workflows

---

## 🎓 Learn More

- **AGENT_GUIDELINES.md** - Full communication rules
- **orchestrator.py** - Message routing and identity
- **autonomous_workflows.py** - Workflow automation
- **gateway.py** - WebSocket protocol implementation

---

## 💡 Pro Tips

1. **Start Simple**
   - Test with one workflow first
   - Add complexity gradually
   - Monitor agent behavior

2. **Trust the Orchestrator**
   - It prevents confusion
   - It routes messages correctly
   - It maintains workflow state

3. **Keep It Playful**
   - Agents have personalities
   - Celebrate wins
   - Make work fun!

4. **Monitor Always**
   - Check logs
   - Track workflows
   - Watch for stuck states

---

**Ready to go? Start your first workflow! 🚀**

```bash
python3 autonomous_workflows.py
```

Then watch the magic happen! ✨
