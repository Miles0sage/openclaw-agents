---
description: NAU ASCE Concrete Canoe 2026 competition project — hull design and structural analysis
agent: codegen
tags: [project, engineering, competition, canoe, nau]
priority: low
---

# Concrete Canoe

NAU ASCE Concrete Canoe 2026 ("PLUTO JACKS") — competition project for hull design optimization.

## Design Specs

- Design A (optimal): 192" x 32" x 17" x 0.5" wall
- Weight: 174.3 lbs
- Repo: github.com/Miles0sage/concrete-canoe-project2026
- Local: /root/concrete-canoe-project2026/

## Key Decisions

- [[codegen-development]] handles Python analysis scripts
- Independent from [[prestress-calc]] — separate repo, separate concerns
- Lower priority than client projects ([[barber-crm]], [[delhi-palace]])
- Per [[priority-matrix]], competition deadlines drive urgency

## Current Status

Design analysis complete. Manufacturing phase (physical, not software).
Software work is mostly done — occasional optimization runs only.

## Cost

- Zero runtime cost (local Python scripts)
- Minimal agent time expected
