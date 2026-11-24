"""Model roles refer to actual Ollama models, not development assistants or search code."""
import json
import os
from pathlib import Path
import re

DEFAULT_ROLES = {'teacher': 'qwen2.5:3b', 'student': 'qwen2.5:0.5b',
                 'evaluator': 'qwen2.5:3b', 'researcher': 'qwen2.5:3b'}


def load_roles(path=None):
    configured = path or os.environ.get('TINY_RSI_MODEL_CONFIG')
    repository_config = Path(__file__).resolve().parents[3] / 'config' / 'models.json'
    if not configured and repository_config.is_file():
        configured = repository_config
    if configured:
        raw = Path(configured).read_bytes()
        if len(raw) > 65536:
            raise ValueError('Model configuration exceeds size limit')
        config = json.loads(raw)
    else:
        config = {'schema_version': 1, 'endpoint': 'http://127.0.0.1:11434',
                  'max_loaded_models': 1,
                  'roles': {role: {'model': model, 'context_tokens': 4096}
                            for role, model in DEFAULT_ROLES.items()}}
    if config.get('schema_version') != 1 or config.get('endpoint') != 'http://127.0.0.1:11434':
        raise ValueError('Only the guest-local Ollama endpoint is supported')
    if config.get('max_loaded_models') != 1 or set(config.get('roles', {})) != set(DEFAULT_ROLES):
        raise ValueError('Invalid resource budget or model roles')
    for role in config['roles'].values():
        if not isinstance(role, dict) or set(role) != {'model', 'context_tokens'}:
            raise ValueError('Invalid role configuration')
        if not isinstance(role['model'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', role['model']):
            raise ValueError('Invalid Ollama model name')
        if type(role['context_tokens']) is not int or not 512 <= role['context_tokens'] <= 8192:
            raise ValueError('Invalid context memory budget')
    return config


def default_model(role):
    if role not in DEFAULT_ROLES:
        raise ValueError('Unknown model role')
    return load_roles()['roles'][role]['model']
