"""Portfolio Health Review — deterministic rules engine.

A portfolio is evaluated against a fixed framework (suitability, allocation,
concentration, liquidity, downside risk, fees, rebalancing). The engine produces
explainable scores + structured JSON findings. An LLM (Stage 3) only *explains*
those findings — it never invents them or gives buy/sell advice.

Public surface:
- derive_policy(profile) -> PolicyData          (policy.py)
- run_review(profile, policy, snapshot, ...) -> ReviewResult   (engine.py)

Determinism: every function here is pure. The portfolio snapshot is fetched once
at the router layer and passed in; no clock/network/LLM calls happen inside the
engine. Same input ⇒ identical findings.
"""
from __future__ import annotations

# Bump on any change to engine logic / finding catalog. Persisted per review.
RULES_ENGINE_VERSION = "1.2"
# Bump on any change to the AI prompt (Stage 3). Persisted per review.
AI_PROMPT_VERSION = "1.0"
