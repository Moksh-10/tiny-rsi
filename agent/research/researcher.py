"""Guest-local Ollama proposes data-only experiments; it never emits executable code."""
from __future__ import annotations

from contextlib import contextmanager
import signal
import threading
import time
import hashlib
import json
import urllib.request
from pathlib import Path

from .environment import require_worker


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Inference redirects are forbidden")


@contextmanager
def request_deadline(seconds):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Researcher requests must run in the main thread")
    def expired(signum, frame):
        raise TimeoutError("Researcher absolute request deadline exceeded")
    old = signal.signal(signal.SIGALRM, expired)
    previous = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, min(seconds, previous[0]) if previous[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        if previous[0]:
            signal.setitimer(signal.ITIMER_REAL, max(.000001, previous[0] - (time.monotonic()-started)), previous[1])


def validation_feedback_only(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if "holdout" in str(key).lower() or "heldout" in str(key).lower():
                raise ValueError("Held-out results must not enter feedback")
            if key in ("split", "evaluation_scope") and item in ("eval", "heldout", "holdout", "held-out-layouts"):
                raise ValueError("Held-out results must not enter feedback")
            validation_feedback_only(item)
    elif isinstance(value, list):
        for item in value:
            validation_feedback_only(item)

MODEL = 'qwen2.5:3b'
ENDPOINT = 'http://127.0.0.1:11434'
LIMIT = 1 << 20
CHOICES = {
    'architecture': ['tree', 'mlp'],
    'depth': [2, 4, 6, 8, 10],
    'min_leaf': [1, 2, 4],
    'hidden_size': [8, 16],
    'epochs': [20, 50],
    'learning_rate': [0.01, 0.03, 0.1],
}
SCHEMA = {'type': 'object', 'additionalProperties': False,
          'properties': {k: {'type': 'string' if k == 'architecture' else 'number', 'enum': v}
                         for k, v in CHOICES.items()}, 'required': list(CHOICES)}


def validate_proposal(proposal):
    if not isinstance(proposal, dict) or set(proposal) != set(CHOICES):
        raise ValueError('Experiment must contain exactly the allowed configuration fields')
    for key, choices in CHOICES.items():
        if isinstance(proposal[key], bool) or proposal[key] not in choices:
            raise ValueError(f'Invalid experiment choice: {key}')
    return dict(proposal)


def training_config(proposal, seed=0):
    p = validate_proposal(proposal)
    return {'architecture': p['architecture'], 'depths': [int(p['depth'])],
            'min_leaves': [int(p['min_leaf'])], 'hidden_sizes': [int(p['hidden_size'])],
            'epochs': [int(p['epochs'])], 'learning_rates': [p['learning_rate']],
            'seed': seed, 'max_rows': 10000, 'max_candidates': 1}


class OllamaResearcher:
    def __init__(self, model=MODEL, timeout=120, token_budget=12000):
        require_worker()
        if not 1 <= timeout <= 180 or not 1024 <= token_budget <= 100000:
            raise ValueError("Invalid researcher budget")
        self.model, self.timeout, self.token_budget = model, timeout, token_budget
        self.tokens = 0
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def api(self, path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(ENDPOINT + path, data=payload,
                                     headers={'Content-Type': 'application/json'})
        with request_deadline(self.timeout):
            with self.client.open(req, timeout=self.timeout) as response:
                raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Ollama response exceeds limit')
        return json.loads(raw)

    def identity(self):
        tags = self.api('/api/tags')
        for model in tags.get('models', []):
            if model['name'] == self.model or model['name'] == self.model + ':latest':
                return {'name': model['name'], 'digest': model['digest'],
                        'ollama_version': self.api('/api/version').get('version')}
        raise ValueError('Research model is not installed inside this guest')

    def propose(self, summary, audit_path):
        # Only training/validation aggregates enter this prompt. No holdout results are supplied.
        if not isinstance(summary, dict):
            raise ValueError("Research summary must be an object")
        allowed = {"goal", "game", "round", "training_rows", "experiments", "incumbent_validation", "budget"}
        if set(summary) - allowed:
            raise ValueError("Unknown research feedback fields")
        validation_feedback_only(summary)
        encoded = json.dumps(summary, sort_keys=True)
        if len(encoded) > 16000:
            raise ValueError('Research summary exceeds prompt budget')
        if 'heldout' in summary or 'holdout' in summary:
            raise ValueError('Held-out results must not enter the researcher feedback loop')
        if self.tokens + len(encoded) + 1024 > self.token_budget:
            raise ValueError('Researcher token budget exhausted')
        body = {'model': self.model, 'stream': False, 'format': SCHEMA,
                'messages': [
                    {'role': 'system', 'content':
                     'You are a compute-constrained game-policy researcher. Propose one allowed '
                     'training experiment as JSON. The student is a tiny tree or neural MLP, not '
                     'a language model. Optimize validation game success/progress under fixed '
                     'execution budgets. Prefer an experiment different from prior attempts. '
                     'Do not output code, paths, shell commands, or commentary.'},
                    {'role': 'user', 'content': encoded}],
                'options': {'num_ctx': 4096, 'num_predict': 192, 'temperature': 0.2,
                            'seed': len(summary.get('experiments', [])), 'num_thread': 4},
                'keep_alive': '5m'}
        response = self.api('/api/chat', body)
        used = int(response.get('prompt_eval_count', 0)) + int(response.get('eval_count', 0))
        self.tokens += used
        raw = response.get('message', {}).get('content', '')
        audit = {'request': body, 'response': response, 'tokens_used_total': self.tokens,
                 'summary_sha256': hashlib.sha256(encoded.encode()).hexdigest()}
        target = Path(audit_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x') as output:
            json.dump(audit, output, sort_keys=True, indent=2)
        return validate_proposal(json.loads(raw))
