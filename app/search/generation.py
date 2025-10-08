"""Answer generation helpers backed by Gemini."""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from app.config import settings

try:  # pragma: no cover - optional dependency in some environments
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - provide graceful degradation
    genai = None  # type: ignore
    types = None  # type: ignore

LOGGER = logging.getLogger(__name__)

_gemini_client: Optional["genai.Client"] = None


def _get_client() -> Optional["genai.Client"]:
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    if genai is None or settings.gemini_api_key is None:
        return None
    try:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
        return _gemini_client
    except Exception as exc:  # pragma: no cover - network/credential issues
        LOGGER.error("Failed to initialise Gemini client: %s", exc)
        return None


def _build_prompt(question: str, context: Iterable[dict]) -> str:
    sections: List[str] = []
    for idx, hit in enumerate(context, start=1):
        snippet = (hit.get("snippet") or hit.get("content") or "").strip()
        source = hit.get("id", f"source-{idx}")
        if snippet:
            sections.append(f"[Source {idx} | {source}]\n{snippet}")
    context_block = "\n\n".join(sections)
    return (
        "You are a documentation assistant.\n"  # instructions
        "Use the provided sources to answer the user's question in Traditional Chinese.\n"
        "Summarise concisely, provide bullet points when helpful, and cite sources as [Source N].\n"
        "If the answer is unclear, state that explicitly.\n"
        f"\nUser question:\n{question}\n\nSources:\n{context_block}"
    )


def _fallback_summary(context: Iterable[dict]) -> str:
    lines: List[str] = []
    for idx, hit in enumerate(context, start=1):
        snippet = (hit.get("snippet") or hit.get("content") or "").strip()
        if not snippet:
            continue
        first_sentence = snippet.split("。", 1)[0]
        lines.append(f"[Source {idx}] {first_sentence}…")
    if not lines:
        return "查無相關結果，請換個關鍵字或調整過濾條件。"
    return "\n".join(lines)


def generate_answer(question: str, context: List[dict]) -> str:
    if not context:
        return "查無相關結果，請換個關鍵字或調整過濾條件。"

    client = _get_client()
    if client is None:
        return _fallback_summary(context)

    try:
        prompt = _build_prompt(question, context)
        config_kwargs = {}
        if types is not None:
            config_kwargs["config"] = types.GenerateContentConfig(
                temperature=0.3,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )
        response = client.models.generate_content(  # type: ignore[attr-defined]
            model=settings.gemini_model,
            contents=prompt,
            **config_kwargs,
        )
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        if hasattr(response, "candidates") and response.candidates:
            parts = []
            for candidate in response.candidates:  # type: ignore[attr-defined]
                for part in getattr(candidate, "content", {}).get("parts", []):
                    maybe_text = getattr(part, "text", "")
                    if maybe_text:
                        parts.append(maybe_text)
            if parts:
                return "\n".join(parts)
    except Exception as exc:  # pragma: no cover - network/timeout issues
        LOGGER.error("Gemini generation failed: %s", exc)

    return _fallback_summary(context)
