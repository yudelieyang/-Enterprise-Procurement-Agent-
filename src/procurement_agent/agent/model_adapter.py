"""Thin OpenAI and deterministic scripted model adapters for the LangGraph node."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from collections import deque
from time import perf_counter
from typing import Any, Iterable

from openai import OpenAI

from procurement_agent.agent.models import AgentFinalResponse, ModelDiagnostic, ModelPreflight, ModelToolCall, ModelTurn, RequestRequirementsV2
from procurement_agent.agent.prompts import requirements_preflight_prompt


DEFAULT_MODEL = "gpt-5.6-luna"


class ModelAdapterError(RuntimeError):
    """Safe model-boundary error; raw provider errors never enter an Agent answer."""

    def __init__(self, message: str, *, stage: str = "model_adapter", cause: Exception | None = None) -> None:
        super().__init__(message)
        self.diagnostic = ModelDiagnostic(stage=stage, exception_class=type(cause).__name__ if cause else type(self).__name__, message=_sanitize_message(str(cause) if cause else message))


def _sanitize_message(message: str) -> str:
    """Keep useful SDK diagnostics while excluding common secret-bearing fragments."""

    message = re.sub(r"(?i)(authorization|api[_-]?key)\s*[:=]\s*\S+", r"\1=[redacted]", message)
    message = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[redacted]", message)
    return message[:500]


class ModelAdapter(ABC):
    """The deliberately small boundary needed to make orchestration unit-testable."""

    model_name: str

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], final_response_schema: dict[str, Any]) -> ModelTurn:
        """Return observable text/tool requests or a validated final response."""

    def preflight(self, user_query: str, requirements_version: str = "requirements_v2") -> ModelPreflight:
        """Return the conservative scripted/default preflight for legacy adapters."""

        return ModelPreflight(request_requirements=RequestRequirementsV2(decision_definition="SUFFICIENT", clarification_question=None, policy_support_requirement="NONE"))


class LiveOpenAIModelAdapter(ModelAdapter):
    """Official SDK adapter using function calling and SDK-managed Pydantic finals."""

    def __init__(self, *, api_key: str | None = None, model_name: str | None = None, reasoning_effort: str | None = None) -> None:
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ModelAdapterError("OPENAI_API_KEY is required for the live Agent adapter", stage="adapter_configuration")
        self.model_name = model_name or os.getenv("PROCUREMENT_AGENT_MODEL") or DEFAULT_MODEL
        self.reasoning_effort = reasoning_effort or os.getenv("PROCUREMENT_AGENT_REASONING_EFFORT") or "low"
        self.client = OpenAI(api_key=api_key)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], final_response_schema: dict[str, Any]) -> ModelTurn:
        try:
            response = self.client.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                reasoning_effort=self.reasoning_effort,
                response_format=AgentFinalResponse,
            )
        except Exception as error:  # provider-specific types are intentionally isolated here
            raise ModelAdapterError("OpenAI model request failed", stage="openai_chat_completions_parse", cause=error) from error

        message = response.choices[0].message
        tool_calls: list[ModelToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError as error:
                raise ModelAdapterError("Model emitted invalid tool-call JSON", stage="tool_call_argument_decode", cause=error) from error
            if not isinstance(arguments, dict):
                raise ModelAdapterError("Model tool-call arguments must be a JSON object", stage="tool_call_argument_decode")
            tool_calls.append(ModelToolCall(call_id=call.id, tool_name=call.function.name, arguments=arguments))

        usage = response.usage.model_dump(exclude_none=True) if response.usage else {}
        if tool_calls:
            return ModelTurn(assistant_content=message.content, tool_calls=tool_calls, usage=usage, served_model=response.model)
        final = message.parsed
        if final is None:
            raise ModelAdapterError("Model returned neither tool calls nor a final response", stage="final_response_parse")
        return ModelTurn(assistant_content=message.content, final_response=final, usage=usage, served_model=response.model)

    def preflight(self, user_query: str, requirements_version: str = "requirements_v2") -> ModelPreflight:
        started = perf_counter()
        try:
            response = self.client.chat.completions.parse(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": requirements_preflight_prompt(requirements_version)},
                    {"role": "user", "content": user_query},
                ],
                reasoning_effort=self.reasoning_effort,
                response_format=RequestRequirementsV2,
            )
        except Exception as error:  # provider-specific types are intentionally isolated here
            raise ModelAdapterError("OpenAI preflight request failed", stage="openai_preflight_parse", cause=error) from error
        requirements = response.choices[0].message.parsed
        if requirements is None:
            raise ModelAdapterError("Model returned no preflight response", stage="preflight_response_parse")
        usage = response.usage.model_dump(exclude_none=True) if response.usage else {}
        return ModelPreflight(request_requirements=requirements, usage=usage, served_model=response.model, duration_ms=round((perf_counter() - started) * 1000, 3))


class ScriptedModelAdapter(ModelAdapter):
    """A queue of observable model turns for deterministic no-credit unit tests."""

    def __init__(self, turns: Iterable[ModelTurn | dict[str, Any]], *, preflights: Iterable[ModelPreflight | RequestRequirementsV2 | dict[str, Any]] = (), model_name: str = "scripted-agent") -> None:
        self.model_name = model_name
        self._turns = deque(ModelTurn.model_validate(turn) for turn in turns)
        self._preflights = deque(self._preflight_item(item) for item in preflights)
        self.requests: list[dict[str, Any]] = []
        self.preflight_requests: list[str] = []
        self.preflight_versions: list[str] = []

    @staticmethod
    def _preflight_item(item: ModelPreflight | RequestRequirementsV2 | dict[str, Any]) -> ModelPreflight:
        if isinstance(item, ModelPreflight):
            return item
        if isinstance(item, RequestRequirementsV2):
            return ModelPreflight(request_requirements=item)
        if "request_requirements" in item:
            return ModelPreflight.model_validate(item)
        return ModelPreflight(request_requirements=RequestRequirementsV2.model_validate(item))

    def preflight(self, user_query: str, requirements_version: str = "requirements_v2") -> ModelPreflight:
        self.preflight_requests.append(user_query)
        self.preflight_versions.append(requirements_version)
        if not self._preflights:
            raise ModelAdapterError("Scripted model has no remaining preflight")
        return self._preflights.popleft()

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], final_response_schema: dict[str, Any]) -> ModelTurn:
        self.requests.append({"messages": messages, "tools": tools, "final_response_schema": final_response_schema})
        if not self._turns:
            raise ModelAdapterError("Scripted model has no remaining turn")
        return self._turns.popleft()
