"""Stage 3 — AI explanation layer for Portfolio Health findings.

Architecture:
- `ExplanationProvider` ABC — pluggable; `OllamaExplanationProvider` is the default.
- `explain_review(review_data, finding_ids, provider)` — public entry point.
- Guardrails (deterministic, post-LLM):
    - Output may only reference finding IDs present in the review.
    - Output must not contain buy/sell/hold instructions or ticker recommendations.
    - Output must not contain return predictions or tax/legal advice.
    - Any failure → graceful degradation to `_template_explanation(review_data)`.
- Deterministic template fallback — `_template_explanation()` — always works offline.

The prompt deliberately gives the LLM only the structured review JSON (findings +
scores + missing data + profile summary). It never says "evaluate this portfolio"
— the deterministic engine already did that; the LLM only writes the explanation.
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod

import httpx

from ...config import get_settings

log = logging.getLogger(__name__)

# ---- forbidden-phrase patterns (post-LLM guardrail) -------------------------
_FORBIDDEN = re.compile(
    # Catch active advice/prediction language; exclude disclaimer contexts where
    # "legal advice" / "tax advice" appear after "not" / "no" (those are good).
    r"\b(?:buy|sell|purchase|invest\s+in|short\s+(?:the|this|your|a\b)|"
    r"recommend\w*|predict\w*|"
    r"will\s+(?:go\s+up|go\s+down|rise|fall|increase|decrease)|"
    r"guaranteed|certain(?:ty)?|"
    r"(?<!not\s)(?<!nor\s)(?<!no\s)(?<!without\s)"
    r"tax\s+advice|consult\s+your\s+tax)\b",
    re.IGNORECASE,
)


# ---- ExplanationProvider interface ------------------------------------------

class ExplanationProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str | None:
        """Return raw LLM text or None on any failure."""


class OllamaExplanationProvider(ExplanationProvider):
    """Ollama HTTP client — mirrors categorization/ollama.py pattern."""

    def __init__(
        self,
        model: str | None = None,
        url: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ):
        settings = get_settings()
        self.model = model or settings.ollama_model
        self.url = url or settings.ollama_url
        self.timeout = timeout
        self._client = client

    def generate(self, prompt: str) -> str | None:
        settings = get_settings()
        if not settings.ollama_enabled:
            return None
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            try:
                resp = client.post(
                    f"{self.url.rstrip('/')}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                )
                resp.raise_for_status()
                return resp.json().get("response", "").strip() or None
            finally:
                if self._client is None:
                    client.close()
        except Exception as e:  # noqa: BLE001
            log.warning("Ollama explanation unavailable: %s", e)
            return None


# ---- prompt builder ---------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are a portfolio review assistant for a personal finance app. Your job is to \
explain the findings from a deterministic rules engine in plain, educational language.

STRICT RULES — follow exactly:
1. You may ONLY reference findings listed in the JSON below. Do NOT invent new findings.
2. Do NOT recommend buying, selling, or holding any specific asset.
3. Do NOT name specific securities, funds, or ETFs to buy or sell.
4. Do NOT predict future returns, prices, or performance.
5. Do NOT give tax or legal advice.
6. Always end with a note that this is educational and not professional financial advice.

REVIEW DATA:
{review_json}

Write a structured explanation with exactly these 7 sections, each starting with its label \
on its own line followed by the content:

OVERALL SUMMARY:
<2-3 sentence plain-English summary of the portfolio's health.>

WHAT'S WORKING:
<Bullet list of aligned areas (finding ids with sev=low or sub-scores ≥ 85).>

NEEDS ATTENTION:
<Bullet list of the top issues, referencing only finding ids present in the data.>

WHY THESE MATTER:
<2-4 sentences connecting the findings to the household's stated goals and time horizon.>

WHAT TO REVIEW NEXT:
<2-3 concrete review steps (not buy/sell instructions — review steps).>

DATA LIMITATIONS:
<Brief note on missing data that limits this analysis.>

PROFESSIONAL ADVICE NOTE:
This is an educational review based on a deterministic rules engine. It is not \
investment, tax, or legal advice. For decisions involving your specific situation, \
consider speaking with a licensed financial advisor.
"""


def _build_prompt(review_data: dict) -> str:
    """Distil the review down to what the LLM needs — findings + scores + meta.
    Never includes raw holdings or an open 'evaluate this portfolio' instruction.
    """
    safe = {
        "profile_summary": {
            "primary_goal": review_data.get("primary_goal"),
            "time_horizon": review_data.get("time_horizon"),
            "risk_profile": review_data.get("risk_profile"),
        },
        "overall_score": review_data.get("overall_score"),
        "sub_scores": review_data.get("sub_scores"),
        "status": review_data.get("status"),
        "findings": review_data.get("findings", []),
        "missing_data": review_data.get("missing_data", []),
    }
    return _PROMPT_TEMPLATE.format(review_json=json.dumps(safe, ensure_ascii=False, indent=2))


# ---- response parser --------------------------------------------------------

_SECTION_HEADS = {
    "OVERALL SUMMARY:": "overall_summary",
    "WHAT'S WORKING:": "aligned",
    "NEEDS ATTENTION:": "needs_attention",
    "WHY THESE MATTER:": "why_it_matters",
    "WHAT TO REVIEW NEXT:": "what_to_review_next",
    "DATA LIMITATIONS:": "data_limitations",
    "PROFESSIONAL ADVICE NOTE:": "professional_advice_note",
}


def _parse_sections(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        matched = next((k for k in _SECTION_HEADS if stripped.startswith(k)), None)
        if matched:
            if current_key and buf:
                result[current_key] = "\n".join(buf).strip()
            current_key = _SECTION_HEADS[matched]
            remainder = stripped[len(matched):].strip()
            buf = [remainder] if remainder else []
        elif current_key is not None:
            buf.append(line)

    if current_key and buf:
        result[current_key] = "\n".join(buf).strip()
    return result


# ---- guardrail enforcement --------------------------------------------------

def _valid_finding_id(text: str, known_ids: set[str]) -> bool:
    """Return True if text doesn't reference any finding-id-like token outside known_ids."""
    # Finding IDs follow the pattern "word.word" (e.g. "suitability.horizon_cap").
    # If the LLM invents IDs, they would appear here.
    found = set(re.findall(r"\b\w+\.\w[\w_]*\b", text))
    unknown = found - known_ids
    if unknown:
        log.warning("Guardrail: AI explanation references unknown finding ids: %s", unknown)
        return False
    return True


def _passes_content_guardrail(text: str) -> bool:
    if _FORBIDDEN.search(text):
        log.warning("Guardrail: AI explanation contains forbidden phrase; using template fallback.")
        return False
    return True


# ---- deterministic template fallback ----------------------------------------

def _template_explanation(review_data: dict) -> dict:
    """Build a structured explanation from the findings without any LLM call.
    Always deterministic; used when Ollama is off or guardrail rejects output.
    """
    findings = review_data.get("findings", [])
    score = review_data.get("overall_score", 0)
    missing = review_data.get("missing_data", [])
    risk_profile = review_data.get("risk_profile", "")
    goal = review_data.get("primary_goal", "")
    horizon = review_data.get("time_horizon", "")

    high = [f for f in findings if f.get("severity") == "high"]
    medium = [f for f in findings if f.get("severity") == "medium"]
    low = [f for f in findings if f.get("severity") == "low"]

    # overall_summary
    if score >= 80:
        summary = (
            f"The portfolio scores {score:.0f}/100 — generally well-aligned with the "
            f"{risk_profile} profile. "
            f"There are {len(high) + len(medium)} item(s) that merit review."
        )
    elif score >= 60:
        summary = (
            f"The portfolio scores {score:.0f}/100. Several areas need attention — "
            f"particularly {len(high)} high-severity item(s)."
        )
    else:
        summary = (
            f"The portfolio scores {score:.0f}/100. Multiple issues were found that "
            "may need to be reviewed to align better with the stated goals."
        )

    # aligned
    if low:
        aligned_bullets = "\n".join(f"• {f['finding']}" for f in low[:3])
    else:
        aligned_bullets = "• No specific high-scoring areas identified in this review."

    # needs_attention
    if high or medium:
        attention_bullets = "\n".join(
            f"• [{f['severity'].upper()}] {f['finding']}" for f in (high + medium)[:5]
        )
    else:
        attention_bullets = "• No major issues identified."

    # why_it_matters
    horizon_map = {
        "lt_1y": "under 1 year", "1_3y": "1–3 years",
        "3_7y": "3–7 years", "7_15y": "7–15 years", "gt_15y": "over 15 years",
    }
    why = (
        f"These findings are evaluated relative to a {risk_profile} risk profile with a "
        f"{horizon_map.get(horizon, horizon)} horizon and a primary goal of "
        f"{goal.replace('_', ' ')}. Misalignments between the current portfolio and "
        "these parameters can affect long-term outcomes."
    )

    # what_to_review_next
    next_steps = []
    if high:
        next_steps.append(f"• Review the {len(high)} high-severity finding(s) first.")
    if missing:
        next_steps.append("• Add missing asset prices or classes to improve data quality.")
    next_steps.append("• Consider running the review again after any portfolio changes.")
    if not next_steps:
        next_steps = ["• Continue monitoring the portfolio against the stated policy."]

    # data_limitations
    if missing:
        lim = "Missing data items:\n" + "\n".join(f"• {m}" for m in missing[:5])
    else:
        lim = "No significant data gaps detected."

    return {
        "overall_summary": summary,
        "aligned": aligned_bullets,
        "needs_attention": attention_bullets,
        "why_it_matters": why,
        "what_to_review_next": "\n".join(next_steps),
        "data_limitations": lim,
        "professional_advice_note": (
            "This is an educational review based on a deterministic rules engine. "
            "It is not investment, tax, or legal advice. For decisions involving your "
            "specific situation, consider speaking with a licensed financial advisor."
        ),
        "generated_by": "template",
    }


# ---- public entry point -----------------------------------------------------

def explain_review(
    review_data: dict,
    provider: ExplanationProvider | None = None,
) -> tuple[dict, str | None]:
    """Generate an AI explanation for a completed review.

    Returns (explanation_dict, prompt_version_used).
    explanation_dict is always non-None (template fallback guarantees it).
    prompt_version_used is None when the template was used.
    """
    from app.services.portfolio_health import AI_PROMPT_VERSION  # noqa: PLC0415

    known_finding_ids = {f.get("id", "") for f in review_data.get("findings", [])}

    if provider is None:
        provider = OllamaExplanationProvider()

    prompt = _build_prompt(review_data)
    raw = provider.generate(prompt)

    if raw is not None:
        # Post-LLM guardrail checks
        if not _passes_content_guardrail(raw):
            raw = None
        elif not _valid_finding_id(raw, known_finding_ids):
            raw = None

    if raw is not None:
        sections = _parse_sections(raw)
        # Require at least overall_summary; fall back if parsing yielded nothing useful.
        if sections.get("overall_summary"):
            sections["generated_by"] = "ollama"
            return sections, AI_PROMPT_VERSION

    # Template fallback — always succeeds
    return _template_explanation(review_data), None
