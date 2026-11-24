"""Bounded guest-only Ollama gameplay actor.

Teacher and student roles are actual configurable Ollama models. Fixed native
physics remains authoritative for reward and success; role labels do not turn a
model's self-assessment into a game score. No model output executes as code.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any

from .environment import GameEnvironment, require_worker
from .researcher import OllamaResearcher
from .models import default_model, load_roles
from .prompts import messages_for_state, PROMPT_VERSION

DEFAULT_MODEL = 'qwen2.5:3b'
MAX_ACTION_BYTES = 16384
TICK_CHOICES = (15, 30, 60, 120)
ROLES = ('teacher', 'student', 'evaluator')


@contextmanager
def episode_deadline(seconds: float):
    """Absolute wall deadline, preserving any enclosing POSIX interval timer."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Actor execution requires the main thread')
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expired(signum, frame):
        raise TimeoutError('Actor episode wall-time budget exhausted')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL,
                    min(seconds, previous_timer[0]) if previous_timer[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0]:
            elapsed = time.monotonic() - started
            signal.setitimer(signal.ITIMER_REAL,
                            max(.000001, previous_timer[0] - elapsed), previous_timer[1])


def action_from(content: str) -> dict:
    """Exactly one finite JSON object, with no duplicate keys or code fences."""
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_ACTION_BYTES:
        raise ValueError('Model action must be a bounded JSON string')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f'Nonfinite JSON constant: {value}')
    result = json.loads(content, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(result, dict):
        raise ValueError('Model action must be a JSON object')
    # JSON exponent overflow (e.g. 1e999) is not a parse_constant callback.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Nonfinite action number')
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)
    finite(result)
    return result


def compact(value: Any) -> Any:
    """Copy only model-facing geometry; trajectories retain full precision."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def action_schema(game: str, state: dict) -> dict:
    def variant(kind, aim=False, hold=False):
        properties = {
            'type': {'type': 'string', 'const': kind},
            'ticks': {'type': 'integer', 'enum': list(TICK_CHOICES)},
        }
        required = ['type', 'ticks']
        if aim:
            limit = 3.15 if hold else 95
            properties.update({key: {'type': 'number', 'minimum': -limit, 'maximum': limit}
                               for key in ('x', 'y')})
            required += ['x', 'y']
        if hold:
            properties['hold'] = {'type': 'boolean'}
            required.append('hold')
        return {'type': 'object', 'properties': properties,
                'required': required, 'additionalProperties': False}
    if game == 'getting-over-it':
        return variant('hammer', aim=True, hold=True)
    if game != 'angry-birds':
        raise ValueError('Unsupported game')
    observation = state.get('observation', {})
    choices = [variant('wait')]
    if observation.get('phase') == 'aiming':
        choices.append(variant('launch', aim=True))
    if observation.get('ability_ready'):
        choices.append(variant('ability'))
    return choices[0] if len(choices) == 1 else {'anyOf': choices}


def _instructions(game: str, description: dict) -> str:
    rules = description.get('angry_birds' if game == 'angry-birds' else 'getting_over_it', {})
    result = ('Control the game using exactly one JSON action matching the provided schema. '
              'No commentary or code. Each tick is 1/60 simulated second. Choices are limited '
              'to currently available actions. Rules: ' + json.dumps(rules, sort_keys=True))
    if game == 'angry-birds':
        return result + (
            ' Goal: hit all pigs. The slingshot is at [210,438]. Pull LEFT (negative x) '
            'and DOWN (positive y) to shoot RIGHT and UP. Example valid launch: '
            '{"type":"launch","x":-75,"y":45,"ticks":120}. Adjust aim based on targets '
            'and previous results. Pull length cannot exceed 95. While flying, wait 120 ticks '
            'to observe the trajectory or activate an available ability. Never launch '
            'again until phase is aiming. Prefer ticks=120 for waits.')
    return result + (
        ' Goal: climb to the summit. Aim x,y relative to your shoulder: right is positive x, '
        'up is positive y. Reach is 3.15m. Reach toward terrain, hold to anchor, then '
        'change aim to push or pull your body; release to swing. A grip must touch terrain. '
        'Use ticks=15 or 30 to observe and adjust. Example action shape: '
        '{"type":"hammer","x":3,"y":-1,"hold":true,"ticks":30}.')


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _token_count(response: dict, name: str) -> int:
    value = response.get(name)
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise ValueError(f'Ollama omitted or returned invalid {name}')
    return value


def _done(state) -> bool:
    return bool(state and (state.get('terminated') or state.get('truncated')))


def play_episode(executable: str, output: str, *, model=DEFAULT_MODEL,
                 game='angry-birds', level=0, role='student', steps=32,
                 tokens=30000, timeout=1200.0) -> dict:
    """Run a bounded real Ollama episode only after the sealed-worker guard.

    Output is exclusive mode0600, fsynced after every event. Errors preserve a
    metadata/error/summary trace and are reflected by summary.status='error'.
    A completed inference can cross the remaining token budget once; there are
    no hidden retries or concurrent calls. Subsequent inference then stops.
    """
    if game not in ('angry-birds', 'getting-over-it') or role not in ROLES:
        raise ValueError('Unsupported game or model role')
    if type(level) is not int or not 0 <= level < (12 if game == 'angry-birds' else 1):
        raise ValueError('Invalid game level')
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError('steps must be in [1,10000]')
    if type(tokens) is not int or not 1024 <= tokens <= 10_000_000:
        raise ValueError('tokens must be in [1024,10000000]')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ValueError('timeout must be in (0,86400] seconds')
    if not isinstance(model, str) or not model or len(model) > 256:
        raise ValueError('A bounded Ollama model name is required')
    require_worker()  # Before identity queries, engine reads/spawns or trace output.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as trace:
        def record(event):
            trace.write(json.dumps(event, sort_keys=True, allow_nan=False) + '\n')
            trace.flush()
            os.fsync(trace.fileno())
        started = time.monotonic()
        options = {'num_ctx': load_roles()['roles'][role]['context_tokens'], 'num_predict': 256, 'temperature': 0,
                   'seed': 0, 'num_thread': 4}
        metadata = {
            'event': 'metadata', 'protocol': 1, 'role': role, 'model': model,
            'revision': os.environ.get('TINY_RSI_REVISION', 'development'),
            'engine_sha256': None, 'digest': None, 'ollama_version': None,
            'capabilities': None, 'game': game, 'level': level,
            'track': 'structured-state', 'prompt_version': PROMPT_VERSION, 'started': datetime.now(timezone.utc).isoformat(),
            'max_steps': steps, 'token_budget': tokens, 'timeout_seconds': timeout,
            'options': options,
        }
        written_metadata = False
        state = None
        engine = None
        used = invalid = executed = decisions = 0
        reason = 'decision_limit'
        status = 'ok'
        error = None
        try:
            with episode_deadline(timeout):
                metadata['engine_sha256'] = _sha256(executable)
                client = OllamaResearcher(model=model, timeout=min(180, max(1.0, timeout)),
                                          token_budget=min(100000, max(1024, tokens)))
                identity = client.identity()
                if not isinstance(identity, dict) or not isinstance(identity.get('digest'), str) or not identity['digest']:
                    raise ValueError('Ollama model identity has no digest')
                if len(identity['digest']) > 256:
                    raise ValueError('Ollama model digest exceeds metadata limit')
                resolved_name = identity.get('name', model)
                version = identity.get('ollama_version')
                if not isinstance(resolved_name, str) or len(resolved_name) > 256:
                    raise ValueError('Invalid resolved model name')
                if version is not None and (not isinstance(version, str) or len(version) > 128):
                    raise ValueError('Invalid Ollama version')
                metadata['digest'] = identity['digest']
                metadata['resolved_model'] = resolved_name
                metadata['ollama_version'] = version
                details = client.api('/api/show', {'model': model})
                capabilities = details.get('capabilities', [])
                if not isinstance(capabilities, list) or len(capabilities) > 64 or any(not isinstance(c, str) or len(c) > 256 for c in capabilities):
                    raise ValueError('Invalid model capabilities')
                metadata['capabilities'] = capabilities
                record(metadata)
                written_metadata = True
                engine = GameEnvironment(executable, game, level)
                description = engine.request({'op': 'describe'})
                engine.reset(seed=0)
                state = copy.deepcopy(engine.state)
                reset_request = {'op': 'reset', 'game': game, 'level': level}
                record({'event': 'reset', 'request': reset_request, 'response': state})
                system = messages_for_state(game,state)[0]['content']
                last = ''
                for decision in range(steps):
                    if _done(state):
                        reason = 'environment_finished'
                        break
                    messages = messages_for_state(game,state)
                    observation = messages[1]['content']
                    if used + len(system) + len(observation) + len(last) + 1024 > tokens:
                        reason = 'token_budget'
                        break
                    if last:
                        messages[1]['content'] += '\nRejected: ' + last[:256]
                    body = {
                        'model': model, 'stream': False, 'format': action_schema(game, state),
                        'messages': messages,
                        'options': options, 'keep_alive': '5m',
                    }
                    decision_started = time.monotonic()
                    response = client.api('/api/chat', body)
                    prompt_tokens = _token_count(response, 'prompt_eval_count')
                    completion_tokens = _token_count(response, 'eval_count')
                    used += prompt_tokens + completion_tokens
                    raw = response.get('message', {}).get('content', '')
                    action = native_response = None
                    action_error = None
                    if not isinstance(raw, str):
                        action_error = 'Ollama message.content must be a string'
                        raw = repr(raw)[:MAX_ACTION_BYTES]
                    else:
                        try:
                            action = action_from(raw)
                        except (ValueError, TypeError, RecursionError) as exc:
                            action_error = str(exc)[:1024]
                    duration = response.get('total_duration')
                    if type(duration) is not int or duration < 0:
                        duration = None
                    if action_error is None:
                        try:
                            native_response = engine.request({'op': 'act', 'action': action})
                        except ValueError as exc:
                            # Locally rejected serialization/size did not reach the engine.
                            action_error = str(exc)[:1024]
                    entry = {
                        'event': 'step', 'step': decision, 'raw_action': raw,
                        'action': action, 'response': native_response,
                        'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                        'ollama_duration_ns': duration,
                        'wall_ms': round((time.monotonic() - decision_started) * 1000),
                    }
                    if action_error is not None:
                        entry['error'] = action_error
                    record(entry)
                    decisions += 1
                    accepted = native_response is not None and native_response.get('ok') is True
                    if not accepted:
                        invalid += 1
                        last = json.dumps({'action': raw, 'error': action_error or native_response.get('error', 'Rejected action')}, sort_keys=True)
                        if invalid >= 5:
                            reason = 'invalid_action_limit'
                            break
                    else:
                        state = copy.deepcopy(native_response)
                        engine.state = copy.deepcopy(native_response)
                        executed += 1
                        last = ''
                    if _done(state):
                        reason = 'environment_finished'
                        break
                    if used >= tokens:
                        reason = 'token_budget'
                        break
        except KeyboardInterrupt as exc:
            status, reason, error = 'error', 'interrupted', 'KeyboardInterrupt'
        except TimeoutError as exc:
            status, reason, error = 'error', 'wall_timeout', f'{type(exc).__name__}: {exc}'[:1024]
        except Exception as exc:
            status, reason, error = 'error', 'runtime_error', f'{type(exc).__name__}: {exc}'[:1024]
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception as exc:
                    if error is None:
                        status, reason, error = 'error', 'cleanup_error', f'{type(exc).__name__}: {exc}'[:1024]
        if not written_metadata:
            record(metadata)
        if error is not None:
            record({'event': 'error', 'error': error, 'reason': reason,
                    'decisions': decisions, 'tokens': used})
        summary = {
            'event': 'summary', 'status': status, 'reason': reason, 'role': role,
            'executed_actions': executed, 'invalid_actions': invalid, 'decisions': decisions,
            'tokens': used, 'elapsed_ms': round((time.monotonic() - started) * 1000),
            'final': state,
        }
        record(summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', required=True, help='Trusted C++ environment executable')
    parser.add_argument('--model', help='Overrides the configured Ollama model for this role')
    parser.add_argument('--role', choices=ROLES, default='student')
    parser.add_argument('--game', choices=('angry-birds', 'getting-over-it'), default='angry-birds')
    parser.add_argument('--level', type=int, default=0)
    parser.add_argument('--steps', type=int, default=32)
    parser.add_argument('--tokens', type=int, default=30000)
    parser.add_argument('--timeout', type=float, default=1200, help='Whole episode seconds')
    parser.add_argument('--output', required=True, help='New JSONL trace, never overwritten')
    args = parser.parse_args()
    try:
        result = play_episode(args.env, args.output, model=args.model or default_model(args.role), role=args.role,
                              game=args.game, level=args.level, steps=args.steps,
                              tokens=args.tokens, timeout=args.timeout)
    except Exception as exc:
        print(f'Actor error: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
