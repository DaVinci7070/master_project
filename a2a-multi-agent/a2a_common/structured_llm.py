from __future__ import annotations

import os
from typing import Type, TypeVar, Optional, List, Dict, Any

import instructor
from openai import OpenAI
from pydantic import BaseModel

from a2a_common.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

class StructuredLLMClient:

    DEFAULT_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://vllm:8003/v1")
    DEFAULT_API_KEY: str = os.getenv("VLLM_API_KEY", "EMPTY")
    DEFAULT_MODEL: str = os.getenv("VLLM_MODEL", "qwen2.5-7b-instruct")

    _instance: Optional["StructuredLLMClient"] = None

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or self.DEFAULT_API_KEY
        self.model = model or self.DEFAULT_MODEL
        self.timeout = timeout

        self._base_client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
        )

        self._client = instructor.from_openai(
            self._base_client,
            mode=instructor.Mode.JSON,
        )

        logger.info(
            "StructuredLLMClient initialized: base_url=%s, model=%s",
            self.base_url,
            self.model,
        )

    @classmethod
    def get(cls) -> "StructuredLLMClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate_structured(
        self,
        response_model: Type[T],
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        max_retries: int = 2,
        **kwargs,
    ) -> T:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        logger.debug(
            "Generating structured response: model=%s, response_model=%s",
            self.model,
            response_model.__name__,
        )

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            **kwargs,
        )

        logger.debug("Structured response generated successfully")
        return response

def generate_structured(
    response_model: Type[T],
    prompt: str,
    system: Optional[str] = None,
    **kwargs,
) -> T:
    client = StructuredLLMClient.get()
    return client.generate_structured(
        response_model=response_model,
        prompt=prompt,
        system=system,
        **kwargs,
    )
