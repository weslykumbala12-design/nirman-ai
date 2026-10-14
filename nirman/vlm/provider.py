"""
NIRMAN AI -- VLM Provider Abstraction
Unified interface over Google Gemini and OpenAI GPT-4o.
Both providers support vision (base64 images) and text.
Automatic retry with exponential back-off via tenacity.
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class VLMMessage(BaseModel):
    role:    str           # 'user' | 'assistant' / 'model'
    content: str
    images:  List[str] = []   # base64-encoded image bytes (JPEG)


class VLMResponse(BaseModel):
    text:          str
    input_tokens:  int = 0
    output_tokens: int = 0
    model:         str
    provider:      str


class BaseVLMProvider(ABC):
    @abstractmethod
    def generate(self, messages: List[VLMMessage], system_prompt: str) -> VLMResponse:
        ...


# ---------------------------------------------------------------------------
# Gemini  (google-genai SDK -- current, non-deprecated)
# ---------------------------------------------------------------------------

class GeminiProvider(BaseVLMProvider):
    """Google Gemini 2.0 Flash -- vision + text via google-genai SDK."""

    def __init__(self, api_key: str, model: str = "models/gemini-3.8-flash"):
        from google import genai
        from google.genai import types as genai_types
        self._client    = genai.Client(api_key=api_key)
        self._types     = genai_types
        self.model_name = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def generate(self, messages: List[VLMMessage], system_prompt: str) -> VLMResponse:
        import base64
        types = self._types
        parts: list = []
        for msg in messages:
            for img_b64 in msg.images:
                img_bytes = base64.b64decode(img_b64)
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
            if msg.content:
                parts.append(types.Part.from_text(text=msg.content))

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.4,
        )
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=parts,
            config=config,
        )

        text = ""
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

        in_tok = out_tok = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            in_tok  = getattr(response.usage_metadata, "prompt_token_count",     0) or 0
            out_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        return VLMResponse(
            text=text, input_tokens=in_tok, output_tokens=out_tok,
            model=self.model_name, provider="gemini",
        )


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class OpenAIProvider(BaseVLMProvider):
    """OpenAI GPT-4o -- vision + text."""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import OpenAI
        self.client     = OpenAI(api_key=api_key)
        self.model_name = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def generate(self, messages: List[VLMMessage], system_prompt: str) -> VLMResponse:
        oai_msgs: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            parts: list[dict] = []
            for img_b64 in msg.images:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                })
            if msg.content:
                parts.append({"type": "text", "text": msg.content})
            oai_msgs.append({"role": msg.role, "content": parts})

        resp  = self.client.chat.completions.create(
            model=self.model_name, messages=oai_msgs, max_tokens=4096
        )
        text  = resp.choices[0].message.content or ""
        usage = resp.usage
        return VLMResponse(
            text=text,
            input_tokens=usage.prompt_tokens     if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self.model_name, provider="openai",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class VLMProviderFactory:
    @staticmethod
    def create(provider: str, api_key: str) -> BaseVLMProvider:
        if provider.lower() == "gemini":
            return GeminiProvider(api_key=api_key)
        if provider.lower() == "openai":
            return OpenAIProvider(api_key=api_key)
        raise ValueError(f"Unknown VLM provider '{provider}'. Use 'gemini' or 'openai'.")
