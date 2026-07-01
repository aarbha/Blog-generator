from __future__ import annotations

import asyncio
import json
import time

from openai import OpenAI

from agents.context import BlogContext
from config import settings


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            if line.strip().startswith("```"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()
    return text


def _select_timeout(key_name: str) -> float:
    return {
        "WRITER": settings.writer_timeout,
        "ANALYZER": settings.analyzer_timeout,
        "CHEAP": settings.cheap_timeout,
    }.get(key_name, settings.writer_timeout)


def _select_model(key_name: str) -> str:
    return {
        "WRITER": settings.writer_model,
        "ANALYZER": settings.analyzer_model,
        "CHEAP": settings.cheap_model,
    }.get(key_name, settings.cheap_model)


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    timeout: float | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    client = OpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",
        timeout=timeout or 300,
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"keep_alive": "0s"},
    )
    content = response.choices[0].message.content
    if content is None:
        raise ValueError("LLM returned None content")
    return content


def _call_llm_groq(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    timeout: float | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> str:
    client = OpenAI(
        base_url=settings.groq_base_url,
        api_key=settings.groq_api_key,
        timeout=timeout or settings.groq_timeout,
    )
    response = client.chat.completions.create(
        model=model or settings.groq_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    if content is None:
        raise ValueError("Groq returned None content")
    return content


def _call_llm_routed(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    key_name: str | None = None,
    timeout: float | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    use_groq: bool = False,
) -> str:
    if use_groq and settings.groq_available:
        return _call_llm_groq(
            system_prompt, user_prompt,
            model=model or settings.groq_model,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return _call_llm(
        system_prompt, user_prompt,
        model=model or _select_model(key_name or "CHEAP"),
        timeout=timeout or _select_timeout(key_name or "CHEAP"),
        temperature=temperature,
        max_tokens=max_tokens,
    )


class GroqRateLimiter:
    def __init__(self, max_rpm: int = 25, max_tpm: int = 400000):
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self._request_times: list[float] = []
        self._tokens_used: int = 0
        self._window_start: float = time.time()
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, estimated_tokens: int = 0) -> None:
        if not settings.groq_available:
            return
        async with self._lock:
            now = time.time()
            self._request_times = [t for t in self._request_times if now - t < 60]
            elapsed = now - self._window_start
            if elapsed > 60:
                self._tokens_used = 0
                self._window_start = now
                elapsed = 0

            if len(self._request_times) >= self.max_rpm:
                sleep = self._request_times[0] + 60 - now
                if sleep > 0:
                    await asyncio.sleep(sleep)

            if self._tokens_used + estimated_tokens > self.max_tpm:
                sleep = self._window_start + 60 - now
                if sleep > 0:
                    await asyncio.sleep(sleep)

            self._request_times.append(time.time())
            self._tokens_used += estimated_tokens

    @staticmethod
    def estimate_tokens(system: str, user: str, max_tokens: int) -> int:
        return (len(system) + len(user)) // 4 + max_tokens


_groq_rate_limiter: GroqRateLimiter | None = None


def get_groq_rate_limiter() -> GroqRateLimiter:
    global _groq_rate_limiter
    if _groq_rate_limiter is None:
        _groq_rate_limiter = GroqRateLimiter(
            max_rpm=settings.groq_max_rpm,
            max_tpm=settings.groq_max_tpm,
        )
    return _groq_rate_limiter


def _warm_model(model: str, keep_alive: str = "60s"):
    try:
        client = OpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            timeout=30,
        )
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "."}],
            max_tokens=1,
            extra_body={"keep_alive": keep_alive},
        )
    except Exception:
        pass


async def preload_model(model: str, keep_alive: str = "60s"):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _warm_model, model, keep_alive)


class AgentError(Exception):
    def __init__(self, agent_name: str, reason: str, original: Exception | None = None):
        self.agent_name = agent_name
        self.reason = reason
        self.original = original
        super().__init__(f"[{agent_name}] {reason}")


class BaseAgent:
    name: str = "base"
    model: str = "qwen2.5:1.5b"
    key_name: str = "CHEAP"
    temperature: float = 0.7
    max_tokens: int = 8192

    @property
    def use_cloud(self) -> bool:
        return settings.agent_uses_cloud(self.name)

    def _source_limit(self) -> int:
        return settings.groq_source_limit if self.use_cloud else settings.max_source_chars

    def build_prompt(self, ctx: BlogContext) -> tuple[str, str]:
        raise NotImplementedError

    def parse_output(self, raw: str) -> dict | list:
        cleaned = _extract_json(raw)
        return json.loads(cleaned)

    def apply_result(self, ctx: BlogContext, parsed: dict | list) -> BlogContext:
        raise NotImplementedError

    async def run(self, ctx: BlogContext) -> BlogContext:
        try:
            system, user = self.build_prompt(ctx)
            if self.use_cloud:
                limiter = get_groq_rate_limiter()
                estimated = limiter.estimate_tokens(system, user, self.max_tokens)
                await limiter.wait_if_needed(estimated)
                raw = await asyncio.to_thread(
                    _call_llm_groq,
                    system, user,
                    None, None,
                    self.temperature, self.max_tokens,
                )
            else:
                raw = await asyncio.to_thread(
                    _call_llm,
                    system, user,
                    self.model,
                    _select_timeout(self.key_name),
                    self.temperature,
                    self.max_tokens,
                )
            parsed = self.parse_output(raw)
            return self.apply_result(ctx, parsed)
        except json.JSONDecodeError as e:
            raise AgentError(self.name, f"Failed to parse LLM output as JSON: {e}")
        except ValueError as e:
            raise AgentError(self.name, f"LLM returned invalid content: {e}")
        except Exception as e:
            raise AgentError(self.name, f"{type(e).__name__}: {e}", original=e)
