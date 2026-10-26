import logging
import os

from comps_pipeline.config.schema import Settings
from comps_pipeline.llm.base import LLMClient, LLMResult
from comps_pipeline.llm.mock_client import MockLLMClient

log = logging.getLogger(__name__)

__all__ = ["LLMClient", "LLMResult", "MockLLMClient", "build_client"]


def build_client(settings: Settings) -> tuple[LLMClient | None, str, str | None]:
    """(client, mode label for the manifest, reason the LLM is unavailable).

    A missing Gemini key or model is reported clearly at startup; the run then continues
    without review (LLM_UNAVAILABLE) instead of failing.
    """
    cfg = settings.llm
    if not cfg.enabled:
        return None, "off", "LLM review disabled (llm.enabled is false or --llm off)"
    if cfg.provider == "mock":
        client = MockLLMClient(cfg.mock_mode)
        return client, client.model, None
    missing = [name for name in (cfg.api_key_env, cfg.model_env) if not os.environ.get(name)]
    if missing:
        msg = (
            f"Gemini selected but {', '.join(missing)} not set (put it in .env, see .env.example); "
            "continuing without LLM review"
        )
        log.error(msg)
        return None, "gemini (unavailable)", msg
    from comps_pipeline.llm.gemini_client import GeminiClient  # optional at runtime

    client = GeminiClient(
        api_key=os.environ[cfg.api_key_env],
        model=os.environ[cfg.model_env],
        temperature=cfg.temperature,
        timeout_seconds=cfg.timeout_seconds,
        attempts=cfg.api_attempts,
    )
    return client, client.model, None
