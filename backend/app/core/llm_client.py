"""
LiteLLM Client Wrapper with Instructor Support

Provides a unified interface for LLM inference across multiple providers.
Supports Gemini, OpenAI, Anthropic, vLLM, Ollama, and any LiteLLM-compatible provider.

Features:
- Structured outputs via Instructor (Pydantic models)
- Automatic retries with exponential backoff
- Rate limit handling
- Streaming support

Usage:
    from app.core.llm_client import LLMClient, chat, chat_structured
    from pydantic import BaseModel

    # Simple chat
    response = await chat([{"role": "user", "content": "Hello!"}])
    print(response.content)

    # Structured output with Pydantic model
    class Person(BaseModel):
        name: str
        age: int

    person = await chat_structured(
        messages=[{"role": "user", "content": "Extract: John is 25 years old"}],
        response_model=Person
    )
    print(person.name, person.age)
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, TypeVar, Type

import litellm
from litellm import acompletion
import instructor
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Configure LiteLLM
litellm.drop_params = True  # Drop unsupported params instead of erroring
litellm.set_verbose = False  # Disable verbose logging by default

# Type variable for generic structured outputs
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Exception raised for LLM-related errors."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


@dataclass
class LLMResponse:
    """Response from an LLM completion request."""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"

    @property
    def total_tokens(self) -> int:
        """Total tokens used in the request."""
        return self.usage.get("total_tokens", 0)

    @property
    def prompt_tokens(self) -> int:
        """Tokens used in the prompt."""
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        """Tokens used in the completion."""
        return self.usage.get("completion_tokens", 0)


class LLMClient:
    """
    Unified LLM client using LiteLLM for provider abstraction.

    Supports hot-swappable providers via environment variables or constructor arguments.
    Uses Instructor for reliable structured outputs with any provider.

    Provider Examples:
        - Gemini: model="gemini/gemini-2.0-flash"
        - OpenAI: model="gpt-4o"
        - Anthropic: model="claude-3-5-sonnet-20241022"
        - vLLM: model="hosted_vllm/model-name", api_base="http://vllm:8000/v1"
        - Ollama: model="ollama/llama3.2", api_base="http://localhost:11434"
    """

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        timeout: float | None = None,
    ):
        """
        Initialize the LLM client.

        Args:
            model: LiteLLM model identifier (e.g., "gemini/gemini-2.0-flash").
                   Falls back to LLM_MODEL env var, then default.
            api_base: Custom API base URL for self-hosted models.
                      Falls back to LLM_API_BASE env var.
            timeout: Request timeout in seconds.
                     Falls back to LLM_TIMEOUT env var, then 120.0.
        """
        self.model = model or os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")
        self.api_base = api_base or os.getenv("LLM_API_BASE") or None
        self.timeout = timeout or float(os.getenv("LLM_TIMEOUT", "120.0"))
        # Retry configuration for rate limits
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "5"))
        self.retry_base_delay = float(os.getenv("LLM_RETRY_DELAY", "2.0"))

        # Initialize Instructor client for structured outputs
        # Using MD_JSON mode for better compatibility with Gemini
        self._instructor_client = instructor.from_litellm(
            acompletion,
            mode=instructor.Mode.MD_JSON,  # Works well with Gemini
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate (None for model default).
            **kwargs: Additional arguments passed to LiteLLM.

        Returns:
            LLMResponse with content, model, usage, and finish_reason.

        Raises:
            LLMError: If the request fails.
        """
        # Remove response_format if present - use chat_structured() instead
        kwargs.pop("response_format", None)

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await acompletion(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_base=self.api_base,
                    timeout=self.timeout,
                    **kwargs,
                )

                choice = response.choices[0]
                usage = dict(response.usage) if response.usage else {}

                return LLMResponse(
                    content=choice.message.content or "",
                    model=response.model or self.model,
                    usage=usage,
                    finish_reason=choice.finish_reason or "stop",
                )

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if it's a retryable error (rate limit or transient server error)
                is_retryable = (
                    "429" in error_str or
                    "rate" in error_str or
                    "resource_exhausted" in error_str or
                    "quota" in error_str or
                    "503" in error_str or
                    "service unavailable" in error_str or
                    "unavailable" in error_str or
                    "502" in error_str or
                    "bad gateway" in error_str or
                    "504" in error_str or
                    "timeout" in error_str
                )

                if is_retryable and attempt < self.max_retries:
                    # Exponential backoff with jitter
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Retryable error (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    # Not a retryable error or max retries reached
                    raise LLMError(f"LLM request failed: {e}", original_error=e) from e

        # Should not reach here, but just in case
        raise LLMError(f"LLM request failed after {self.max_retries + 1} attempts: {last_error}", original_error=last_error)

    async def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_model: Type[T],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> T:
        """
        Send a chat completion request with structured output.

        Uses Instructor to ensure the response conforms to the Pydantic model.
        Automatically handles retries and validation errors.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            response_model: Pydantic model class for the expected response.
            temperature: Sampling temperature (default 0.3 for structured output).
            max_tokens: Maximum tokens to generate (None for model default).
            max_retries: Number of retries for validation failures (default 3).
            **kwargs: Additional arguments passed to LiteLLM.

        Returns:
            Instance of response_model with validated data.

        Raises:
            LLMError: If the request fails after all retries.

        Example:
            class CodeOutput(BaseModel):
                code: str
                language: str
                explanation: str

            result = await client.chat_structured(
                messages=[{"role": "user", "content": "Write hello world in Python"}],
                response_model=CodeOutput
            )
            print(result.code)
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                # Use instructor client for structured output
                response = await self._instructor_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=max_retries,  # Instructor's internal retries for validation
                    api_base=self.api_base,
                    timeout=self.timeout,
                    **kwargs,
                )

                logger.debug(f"Structured output successful: {response_model.__name__}")
                return response

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if it's a retryable error
                is_retryable = (
                    "429" in error_str or
                    "rate" in error_str or
                    "resource_exhausted" in error_str or
                    "quota" in error_str or
                    "503" in error_str or
                    "service unavailable" in error_str or
                    "unavailable" in error_str or
                    "502" in error_str or
                    "bad gateway" in error_str or
                    "504" in error_str or
                    "timeout" in error_str
                )

                if is_retryable and attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Retryable error in structured call (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Structured output failed: {e}")
                    raise LLMError(
                        f"Structured LLM request failed: {e}",
                        original_error=e
                    ) from e

        raise LLMError(
            f"Structured LLM request failed after {self.max_retries + 1} attempts: {last_error}",
            original_error=last_error
        )

    async def chat_structured_with_usage(
        self,
        messages: list[dict[str, str]],
        response_model: Type[T],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> tuple[T, dict[str, int]]:
        """
        Structured chat completion that also returns token usage.

        Uses Instructor's create_with_completion() to get both the parsed
        Pydantic model and the raw completion with usage data.

        Returns:
            Tuple of (response_model instance, usage dict).
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response, completion = await self._instructor_client.chat.completions.create_with_completion(
                    model=self.model,
                    messages=messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=max_retries,
                    api_base=self.api_base,
                    timeout=self.timeout,
                    **kwargs,
                )

                usage = dict(completion.usage) if completion.usage else {}
                return response, usage

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                is_retryable = (
                    "429" in error_str or
                    "rate" in error_str or
                    "resource_exhausted" in error_str or
                    "quota" in error_str or
                    "503" in error_str or
                    "service unavailable" in error_str or
                    "unavailable" in error_str or
                    "502" in error_str or
                    "bad gateway" in error_str or
                    "504" in error_str or
                    "timeout" in error_str
                )

                if is_retryable and attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Retryable error in structured+usage call (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise LLMError(
                        f"Structured+usage LLM request failed: {e}",
                        original_error=e
                    ) from e

        raise LLMError(
            f"Structured+usage LLM request failed after {self.max_retries + 1} attempts: {last_error}",
            original_error=last_error
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Send a streaming chat completion request.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate (None for model default).
            **kwargs: Additional arguments passed to LiteLLM.

        Yields:
            Content chunks as they arrive.

        Raises:
            LLMError: If the request fails.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await acompletion(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_base=self.api_base,
                    timeout=self.timeout,
                    stream=True,
                    **kwargs,
                )

                async for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return  # Success, exit retry loop

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                is_retryable = (
                    "429" in error_str or
                    "rate" in error_str or
                    "resource_exhausted" in error_str or
                    "quota" in error_str or
                    "503" in error_str or
                    "service unavailable" in error_str or
                    "unavailable" in error_str or
                    "502" in error_str or
                    "bad gateway" in error_str or
                    "504" in error_str or
                    "timeout" in error_str
                )

                if is_retryable and attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Retryable error in stream (attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise LLMError(f"LLM streaming request failed: {e}", original_error=e) from e

        raise LLMError(f"LLM streaming failed after {self.max_retries + 1} attempts: {last_error}", original_error=last_error)


# Default client instance using environment configuration
default_client = LLMClient()


async def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    **kwargs: Any,
) -> LLMResponse:
    """
    Convenience function for one-off chat completions.

    Uses the default client if no model is specified,
    or creates a temporary client with the specified model.

    Args:
        messages: List of message dicts with "role" and "content" keys.
        model: Optional model override.
        **kwargs: Additional arguments passed to LLMClient.chat().

    Returns:
        LLMResponse with content, model, usage, and finish_reason.
    """
    if model:
        client = LLMClient(model=model)
        return await client.chat(messages, **kwargs)
    return await default_client.chat(messages, **kwargs)


async def chat_structured(
    messages: list[dict[str, str]],
    response_model: Type[T],
    model: str | None = None,
    **kwargs: Any,
) -> T:
    """
    Convenience function for structured chat completions.

    Uses Instructor to ensure the response conforms to the Pydantic model.

    Args:
        messages: List of message dicts with "role" and "content" keys.
        response_model: Pydantic model class for the expected response.
        model: Optional model override.
        **kwargs: Additional arguments passed to LLMClient.chat_structured().

    Returns:
        Instance of response_model with validated data.

    Example:
        class Analysis(BaseModel):
            sentiment: str
            confidence: float
            keywords: list[str]

        result = await chat_structured(
            messages=[{"role": "user", "content": "Analyze: I love this product!"}],
            response_model=Analysis
        )
    """
    if model:
        client = LLMClient(model=model)
        return await client.chat_structured(messages, response_model, **kwargs)
    return await default_client.chat_structured(messages, response_model, **kwargs)


# ============================================================================
# Embedding Support (fastembed - local, no API needed)
# ============================================================================

# Embedding dimensions (BGE-base model)
EMBEDDING_DIM = 768

# Lazy-loaded embedding model (singleton)
_embedding_model = None
_embedding_lock = asyncio.Lock()


def _get_embedding_model():
    """Get or create the fastembed model (lazy loading)."""
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding
        # BGE-base: 768 dimensions, good quality, reasonable speed
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
        logger.info(f"Loading embedding model: {model_name}")
        _embedding_model = TextEmbedding(model_name=model_name)
        logger.info("Embedding model loaded")
    return _embedding_model


async def get_embedding(
    text: str,
    model: str | None = None,
) -> list[float]:
    """
    Get embedding vector for text using fastembed (local).

    Uses BAAI/bge-base-en-v1.5 by default (768 dimensions).
    Runs locally - no API calls, no costs, no rate limits.

    Args:
        text: Text to embed
        model: Ignored (uses configured model)

    Returns:
        Embedding vector as list of floats (768 dimensions)
    """
    try:
        # Run sync fastembed in thread pool to not block async loop
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            _compute_embedding_sync,
            text
        )
        return embedding
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return [0.0] * EMBEDDING_DIM


def _compute_embedding_sync(text: str) -> list[float]:
    """Synchronous embedding computation (runs in thread pool)."""
    model = _get_embedding_model()
    # fastembed returns generator, get first result
    embeddings = list(model.embed([text]))
    if embeddings:
        return embeddings[0].tolist()
    return [0.0] * EMBEDDING_DIM


def create_embedding_fn() -> Any:
    """
    Create an embedding function suitable for passing to services.

    Returns:
        Async function(text: str) -> list[float]
    """
    return get_embedding


def create_llm_fn() -> Any:
    """
    Create an LLM function suitable for passing to services.

    Returns:
        Async function(messages: list[dict], kwargs: dict) -> str
    """
    async def llm_fn(messages: list[dict], kwargs: dict) -> str:
        response = await default_client.chat(messages, **kwargs)
        return response.content

    return llm_fn


def create_structured_llm_fn() -> Any:
    """
    Create a structured LLM function that returns validated Pydantic models.

    Uses Instructor via LLMClient.chat_structured() for schema-enforced responses.

    Returns:
        Async function(messages, response_model, **kwargs) -> BaseModel instance
    """
    async def structured_llm_fn(
        messages: list[dict],
        response_model: type,
        **kwargs,
    ):
        return await default_client.chat_structured(messages, response_model, **kwargs)

    return structured_llm_fn

