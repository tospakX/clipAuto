from __future__ import annotations

import re

import httpx


class OllamaError(RuntimeError):
    pass


def _parameter_count(model: dict) -> float:
    value = str(model.get("details", {}).get("parameter_size", ""))
    match = re.search(r"([\d.]+)\s*([BMK])?", value, re.IGNORECASE)
    if not match:
        return float(model.get("size") or "inf")
    number = float(match.group(1))
    return number * {"B": 1e9, "M": 1e6, "K": 1e3, "": 1}.get((match.group(2) or "").upper(), 1)


def choose_smallest_model(models: list[dict]) -> str:
    candidates = []
    for model in models:
        capabilities = model.get("capabilities")
        name = model.get("name") or model.get("model")
        if name and (not capabilities or "completion" in capabilities):
            candidates.append((_parameter_count(model), int(model.get("size") or 0), name))
    if not candidates:
        raise OllamaError("No installed Ollama text-generation model is available")
    return min(candidates)[2]


TOPIC_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["title", "start", "end"],
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "number"},
            "end": {"type": "number"},
        },
        "additionalProperties": False,
    },
}


SYSTEM_PROMPT = (
    "You segment transcripts into every distinct complete topic. Return one item per topic, "
    "covering the entire video in order. Boundaries must preserve complete sentences and "
    "complete discussions. Do not select highlights, rank moments, impose a duration, or omit "
    "mundane topics. A new sentence, example, aside, or detail is not automatically a new topic: "
    "merge consecutive material about the same central subject. Split only when the central "
    "subject or discussion goal genuinely changes. Titles must be short and specific. Timestamps "
    "are seconds and adjacent topics should meet without overlap. Transcript lines are Whisper "
    "chunks, not suggested topic boundaries. Never create one topic per sentence or chunk."
)

SEGMENTATION_EXAMPLE = """Video duration: 20 seconds.
Transcript:
[0.0-4.0] Here we are with an elephant.
[4.0-12.0] Elephants have very long trunks.
[12.0-15.0] Their trunks are cool.
[15.0-20.0] That is all I have to say about this elephant."""


class OllamaClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.http = http
        self._model: str | None = None

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self.http:
            response = await self.http.request(method, path, **kwargs)
        else:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=300) as client:
                response = await client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise OllamaError(f"Ollama request failed: {error}") from error
        return response

    async def installed_model(self) -> str:
        if self._model is None:
            response = await self._request("GET", "/api/tags")
            self._model = choose_smallest_model(response.json().get("models", []))
        return self._model

    async def segment(self, timestamped_transcript: str, duration: float) -> str:
        model = await self.installed_model()
        estimated_tokens = len(timestamped_transcript) // 3 + 4096
        context_size = max(8192, min(16384, estimated_tokens))
        response = await self._request(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "stream": False,
                "think": False,
                "format": TOPIC_SCHEMA,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 2048,
                    "num_ctx": context_size,
                },
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": SEGMENTATION_EXAMPLE},
                    {
                        "role": "assistant",
                        "content": '[{"title":"About the elephant","start":0,"end":20}]',
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Video duration: {duration:.3f} seconds.\n"
                            f"Transcript:\n{timestamped_transcript}"
                        ),
                    },
                ],
            },
        )
        try:
            return response.json()["message"]["content"]
        except (KeyError, TypeError, ValueError) as error:
            raise OllamaError("Ollama returned an invalid response envelope") from error
