import json

import httpx
import pytest

from clipauto.ollama import OllamaClient, OllamaError, choose_smallest_model


def test_selects_smallest_completion_model_by_parameter_count():
    models = [
        {
            "name": "large:latest",
            "size": 4_000,
            "details": {"parameter_size": "30.5B"},
            "capabilities": ["completion"],
        },
        {
            "name": "embed:latest",
            "size": 100,
            "details": {"parameter_size": "0.3B"},
            "capabilities": ["embedding"],
        },
        {
            "name": "small:latest",
            "size": 9_000,
            "details": {"parameter_size": "9.7B"},
            "capabilities": ["vision", "completion"],
        },
    ]

    assert choose_smallest_model(models) == "small:latest"


def test_model_selection_rejects_no_generation_models():
    with pytest.raises(OllamaError, match="No installed Ollama text-generation model"):
        choose_smallest_model([])


@pytest.mark.asyncio
async def test_segment_requests_json_schema_and_returns_message_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "tiny:1b",
                            "details": {"parameter_size": "1B"},
                            "capabilities": ["completion"],
                        }
                    ]
                },
            )
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"message": {"content": '[{"title":"Intro","start":0,"end":12}]'}}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://ollama") as http:
        content = await OllamaClient("http://ollama", http=http).segment(
            "[0.0-12.0] Hello world", 12
        )

    assert json.loads(content)[0]["title"] == "Intro"
    assert seen["model"] == "tiny:1b"
    assert seen["stream"] is False
    assert seen["think"] is False
    assert seen["options"]["num_predict"] == 2048
    assert seen["options"]["num_ctx"] == 8192
    assert seen["format"]["type"] == "array"
    assert "complete topic" in seen["messages"][0]["content"].lower()
    assert [message["role"] for message in seen["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "Hello world" in seen["messages"][-1]["content"]
