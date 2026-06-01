"""Ollama-backed category classifier.

Returns one taxonomy label or None. Never raises — if Ollama is unreachable, slow,
or returns something not in the taxonomy, return None and let the cascade fall
through.
"""
from __future__ import annotations

import logging

import httpx

from ...config import get_settings

log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are a transaction categorizer for a personal finance app.

Categorize this merchant into EXACTLY ONE of these categories:
{categories}

Merchant: {merchant}

Rules:
- Reply with ONLY the category name, nothing else. No punctuation, no explanation.
- If you genuinely cannot tell, reply with: Other
- Match Spanish and English merchant names (the user lives in Spain and Chile).

Category:"""


def classify_with_ollama(
    normalized_merchant: str,
    taxonomy: list[str],
    *,
    model: str | None = None,
    url: str | None = None,
    timeout: float = 8.0,
) -> str | None:
    settings = get_settings()
    if not settings.ollama_enabled:
        return None
    if not normalized_merchant.strip():
        return None

    model = model or settings.ollama_model
    url = url or settings.ollama_url

    prompt = _PROMPT_TEMPLATE.format(
        categories=", ".join(taxonomy),
        merchant=normalized_merchant,
    )

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{url.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 16},
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Ollama unreachable or returned bad data: %s", e)
        return None

    raw = (data.get("response") or "").strip()
    # Take just the first line/token cluster and strip punctuation.
    candidate = raw.splitlines()[0].strip().strip(".,;:!?\"'`").strip()

    # Case-insensitive match against the taxonomy.
    lower_to_canonical = {c.lower(): c for c in taxonomy}
    if candidate.lower() in lower_to_canonical:
        return lower_to_canonical[candidate.lower()]

    log.info("Ollama returned non-taxonomy label %r for %r", candidate, normalized_merchant)
    return None
