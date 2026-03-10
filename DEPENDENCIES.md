# OpenClaw Dependencies - Quick Reference

## Files Created/Updated

1. **`./requirements.txt`** (176 lines)
   - Complete list of 45 third-party packages with pinned versions
   - Organized by category (Core, LLM, Data, Files, Dev, etc.)
   - Includes optional scientific dependencies

2. **`./data/opensource_research/dependency_map.md`** (473 lines)
   - Comprehensive dependency analysis
   - Usage patterns, version strategies, conflicts
   - Installation guides for different scenarios
   - Troubleshooting reference

---

## Quick Install

```bash
cd ./
pip install -r requirements.txt --break-system-packages
```

---

## Dependencies Summary

### Core (Always Required)
- **fastapi** 0.109.0 - Web framework
- **pydantic** 2.12.4 - Data validation
- **anthropic** 0.78.0 - Claude API
- **uvicorn** 0.31.1 - ASGI server
- **requests** 2.32.3 - HTTP client
- **httpx** 0.28.1 - Async HTTP
- **websockets** 15.0.1 - WebSocket support

### LLM & AI
- **fastmcp** 3.1.0 - MCP protocol
- **openai** 1.0+ - GPT-5 support

### Data & Analysis
- **pandas** 2.3.3
- **numpy** 2.4.2
- **scipy** 1.17.0
- **scikit-learn** 1.8.0
- **matplotlib** 3.10.8
- **networkx** 3.6.1

### File Processing
- **pypdf** 6.7.2 - PDF extraction
- **pdf2image** 1.17.0 - PDF to images
- **openpyxl** 3.1.5 - Excel handling
- **lxml** 6.0.2 - XML/HTML parsing
- **pillow** 12.1.0 - Image processing
- **python-pptx** 0.6.21 - PowerPoint

### Integrations
- **stripe** 14.3.0 - Payments
- **slack-sdk** 3.25.0 - Slack API
- **python-telegram-bot** 20.0+ - Telegram

### Scheduling & Utils
- **APScheduler** 3.11.2 - Job scheduling
- **click** 8.3.1 - CLI
- **rich** 14.3.3 - Terminal formatting
- **pyyaml** 6.0.2 - YAML parsing
- **cryptography** 43.0.0 - Encryption

### Dev & Testing
- **pytest** 9.0.2 - Testing
- **hypothesis** 6.114.1 - Property-based tests

---

## What Changed

### From Old requirements.txt
```
fastapi==0.104.1
pydantic>=2.0,<3.0
...
```

### To New requirements.txt
- Added 40+ missing dependencies
- Pinned exact versions for stability
- Organized into logical sections
- Added installation instructions
- Included optional packages for ML/science

---

## Version Notes

### Pinned (Production-Tested)
- `fastapi==0.109.0`
- `pydantic==2.12.4`
- `anthropic==0.78.0`
- `stripe==14.3.0`

### Flexible (Safe to Update)
- `numpy>=2.4.2`
- `pandas>=2.3.3`
- `requests>=2.32.3`
- `rich>=14.3.3`

### Dev-Only (No Pinning)
- `mypy`
- `sphinx`
- `pytest`

---

## Optional Science Stack

For ML/deep learning/advanced analysis:

```bash
# PyTorch (preferred)
pip install torch>=2.0.0

# TensorFlow (alternative)
pip install tensorflow>=2.14.0

# Bayesian modeling
pip install pymc>=5.0.0 arviz>=0.15.0

# Single-cell analysis
pip install scanpy>=1.9.0 scvelo>=0.3.0

# Survival analysis
pip install lifelines>=0.27.0
```

---

## Internal Modules (Not in PyPI)

100+ internal modules live in `./` and are imported directly:

- `agent_router.py` - Job routing
- `agent_tools.py` - 75+ integrated tools
- `autonomous_runner.py` - Execution engine
- `approval_engine.py` - Workflow approval
- `cost_tracker.py` - Cost accounting
- `ceo_engine.py`, `pa_engine.py` - Agent personas
- Plus 90+ supporting modules

These are NOT in `requirements.txt` because they're not PyPI packages.

---

## Verification

Syntax check passed:
- 54 valid package specifications
- 0 parse errors
- All versions pinned or flexible ranges valid

---

## For Development

```bash
# Full install with testing
pip install -r requirements.txt --break-system-packages
pip install pytest hypothesis mypy

# Run tests
pytest -v

# Type check
mypy --ignore-missing-imports ./
```

---

## See Also

- `./requirements.txt` - Full package list
- `./data/opensource_research/dependency_map.md` - Detailed analysis
- `./CLAUDE.md` - System architecture
- `./pyproject.toml` - Project metadata

---

**Generated**: 2026-03-08 | **OpenClaw v4.2**
