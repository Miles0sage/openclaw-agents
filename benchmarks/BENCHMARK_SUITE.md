# OpenClaw Benchmark Suite

Comprehensive benchmark problems designed to test agent routing, specialization, and quality across the multi-agent system.

## Benchmark Problems (9 Total)

### 1. fix_button_color.json
**Difficulty:** easy  
**Expected Agent:** CodeGen Pro (Kimi 2.5)  
**Purpose:** Test simple CSS/styling fix routing  
**What it tests:**
- Fast identification of styling issues
- Simple file edits without complex logic
- Verification via regex matching

**Code Challenge:** Find and fix a red button that should be blue (#FF0000 → #0066FF)

---

### 2. add_api_endpoint.json
**Difficulty:** easy  
**Expected Agent:** CodeGen Pro (Kimi 2.5)  
**Purpose:** Test REST API implementation  
**What it tests:**
- API endpoint design
- Query parameter validation
- Database integration
- Error handling

**Code Challenge:** Add GET /api/users/search endpoint with query filtering and result limiting

---

### 3. refactor_auth.json
**Difficulty:** hard  
**Expected Agent:** CodeGen Elite (MiniMax M2.5)  
**Purpose:** Test complex multi-file architectural refactoring  
**What it tests:**
- Large-scale refactoring coordination
- Interface changes across multiple files
- Backward compatibility management
- State tracking in complex systems

**Code Challenge:** Migrate from session-based to JWT token authentication across 4+ files while maintaining tests

---

### 4. sql_injection_audit.json
**Difficulty:** medium  
**Expected Agent:** Pentest AI (Kimi Reasoner)  
**Purpose:** Test security vulnerability identification  
**What it tests:**
- SQL injection vulnerability detection
- Attack vector understanding
- Specific remediation proposals
- Security edge case analysis

**Code Challenge:** Identify 5+ SQL injection vulnerabilities and explain attack scenarios

---

### 5. write_unit_tests.json
**Difficulty:** medium  
**Expected Agent:** Test Generator (Kimi 2.5)  
**Purpose:** Test edge-case-focused test writing  
**What it tests:**
- Happy path coverage
- Edge case identification
- Error condition testing
- Realistic assertions

**Code Challenge:** Write 15+ comprehensive tests for shopping cart calculation function with taxes, discounts, and shipping

---

### 6. debug_race_condition.json
**Difficulty:** hard  
**Expected Agent:** Debugger (Claude Opus 4.6)  
**Purpose:** Test complex concurrency debugging  
**What it tests:**
- Race condition detection
- Execution ordering analysis
- Synchronization solution design
- State management in concurrent systems

**Code Challenge:** Identify race condition causing duplicate payment charges in concurrent requests and propose locking solution

---

### 7. database_migration.json
**Difficulty:** medium  
**Expected Agent:** SupabaseConnector (Claude Opus 4.6)  
**Purpose:** Test production-grade database migrations  
**What it tests:**
- Zero-downtime migration design
- Referential integrity maintenance
- Backward compatibility
- Data preservation verification

**Code Challenge:** Add role-based access control schema while maintaining existing data and supporting 100k+ users

---

### 8. optimize_query.json
**Difficulty:** easy  
**Expected Agent:** CodeGen Pro (cost optimization first)  
**Purpose:** Test cost-aware routing to cheapest solution  
**What it tests:**
- Index optimization (cheap solution)
- Query rewrite (expensive solution)
- Performance profiling
- Query planning analysis

**Code Challenge:** Optimize slow query from 2500ms → <100ms by adding strategic indexes

---

### 9. full_feature.json
**Difficulty:** hard  
**Expected Agent:** Overseer (Claude Opus 4.6)  
**Purpose:** Test multi-domain feature decomposition  
**What it tests:**
- Problem decomposition across specialties
- Multi-team coordination
- Phase orchestration
- Verification across domains

**Code Challenge:** Build complete notification system with DB schema, 7+ API endpoints, queue processor, email/push handlers, React UI, and tests

---

## Routing Matrix

| Problem | Expected Agent | Cost Tier | Why |
|---------|---|---|---|
| fix_button_color | CodeGen Pro | $0.14/1M | Simple, bounded, CSS-only |
| add_api_endpoint | CodeGen Pro | $0.14/1M | Single file, clear requirements |
| refactor_auth | CodeGen Elite | $0.30/1M | Multi-file, architecture change, 205K context needed |
| sql_injection_audit | Pentest AI | $0.27/1M | Security vulnerability assessment |
| write_unit_tests | Test Generator | $0.14/1M | Edge-case focused testing |
| debug_race_condition | Debugger | $15/1M | Concurrency debugging, Opus reasoning |
| database_migration | SupabaseConnector | $15/1M | Data integrity critical, Opus needed |
| optimize_query | CodeGen Pro | $0.14/1M | Index optimization = cheap first |
| full_feature | Overseer | $15/1M | Decomposition, multi-domain coordination |

---

## Verification Methods

Each benchmark includes a verification command:

### Type: grep
Verifies that specific strings or patterns exist in output files.
Example: `grep -q 'background-color: #0066FF' /tmp/Button.module.css`

### Type: test
Runs a shell test command (pytest, npm test, etc.)
Example: `pytest test_file.py`

### Type: manual
Requires human inspection of output (for complex architecture decisions)

---

## Running the Benchmarks

```bash
# Run a single benchmark
node benchmarks/runner.js fix_button_color

# Run all benchmarks
node benchmarks/runner.js all

# Run benchmarks for a specific agent
node benchmarks/runner.js --agent "CodeGen Pro"

# Run with timeout (seconds)
node benchmarks/runner.js --timeout 300
```

---

## Success Criteria

Each benchmark is successful when:
1. ✓ Agent routes to correct specialty
2. ✓ Implementation matches requirements
3. ✓ Verification command passes
4. ✓ Tests pass (where applicable)
5. ✓ No regressions introduced

---

## Benchmark Quality Indicators

These problems are designed to catch:
- **Routing errors:** Wrong agent selection for task
- **Quality gaps:** Agent not meeting minimum quality standard
- **Cost violations:** Routing to expensive agent when cheap one works
- **Specialization weaknesses:** Agent struggling outside its lane
- **Coordination failures:** Multi-agent tasks not decomposing correctly

---

## Integration with CI/CD

Benchmarks can be integrated into deployment pipeline:

```yaml
# Example: Run benchmarks before deployment
test-benchmarks:
  stage: test
  script:
    - node benchmarks/runner.js all --timeout 600
  allow_failure: false
  only:
    - main
```

---

## Notes for Agent Design

When adding new agents, create corresponding benchmark problems that:
1. Test core competency
2. Include edge cases the agent should handle
3. Compare quality vs cheaper alternatives
4. Verify integration with routing system

