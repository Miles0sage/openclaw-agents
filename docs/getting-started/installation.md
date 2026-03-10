# Installation

## Requirements

- Python 3.11+
- At least one model provider key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or compatible)

## From Source

```bash
git clone https://github.com/cybershield-agency/openclaw.git
cd openclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Verify

```bash
python -c "import gateway; print('gateway import ok')"
```

## Optional Docs Tooling

```bash
pip install mkdocs-material mkdocs-minify-plugin mkdocstrings[python] pymdown-extensions
```

## Next Steps

- [Quick Start](quickstart.md)
- [Configuration](configuration.md)
- [Architecture Overview](../architecture/overview.md)
