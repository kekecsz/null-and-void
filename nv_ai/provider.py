"""Model providers behind one small interface, so the AI player does not depend on one API.

A provider answers one request: fixed tools and instructions, a conversation (``items``), and
an output-token limit. It returns the tool call (if any), the output items to send back when
the conversation continues, and the token use.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from nv_ai.costs import Usage


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] | None  # None: the arguments were not valid JSON
    call_id: str
    raw_arguments: str = ""


@dataclass
class Reply:
    call: ToolCall | None
    text: str
    output_items: list[Any] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    incomplete: str | None = None  # why the reply stopped early (e.g. the output-token limit)


class Provider(Protocol):
    model: str

    def respond(self, instructions: str, tools: list[dict], items: list[Any], max_output_tokens: int) -> Reply: ...

    @staticmethod
    def user_item(text: str) -> Any: ...

    @staticmethod
    def tool_result_item(call: ToolCall, text: str) -> Any: ...


class OpenAIProvider:
    """OpenAI Responses API with function tools (one call per reply)."""

    MAX_OUTPUT_TOKENS = 128_000  # the model's limit (GPT-6 Luna)

    def __init__(self, model: str, reasoning_effort: str | None = None, timeout: float = 600.0):
        from openai import OpenAI  # imported here so the rest of the project runs without the SDK

        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = OpenAI(timeout=timeout, max_retries=2)

    def respond(self, instructions: str, tools: list[dict], items: list[Any], max_output_tokens: int) -> Reply:
        kwargs: dict[str, Any] = {}
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            tools=tools,
            tool_choice="required",
            parallel_tool_calls=False,
            input=items,
            max_output_tokens=min(max_output_tokens, self.MAX_OUTPUT_TOKENS),
            prompt_cache_key="null-and-void-ai",  # routes every seat's requests to the same cache
            **kwargs,
        )
        call = None
        texts = []
        for item in response.output:
            if item.type == "function_call" and call is None:
                try:
                    arguments = json.loads(item.arguments)
                except json.JSONDecodeError:
                    arguments = None
                call = ToolCall(item.name, arguments, item.call_id, item.arguments)
            elif item.type == "message":
                texts += [c.text for c in item.content if getattr(c, "type", "") == "output_text"]
        usage = Usage()
        if response.usage:
            u = response.usage
            details = u.input_tokens_details
            usage = Usage(
                input_tokens=u.input_tokens,
                cached_tokens=getattr(details, "cached_tokens", 0) or 0,
                cache_write_tokens=getattr(details, "cache_write_tokens", 0) or 0,
                output_tokens=u.output_tokens,
                reasoning_tokens=getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0,
            )
        incomplete = None
        if getattr(response, "status", "") == "incomplete":
            incomplete = getattr(getattr(response, "incomplete_details", None), "reason", "incomplete")
        return Reply(call, "\n".join(texts), list(response.output), usage, incomplete)

    @staticmethod
    def user_item(text: str) -> Any:
        return {"role": "user", "content": text}

    @staticmethod
    def tool_result_item(call: ToolCall, text: str) -> Any:
        return {"type": "function_call_output", "call_id": call.call_id, "output": text}


def make_provider(provider: str, model: str, reasoning_effort: str | None) -> Provider:
    if provider == "openai":
        return OpenAIProvider(model, reasoning_effort)
    raise ValueError(f"unknown AI provider {provider!r} (available: openai)")
