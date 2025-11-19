"""
Abstraction over OpenAI and Claude for structured intent planning.
"""

import asyncio
from collections.abc import Sequence
from typing import Any, Literal, TypedDict, AsyncIterator

import json
import httpx
from anthropic import Anthropic
from openai import OpenAI

from .config import get_settings
from .exceptions import LLMOperationError


class LlmMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LlmClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._openai_client: OpenAI | None = None
        self._anthropic_client: Anthropic | None = None

    def _ensure_openai(self) -> OpenAI:
        if self._openai_client is None:
            self._openai_client = OpenAI(
                api_key=self.settings.openai_api_key,
                http_client=httpx.Client(timeout=30),
            )
        return self._openai_client

    def _ensure_anthropic(self) -> Anthropic:
        if self._anthropic_client is None:
            self._anthropic_client = Anthropic(
                api_key=self.settings.anthropic_api_key,
                timeout=30,
            )
        return self._anthropic_client

    def _build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None = None,
    ) -> list[LlmMessage]:
        messages: list[LlmMessage] = [
            {"role": "system", "content": system_prompt},
        ]
        if extra_messages:
            messages.extend(extra_messages)
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None = None,
    ) -> dict[str, Any]:
        if self.settings.llm_provider == "anthropic":
            return self._generate_json_anthropic(system_prompt, user_prompt, extra_messages)
        return self._generate_json_openai(system_prompt, user_prompt, extra_messages)

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None = None,
    ) -> str:
        if self.settings.llm_provider == "anthropic":
            return self._generate_text_anthropic(system_prompt, user_prompt, extra_messages)
        return self._generate_text_openai(system_prompt, user_prompt, extra_messages)

    async def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None = None,
    ) -> AsyncIterator[str]:
        if self.settings.llm_provider == "anthropic":
            # Simple fallback: yield the full text as a single chunk.
            text = self._generate_text_anthropic(system_prompt, user_prompt, extra_messages)
            yield text
            return
        async for chunk in self._stream_text_openai(system_prompt, user_prompt, extra_messages):
            yield chunk

    def _generate_json_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None,
    ) -> dict[str, Any]:
        client = self._ensure_openai()
        messages = self._build_messages(system_prompt, user_prompt, extra_messages)
        try:
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as e:
            error_msg = f"OpenAI API error: {type(e).__name__}: {e}"
            raise LLMOperationError(error_msg) from e

    def _generate_json_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None,
    ) -> dict[str, Any]:
        client = self._ensure_anthropic()
        messages = self._build_messages(system_prompt, user_prompt, extra_messages)
        system_message = ""
        user_messages: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "system":
                system_message = message["content"]
            else:
                user_messages.append(
                    {"role": message["role"], "content": message["content"]}
                )
        try:
            result = client.messages.create(
                model=self.settings.anthropic_model,
                system=system_message,
                max_tokens=2048,
                messages=user_messages,
            )
            text = result.content[0].text
            return json.loads(text)
        except Exception as e:
            error_msg = f"Anthropic API error: {type(e).__name__}: {e}"
            raise LLMOperationError(error_msg) from e

    def _generate_text_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None,
    ) -> str:
        client = self._ensure_openai()
        messages = self._build_messages(system_prompt, user_prompt, extra_messages)
        try:
            response = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            )
            content = response.choices[0].message.content or ""
            return content
        except Exception as e:
            error_msg = f"OpenAI API error: {type(e).__name__}: {e}"
            raise LLMOperationError(error_msg) from e

    async def _stream_text_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None,
    ) -> AsyncIterator[str]:
        client = self._ensure_openai()
        messages = self._build_messages(system_prompt, user_prompt, extra_messages)
        
        # Use a queue to handle blocking stream in a thread
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        stop_sentinel = None
        
        def process_stream():
            try:
                stream = client.chat.completions.create(
                    model=self.settings.openai_model,
                    messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                    stream=True,
                )
                for chunk in stream:
                    choice = chunk.choices[0]
                    delta = getattr(choice, "delta", None)
                    if delta and getattr(delta, "content", None):
                        queue.put_nowait(delta.content)
            except Exception as e:
                queue.put_nowait(f"ERROR: {e}")
            finally:
                queue.put_nowait(stop_sentinel)
        
        # Run the blocking stream processing in a thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, process_stream)
        
        # Yield chunks as they arrive
        while True:
            chunk = await queue.get()
            if chunk is stop_sentinel:
                break
            if chunk and not chunk.startswith("ERROR:"):
                yield chunk
            elif chunk and chunk.startswith("ERROR:"):
                error_msg = f"OpenAI streaming error: {chunk[7:]}"
                raise LLMOperationError(error_msg)

    def _generate_text_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Sequence[LlmMessage] | None,
    ) -> str:
        client = self._ensure_anthropic()
        messages = self._build_messages(system_prompt, user_prompt, extra_messages)
        system_message = ""
        user_messages: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "system":
                system_message = message["content"]
            else:
                user_messages.append(
                    {"role": message["role"], "content": message["content"]}
                )
        try:
            result = client.messages.create(
                model=self.settings.anthropic_model,
                system=system_message,
                max_tokens=1024,
                messages=user_messages,
            )
            return result.content[0].text
        except Exception as e:
            error_msg = f"Anthropic API error: {type(e).__name__}: {e}"
            raise LLMOperationError(error_msg) from e


