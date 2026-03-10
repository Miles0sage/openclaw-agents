---
description: Structural patterns to reduce API spend without sacrificing output quality
agent: overseer
tags: [cost, optimization, patterns, efficiency]
priority: high
---

# Cost Optimization Patterns

Beyond [[cost-routing]] (model selection), these patterns reduce total spend structurally.

## Pattern 1: Prompt Caching

- Reuse system prompts across requests (many providers cache these)
- Store common context in [[memory-system]] instead of re-sending each time
- For Claude: use prompt caching (first 1024 tokens cached, 90% discount on repeats)
- Impact: 20-40% reduction on repetitive workflows

## Pattern 2: Context Compression

- Summarize conversation history before sending (not full transcript)
- [[overseer-coordination]] compresses session before delegation
- Send project context as references, not full files (point to [[barber-crm]] skill file, not the codebase)
- Impact: 30-50% token reduction per request

## Pattern 3: Skill Graph Traversal (This System)

- Agents read local markdown files instead of asking an LLM for decisions
- Keyword routing in [[cost-routing]] costs zero tokens
- Project context from skill files costs zero tokens
- Decision trees in [[auto-approve-rules]] cost zero tokens
- Impact: 20-30% fewer API calls overall

## Pattern 4: Batch Processing

- Group similar tasks and process in one API call
- Example: 5 file renames = 1 API call, not 5
- [[codegen-development]] batches lint fixes, test generation, formatting
- Impact: 40-60% reduction on batch-eligible tasks

## Pattern 5: Fail Fast, Escalate Smart

- Start with cheapest model per [[cost-routing]]
- If it fails, do NOT retry 3 times on cheap model — escalate after 1 retry
- Burning cheap tokens on hopeless tasks costs more than one Opus call
- See [[error-recovery]] for escalation protocol
- Impact: 15-25% reduction on complex tasks

## Pattern 6: Cache Common Answers

- FAQ responses, status templates, error messages — cache in [[memory-system]]
- Do not generate the same deployment status message every time
- Template once, fill variables, skip the LLM entirely
- Impact: 10-20% reduction on repetitive queries

## Combined Impact

Applying all patterns: 60-80% total cost reduction vs naive (all-Opus, no caching, no batching).
Track actual savings via [[budget-enforcement]] and adjust quarterly.
