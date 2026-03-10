# Contributing

## Development Setup

```bash
git clone https://github.com/cybershield-agency/openclaw.git
cd openclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Coding Guidelines

- Keep router logic small and testable
- Add structured logs for operational paths
- Validate inputs at API boundaries
- Update docs when adding endpoints or features

## Pull Request Checklist

- [ ] Code compiles and tests pass
- [ ] New/changed endpoints documented
- [ ] Backward compatibility considered
- [ ] Security implications reviewed

## Docs Contributions

MkDocs source lives in `docs/` with top-level config in `mkdocs.yml`.

```bash
mkdocs serve -a 0.0.0.0:8001
mkdocs build
```
