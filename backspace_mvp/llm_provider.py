"""Provider selection; legacy NVIDIA remains available only by explicit choice."""
import os
from pathlib import Path
from dotenv import dotenv_values
from .gemini import GeminiProvider
from .nvidia import NvidiaProvider


def provider_class(env_file=Path('.env')):
    configured = os.environ.get('BACKSPACE_LLM_PROVIDER')
    if not configured:
        configured = dotenv_values(env_file).get('BACKSPACE_LLM_PROVIDER')
    name = (configured or 'gemini').strip().lower()
    if name == 'gemini': return GeminiProvider
    if name == 'nvidia': return NvidiaProvider
    raise ValueError('BACKSPACE_LLM_PROVIDER는 gemini 또는 nvidia여야 합니다.')


def create_provider(*, env_file=Path('.env'), task=None, timeout=None, usage_path=None, like=None):
    # An explicitly supplied provider wins over the workspace default. This
    # preserves existing injected runs and avoids switching vendors mid-job.
    cls = type(like) if production_provider(like) else provider_class(env_file)
    return cls(env_file=env_file, task=task, timeout=timeout, usage_path=usage_path)


def production_provider(provider):
    return isinstance(provider, (GeminiProvider, NvidiaProvider))
