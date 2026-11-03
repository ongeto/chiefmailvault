"""Async client for local Ollama LLM."""

import json
import logging

import httpx

from config import OLLAMA_MODEL, OLLAMA_URL

logger = logging.getLogger(__name__)

OLLAMA_BATCH_SIZE = 35
OLLAMA_TIMEOUT_SECONDS = 180


async def is_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def list_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception:
        return []


def model_is_installed(configured: str, installed: list[str]) -> bool:
    if not configured or not installed:
        return False
    if configured in installed:
        return True
    base = configured.split(":")[0]
    return any(m == base or m.startswith(f"{base}:") for m in installed)


async def check_ready() -> dict:
    """Return Ollama connectivity and model readiness."""
    if not await is_available():
        return {
            "available": False,
            "model_ready": False,
            "configured_model": OLLAMA_MODEL,
            "installed_models": [],
            "message": f"Ollama is not reachable at {OLLAMA_URL}",
        }
    installed = await list_models()
    ready = model_is_installed(OLLAMA_MODEL, installed)
    if ready:
        msg = f"Ollama ready — model {OLLAMA_MODEL}"
    else:
        msg = (
            f"Ollama running but model '{OLLAMA_MODEL}' not found. "
            f"Installed: {', '.join(installed[:5]) or 'none'}. "
            f"Run: ollama pull {OLLAMA_MODEL}"
        )
    return {
        "available": True,
        "model_ready": ready,
        "configured_model": OLLAMA_MODEL,
        "installed_models": installed,
        "message": msg,
    }


async def classify_metadata_batch(metadata_batch: list[dict]) -> list[dict]:
    """Classify one batch; returns parsed suggestion dicts."""
    system = (
        "You classify email metadata for mailbox cleanup. "
        "Categories: system_notifications, newsletter_clutter, bloated_threads, "
        "large_attachments, keep. "
        "bloated_threads = older messages in a long reply chain where a newer message exists. "
        "Return JSON object: {\"items\": [{\"index\": 0, \"category\": \"keep\", \"reason\": \"...\"}]}. "
        "Only flag bloated_threads when metadata shows a reply/fwd AND likely redundant in a thread. "
        "Use category keep when unsure."
    )
    user = json.dumps(metadata_batch, ensure_ascii=False)

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        if resp.status_code == 404:
            raise RuntimeError(f"Model '{OLLAMA_MODEL}' not found — run: ollama pull {OLLAMA_MODEL}")
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return _parse_chat_json(content)


def _parse_chat_json(content: str) -> list[dict]:
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("results", []))
    except json.JSONDecodeError:
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass
    return []


async def classify_metadata(metadata_batch: list[dict]) -> list[dict]:
    """Classify all records in efficient batches."""
    all_items: list[dict] = []
    for i in range(0, len(metadata_batch), OLLAMA_BATCH_SIZE):
        chunk = metadata_batch[i : i + OLLAMA_BATCH_SIZE]
        # Re-index within chunk for the model, map back later
        indexed = [{**item, "index": j} for j, item in enumerate(chunk)]
        parsed = await classify_metadata_batch(indexed)
        for item in parsed:
            local_idx = item.get("index", -1)
            if 0 <= local_idx < len(chunk):
                item["index"] = i + local_idx
                all_items.append(item)
    return all_items
