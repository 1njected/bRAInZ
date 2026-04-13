"""Image ingestion — vision LLM description + OCR fallback."""

from __future__ import annotations
import asyncio
import base64
from pathlib import Path


_VISION_PROMPT = (
    "You are analyzing an image for a security knowledge base.\n"
    "Provide a detailed description of everything visible: text, diagrams, code, "
    "UI elements, terminal output, network diagrams, vulnerability details, tool output, "
    "or any other security-relevant content.\n\n"
    "Structure your response as:\n"
    "TITLE: <concise title for this image>\n"
    "DESCRIPTION:\n<full detailed description — extract all visible text verbatim, "
    "describe diagrams and structure, note any tools, CVEs, techniques, or concepts shown>"
)


def _read_image_b64(file_path: str) -> tuple[str, str]:
    """Return (base64_data, media_type) for an image file."""
    path = Path(file_path)
    ext = path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/png")
    with open(file_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return data, media_type


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return stem.replace("_", " ").replace("-", " ").title()


def _parse_vision_response(raw: str, fallback_title: str) -> tuple[str, str]:
    """Parse TITLE / DESCRIPTION from vision LLM response."""
    lines = raw.strip().splitlines()
    title = fallback_title
    desc_lines = []
    in_desc = False
    for line in lines:
        if line.upper().startswith("TITLE:"):
            title = line.split(":", 1)[1].strip() or fallback_title
        elif line.upper().startswith("DESCRIPTION:"):
            in_desc = True
        elif in_desc:
            desc_lines.append(line)
    description = "\n".join(desc_lines).strip() or raw.strip()
    return title, description


async def _vision_anthropic(llm, image_b64: str, media_type: str) -> str:
    msg = await llm._client.messages.create(
        model=llm._vision_model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
    )
    return msg.content[0].text


async def _vision_openai(llm, image_b64: str, media_type: str) -> str:
    resp = await llm._client.chat.completions.create(
        model=llm._vision_model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
    )
    return resp.choices[0].message.content


async def _vision_ollama(llm, image_b64: str) -> str:
    import httpx
    vision_model = llm._vision_model
    payload = {
        "model": vision_model,
        "prompt": _VISION_PROMPT,
        "images": [image_b64],
        "stream": False,
        "options": {"num_predict": 1500},
    }
    async with httpx.AsyncClient(timeout=float(llm._config.get("classify_timeout", 120))) as client:
        resp = await client.post(f"{llm._base_url}/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["response"]


async def _ocr(file_path: str) -> str:
    """Extract text via pytesseract OCR. Returns empty string if unavailable."""
    def _run():
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(file_path)
            return pytesseract.image_to_string(img).strip()
        except Exception:
            return ""
    return await asyncio.to_thread(_run)


async def describe_image(file_path: str, llm, fallback_title: str) -> tuple[str, str]:
    """
    Return (title, description) for an image.
    Always runs OCR and appends the result to the vision LLM description.
    """
    image_b64, media_type = await asyncio.to_thread(_read_image_b64, file_path)

    # Run vision LLM and OCR in parallel
    provider_class = type(llm).__name__

    async def _vision() -> str:
        try:
            if provider_class == "AnthropicProvider":
                return await _vision_anthropic(llm, image_b64, media_type)
            elif provider_class == "OpenAIProvider":
                return await _vision_openai(llm, image_b64, media_type)
            elif provider_class == "OllamaProvider":
                return await _vision_ollama(llm, image_b64)
        except Exception:
            pass
        return ""

    vision_raw, ocr_text = await asyncio.gather(_vision(), _ocr(file_path))

    title, description = _parse_vision_response(vision_raw, fallback_title) if vision_raw else (fallback_title, "")

    if ocr_text:
        if description:
            description = f"{description}\n\n## OCR Text\n{ocr_text}"
        else:
            description = ocr_text

    return title, description or f"Image: {fallback_title}"


async def ingest_image(file_path: str, original_filename: str | None, llm) -> dict:
    """Describe an image and return {title, content_md}."""
    path = Path(file_path)
    fallback_title = _title_from_filename(original_filename or path.name)
    title, description = await describe_image(file_path, llm, fallback_title)
    return {
        "title": title,
        "content_md": description,
    }
