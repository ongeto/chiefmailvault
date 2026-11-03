"""Ollama client tests."""

from unittest.mock import AsyncMock, patch

import pytest

from intelligence import ollama_client


def test_model_is_installed_exact():
    assert ollama_client.model_is_installed("phi3:mini", ["phi3:mini", "llama3"])


def test_model_is_installed_base_name():
    assert ollama_client.model_is_installed("phi3", ["phi3:mini"])


def test_model_is_installed_missing():
    assert not ollama_client.model_is_installed("gemma4", ["phi3:mini", "llama3"])


def test_parse_chat_json_object_with_items():
    content = '{"items": [{"index": 0, "category": "keep", "reason": "ok"}]}'
    items = ollama_client._parse_chat_json(content)
    assert len(items) == 1
    assert items[0]["category"] == "keep"


@pytest.mark.asyncio
async def test_check_ready_when_unreachable():
    with patch.object(ollama_client, "is_available", AsyncMock(return_value=False)):
        status = await ollama_client.check_ready()
        assert status["available"] is False
        assert status["model_ready"] is False


@pytest.mark.asyncio
async def test_check_ready_when_model_missing():
    with patch.object(ollama_client, "is_available", AsyncMock(return_value=True)), patch.object(
        ollama_client, "list_models", AsyncMock(return_value=["phi3:mini"])
    ):
        with patch("intelligence.ollama_client.OLLAMA_MODEL", "gemma4"):
            status = await ollama_client.check_ready()
            assert status["available"] is True
            assert status["model_ready"] is False
            assert "gemma4" in status["message"]
