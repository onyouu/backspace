"""Provider selection; legacy NVIDIA remains available only by explicit choice."""
import os
from pathlib import Path
from dotenv import dotenv_values
from .gemini import GeminiProvider
from .nvidia import NvidiaProvider
from .chatgpt_plan import ChatGPTPlanProvider


def provider_class(env_file=Path('.env')):
    values = dotenv_values(env_file)
    configured = os.environ.get('BACKSPACE_LLM_PROVIDER') or values.get('BACKSPACE_LLM_PROVIDER')
    free_llm_only = (os.environ.get('BACKSPACE_FREE_LLM_ONLY') or values.get('BACKSPACE_FREE_LLM_ONLY') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    name = (configured or 'gemini').strip().lower()
    from .chatgpt_auth import status
    if status(Path(env_file).resolve().parent)['enabled']: name='chatgpt_plan'
    if name == 'chatgpt_plan': return ChatGPTPlanProvider
    if name == 'gemini': return GeminiProvider
    if name == 'nvidia':
        if free_llm_only:
            raise ValueError('무료 API 모드에서는 NVIDIA 호출을 사용하지 않습니다.')
        return NvidiaProvider
    raise ValueError('BACKSPACE_LLM_PROVIDER는 gemini 또는 nvidia여야 합니다.')


def create_provider(*, env_file=Path('.env'), task=None, timeout=None, usage_path=None, like=None):
    # An explicitly supplied provider wins over the workspace default. This
    # preserves existing injected runs and avoids switching vendors mid-job.
    cls = type(like) if production_provider(like) else provider_class(env_file)
    return cls(env_file=env_file, task=task, timeout=timeout, usage_path=usage_path)


def production_provider(provider):
    return isinstance(provider, (GeminiProvider, NvidiaProvider, ChatGPTPlanProvider))
