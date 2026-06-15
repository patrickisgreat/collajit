"""Optional: suggest fetch search terms from the target image via Claude vision.

This only *populates* the terms field — the user can edit or replace anything it
returns, or skip it entirely and type their own terms (see the UI's terms box).
Uses the Anthropic SDK (``claude-opus-4-8``) with a structured JSON-schema output
so we get a clean list back. The image is downscaled before upload to keep it cheap.
"""

from __future__ import annotations

import base64
import io
import json
import os

from PIL import Image

from ..engine import image_ops

MODEL = "claude-opus-4-8"
_MAX_EDGE = 512

_PROMPT = (
    "You help source images for a photo mosaic. Look at this image and propose "
    "concise web image-search queries that would return MANY varied photos of the "
    "SAME subject — good as mosaic tiles. Prefer the concrete subject (e.g. 'human "
    "eye', 'iris macro') over scene descriptions. Give a short subject label and "
    "4-6 search terms."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "terms"],
    "additionalProperties": False,
}


def has_api_key() -> bool:
    """True if an Anthropic credential is present in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def parse_terms_response(text: str, *, max_terms: int = 6) -> list[str]:
    """Parse the model's JSON into a clean, de-duplicated term list (pure)."""
    data = json.loads(text)
    terms: list[str] = []
    subject = (data.get("subject") or "").strip()
    if subject:
        terms.append(subject)
    for t in data.get("terms", []):
        t = str(t).strip()
        if t:
            terms.append(t)
    # De-dup case-insensitively, preserve order, cap length.
    seen, out = set(), []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out[:max_terms]


def _encode_image(path: str) -> str:
    img = image_ops.load_image(path, mode="RGB")
    img.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def suggest_terms(image_path: str, *, max_terms: int = 6, model: str = MODEL) -> list[str]:
    """Ask Claude for search terms describing ``image_path``.

    Raises ``RuntimeError`` with a friendly message if the SDK isn't available or
    authentication fails — the caller surfaces it and the user falls back to typing
    terms manually.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency guaranteed in app
        raise RuntimeError("The 'anthropic' package is required for suggestions.") from exc

    data = _encode_image(image_path)
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=512,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": data,
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "Claude authentication failed. Set ANTHROPIC_API_KEY, or type terms manually."
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Claude request failed: {exc}") from exc

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("Claude returned no suggestions; type terms manually.")
    return parse_terms_response(text, max_terms=max_terms)
