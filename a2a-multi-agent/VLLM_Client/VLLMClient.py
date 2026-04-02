import os
from typing import Dict, List, Optional, ClassVar, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

import requests
from openai import OpenAI
from transformers import AutoTokenizer

class VLLMClient:
    DEFAULT_BASE_URL: ClassVar[str] = os.getenv(
        "VLLM_BASE_URL", "http://vllm:8003/v1"
    )
    DEFAULT_API_KEY: ClassVar[str] = os.getenv("VLLM_API_KEY", "EMPTY")
    DEFAULT_MODEL: ClassVar[str] = os.getenv(
        "VLLM_MODEL", "qwen2.5-7b-instruct"
    )
    DEFAULT_TOKENIZER_DIR: ClassVar[Optional[str]] = os.getenv(
        "VLLM_TOKENIZER_DIR"
    )

    _instance: ClassVar[Optional["VLLMClient"]] = None
    tokenizer: ClassVar[Optional[AutoTokenizer]] = None

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

        self._sdk = None
        if OpenAI is not None:
            try:
                self._sdk = OpenAI(base_url=self.base_url, api_key=self.api_key)
            except Exception:
                self._sdk = None

        if VLLMClient.tokenizer is None and self.DEFAULT_TOKENIZER_DIR:
            VLLMClient.tokenizer = AutoTokenizer.from_pretrained(
                self.DEFAULT_TOKENIZER_DIR,
                use_fast=True,
                trust_remote_code=True,
            )

        self.log_model_info_vllm()

    @classmethod
    def get(cls) -> "VLLMClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def chat(self, messages: List[Dict[str, str]], **gen):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        payload.update(gen or {})
        payload = {k: v for k, v in payload.items() if v is not None}

        if self._sdk:
            resp = self._sdk.chat.completions.create(**payload)
            return resp

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        r = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def generate(self, prompt: str, system: Optional[str] = None, **gen_kwargs) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})

        resp = self.chat(
            msgs,
            temperature=gen_kwargs.pop("temperature", 0.2),
            max_tokens=gen_kwargs.pop("max_tokens", 512),
            top_p=gen_kwargs.pop("top_p", 0.95),
            **gen_kwargs,
        )
        if hasattr(resp, "choices"):
            return resp.choices[0].message.content
        return resp["choices"][0]["message"]["content"]

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
        from a2a_common.structured_llm import StructuredLLMClient

        structured_client = StructuredLLMClient(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            timeout=self.timeout,
        )
        return structured_client.generate_structured(
            response_model=response_model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            **kwargs,
        )

    def _cuda_info(self):
        return "cpu (mode: Gemini/Cloud)"

    def log_model_info_vllm(self, prefix: str = "[LLM][vLLM]"):
        print(
            f"{prefix} backend=vLLM(OpenAI API), "
            f"base_url={self.base_url}, model={self.model}, {self._cuda_info()}",
            flush=True,
        )
