"""LLM 호출 래퍼. OpenAI 호환 Chat Completions 로 호출하므로 제공자는 설정만으로 바꾼다.
키가 없거나 실패하면 None 을 돌려주고, 호출부가 규칙 기반으로 대체한다."""
import logging
import os
import time
from typing import Optional, TypeVar

from pydantic import BaseModel

from . import config

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# 제공자: (API 키 환경 변수, base_url, 기본 모델 목록 - 앞 모델이 과부하·한도 초과면 다음 모델로 넘어간다)
PROVIDERS = {
    "gemini": (
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        # 무료 등급은 모델별로 과부하(503)가 잦아 여러 개를 순서대로 둔다.
        ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"),
    ),
    "openai": ("OPENAI_API_KEY", None, ("gpt-6.1-sol",)),
}
TIMEOUT_S = 45.0  # 모델 하나가 이 시간 안에 답하지 않으면 끊고 다음 모델로 넘어간다
BUDGET_S = 75.0  # 호출 한 번에 모델을 바꿔 가며 기다리는 총 시간. 넘으면 규칙 기반으로 넘어간다
COOLDOWN_S = 120.0  # 응답이 없던 모델을 다시 시도하기까지 건너뛰는 시간

_client = None
_models: tuple[str, ...] = ()
_cooldown: dict[str, float] = {}  # 모델 -> 다시 시도할 수 있는 시각
_last_model = ""
_disabled = config.LLM_MODE == "off"


def name() -> str:
    """응답의 engine 표시에 쓰는 이름 (마지막으로 응답한 모델)."""
    return f"{config.LLM_PROVIDER}:{_last_model}"


def _get_client():
    global _client, _models, _disabled
    if _disabled:
        return None
    if _client is None:
        provider = PROVIDERS.get(config.LLM_PROVIDER)
        if provider is None:
            log.warning("알 수 없는 ROUTEFIT_LLM_PROVIDER=%s, LLM 을 쓰지 않습니다", config.LLM_PROVIDER)
            _disabled = True
            return None
        key_env, base_url, default_models = provider
        api_key = os.getenv(key_env, "").strip()
        if not api_key:
            log.warning("%s 가 비어 있어 LLM 을 쓰지 않습니다", key_env)
            _disabled = True
            return None
        from openai import OpenAI

        # 재시도는 SDK 대신 아래의 모델 전환·쿨다운으로 처리한다.
        _client = OpenAI(api_key=api_key, base_url=base_url, timeout=TIMEOUT_S, max_retries=0)
        _models = tuple(m.strip() for m in config.LLM_MODEL.split(",") if m.strip()) or default_models
    return _client


def structured(system: str, user: str, schema: type[T]) -> Optional[T]:
    """schema 로 검증된 구조화 응답. 사용할 수 없으면 None."""
    global _disabled, _last_model
    client = _get_client()
    if client is None:
        return None
    import openai

    deadline = time.monotonic() + BUDGET_S
    for model in _models * 2:  # 과부하(503)는 대개 잠깐이라 목록을 두 바퀴 돈다
        remaining = deadline - time.monotonic()
        if remaining < 5:
            break
        if time.monotonic() < _cooldown.get(model, 0):
            continue
        try:
            completion = client.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                timeout=min(TIMEOUT_S, remaining),
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            log.warning("LLM 인증 실패, 이후 요청은 규칙 기반으로 처리: %s", e)
            _disabled = True
            return None
        except openai.APIConnectionError as e:
            # 시간 초과 · 연결 실패: 오래 기다린 뒤에야 알 수 있으므로 한동안 건너뛴다
            log.warning("%s 응답 없음, %d초 동안 건너뜀: %s", model, COOLDOWN_S, e)
            _cooldown[model] = time.monotonic() + COOLDOWN_S
            continue
        except (openai.RateLimitError, openai.InternalServerError) as e:
            # 한도 초과 · 서버 과부하: 곧바로 실패하므로 다음 모델을 시도한다
            log.warning("%s 사용 불가, 다음 모델로: %s", model, e)
            continue
        except Exception as e:
            log.warning("LLM 호출 실패(%s), 이번 요청은 규칙 기반으로 처리: %s", model, e)
            return None
        _last_model = model
        parsed = completion.choices[0].message.parsed
        if parsed is None:  # 모델이 응답을 거절한 경우
            log.warning("LLM 이 구조화 응답을 돌려주지 않음(%s)", model)
        return parsed
    log.warning("지금 쓸 수 있는 LLM 모델이 없어 이번 요청은 규칙 기반으로 처리")
    return None
