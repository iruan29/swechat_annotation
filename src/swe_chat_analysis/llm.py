from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class OpenAICompatibleClient:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 180
    max_retries: int = 4
    trust_env_proxy: bool = False

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def complete_json(self, system: str, user: str) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            raw = self._request(payload)
        except RuntimeError as error:
            # Several OpenAI-compatible servers implement chat completions but not
            # response_format. The rubric still strongly constrains the fallback.
            if "response_format" not in str(error) and "json_object" not in str(error):
                raise
            payload.pop("response_format", None)
            raw = self._request(payload)
        content = raw["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        annotation = parse_json_object(str(content))
        usage = raw.get("usage") or {}
        return annotation, usage

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                session = requests.Session()
                session.trust_env = self.trust_env_proxy
                with session:
                    response = session.post(
                        self.endpoint,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=(20, self.timeout_seconds),
                    )
                if response.status_code >= 400:
                    body = response.text[:1000]
                    last_error = RuntimeError(f"HTTP {response.status_code}: {body}")
                    if response.status_code not in {408, 409, 429, 500, 502, 503, 504}:
                        raise last_error
                else:
                    return response.json()
            except (requests.RequestException, json.JSONDecodeError) as error:
                last_error = error
            if attempt < self.max_retries:
                time.sleep(min(20, 2**attempt) + random.random())
        raise RuntimeError(f"LLM request failed after retries: {last_error}")


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response is not a JSON object")
    return value
