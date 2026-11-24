"""Collect language-distillation labels from a REAL planner-assisted Ollama model.

The native simulator remains authoritative. PlanningPolicy is a charged physics
TOOL, never the teacher model. Only accepted final JSON actions actually returned
by Ollama become training rows. Public student prompts contain no planner answer.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from .actor import action_from, action_schema, episode_deadline, _token_count
from .environment import GameEnvironment, require_worker
from .models import default_model, load_roles
from .planner import PlanningPolicy
from .prompts import messages_for_state, PROMPT_VERSION
from .researcher import OllamaResearcher

SOURCE = 'ollama-teacher-with-planner-tool'
MAX_INVALID = 5


def file_sha256(filename):
    digest = hashlib.sha256()
    with open(filename, 'rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _done(state):
    return bool(state and (state.get('terminated') or state.get('truncated')))


def _public_messages(game, state):
    """Exactly the shared student inference prompt; no planner answer or level ID."""
    return copy.deepcopy(messages_for_state(game, state))


def _teacher_messages(student_messages, recommendation, cost, last_error=None):
    result = copy.deepcopy(student_messages)
    result[0]['content'] += (
        ' A bounded physics-planning tool is provided as assistance. Review its '
        'recommendation against the current observation and return your final full '
        'motor-action JSON. You may accept or change it. You are the Ollama teacher '
        'model; the search tool is not a model. Do not output paths, code, or commentary.')
    tool = {'tool': 'plan_action', 'selection': 'harness-provided',
            'recommendation': recommendation, 'charged_oracle_cost': cost}
    if last_error:
        tool['previous_rejected_model_action'] = last_error
    result.append({'role': 'user', 'content': json.dumps(tool, sort_keys=True,
                                                       separators=(',', ':'), allow_nan=False)})
    return result


def _cost_delta(before, after):
    return {key: value - before.get(key, 0) for key, value in after.items()
            if type(value) in (int, float) and type(before.get(key, 0)) in (int, float)}


def collect(executable, game, output, *, model=None, level=0, steps=60, seed=0,
            tokens=100000, timeout=1800.0, candidate_budget=1200,
            tick_budget=2000000, samples=24, horizon=3):
    """Collect train-only real-model labels with a charged planner tool.

    A completed inference may exceed the remaining token limit once; no subsequent
    inference is issued. Output is exclusive mode0600 and flushed/fsynced per event.
    Invalid model actions are audited but NEVER become student training examples.
    """
    if game not in ('angry-birds', 'getting-over-it'):
        raise ValueError('Unsupported game')
    if type(level) is not int or not 0 <= level < (6 if game == 'angry-birds' else 1):
        raise ValueError('Teacher training collection is limited to birds0-5/ascent0')
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError('steps must be in [1,10000]')
    if type(tokens) is not int or not 1024 <= tokens <= 10000000:
        raise ValueError('tokens must be in [1024,10000000]')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ValueError('Invalid absolute episode deadline')
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Invalid deterministic planner seed')
    if type(candidate_budget) is not int or not 1 <= candidate_budget <= 100000:
        raise ValueError('Invalid planner candidate budget')
    if type(tick_budget) is not int or not 120 <= tick_budget <= 100000000:
        raise ValueError('Invalid planner tick budget')
    if type(samples) is not int or not 1 <= samples <= 256 or type(horizon) is not int or not 1 <= horizon <= 8:
        raise ValueError('Invalid planner sample/horizon budget')
    require_worker()  # Before engine reads, model queries, file creation or spawning.
    model = model or default_model('teacher')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', model):
        raise ValueError('Invalid teacher model name')
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as trace:
        def write(event):
            trace.write(json.dumps(event, sort_keys=True, allow_nan=False) + '\n')
            trace.flush()
            os.fsync(trace.fileno())
        started = time.monotonic()
        metadata = {'event': 'metadata', 'protocol': 1, 'source': SOURCE,
                    'runtime': 'ollama', 'role': 'teacher', 'model': model,
                    'game': game, 'level': level, 'split': 'train',
                    'track': 'structured-state-tool-assisted', 'prompt_version': PROMPT_VERSION,
                    'started': datetime.now(timezone.utc).isoformat(),
                    'revision': os.environ.get('TINY_RSI_REVISION', 'development'),
                    'engine_sha256': None, 'digest': None,
                    'planner_seed': seed, 'environment_seed': None,
                    'candidate_budget': candidate_budget, 'tick_budget': tick_budget,
                    'samples': samples, 'horizon': horizon, 'max_steps': steps,
                    'token_budget': tokens, 'timeout_seconds': timeout}
        engine = planner = state = None
        written_metadata = False
        executed = invalid = decisions = used = 0
        reason, status, error = 'decision_limit', 'ok', None
        try:
            with episode_deadline(timeout):
                metadata['engine_sha256'] = file_sha256(executable)
                metadata['collector_sha256'] = file_sha256(__file__)
                metadata['planner_source_sha256'] = file_sha256(Path(__file__).with_name('planner.py'))
                client = OllamaResearcher(model=model, timeout=min(180, max(1.0, timeout)),
                                          token_budget=min(100000, max(1024, tokens)))
                identity = client.identity()
                if not isinstance(identity, dict) or not isinstance(identity.get('digest'), str) or not re.fullmatch(r'[0-9a-f]{64}', identity['digest']):
                    raise ValueError('Teacher model has no valid installed digest')
                teacher = {'runtime': 'ollama', 'role': 'teacher',
                           'model': identity.get('name', model), 'digest': identity['digest']}
                if not isinstance(teacher['model'], str) or len(teacher['model']) > 128:
                    raise ValueError('Invalid resolved teacher identity')
                metadata.update(digest=teacher['digest'], resolved_model=teacher['model'],
                                ollama_version=identity.get('ollama_version'))
                options = {'num_ctx': load_roles()['roles']['teacher']['context_tokens'],
                           'num_predict': 256, 'temperature': 0, 'seed': seed, 'num_thread': 4}
                metadata['options'] = options
                episode_id = hashlib.sha256((str(output) + teacher['digest'] + metadata['started']).encode()).hexdigest()[:24]
                metadata['episode_id'] = episode_id
                write(metadata)
                written_metadata = True
                engine = GameEnvironment(executable, game, level)
                description = engine.request({'op': 'describe'})
                engine.reset(seed=0)
                state = copy.deepcopy(engine.state)
                planner = PlanningPolicy(executable, game, level=level, seed=seed,
                                         candidate_budget=candidate_budget, tick_budget=tick_budget,
                                         samples=samples, horizon=horizon)
                if not callable(getattr(planner, 'label', None)) or not callable(getattr(planner, 'observe_action', None)):
                    raise RuntimeError('PlanningPolicy requires label/observe_action APIs')
                write({'event': 'reset', 'request': {'op': 'reset', 'game': game, 'level': level},
                       'response': state})
                last_error = None
                for step in range(steps):
                    if _done(state):
                        reason = 'environment_finished'
                        break
                    before = copy.deepcopy(state)
                    before_stats = copy.deepcopy(planner.stats)
                    recommendation = planner.label(before['observation'], before['info'])
                    cost = _cost_delta(before_stats, planner.stats)
                    student_prompt = _public_messages(game, before)
                    teacher_prompt = _teacher_messages(student_prompt, recommendation, cost, last_error)
                    schema = action_schema(game, before)
                    encoded = json.dumps(teacher_prompt, sort_keys=True, separators=(',', ':'))
                    write({'event': 'planner_tool', 'step': step, 'tool': 'plan_action',
                           'recommendation': recommendation, 'cost': cost,
                           'cumulative_stats': copy.deepcopy(planner.stats)})
                    # Conservative preflight; logs distinguish tool compute from model compute.
                    if used + len(encoded.encode()) + 1024 > tokens:
                        reason = 'token_budget'
                        break
                    body = {'model': model, 'stream': False, 'format': schema,
                            'messages': teacher_prompt, 'options': options, 'keep_alive': '5m'}
                    response_id = f'{episode_id}:{step}'
                    write({'event': 'model_request', 'response_id': response_id,
                           'role': 'teacher', 'request': body,
                           'request_sha256': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()})
                    response = client.api('/api/chat', body)
                    prompt_tokens = _token_count(response, 'prompt_eval_count')
                    completion_tokens = _token_count(response, 'eval_count')
                    used += prompt_tokens + completion_tokens
                    decisions += 1
                    raw = response.get('message', {}).get('content', '')
                    # Keep actual motor text and public API metrics, not hidden thinking fields.
                    write({'event': 'model_response', 'response_id': response_id,
                           'teacher': teacher, 'content': raw, 'prompt_tokens': prompt_tokens,
                           'completion_tokens': completion_tokens,
                           'total_duration': response.get('total_duration'),
                           'done_reason': response.get('done_reason')})
                    action = native_response = None
                    rejection = None
                    try:
                        action = action_from(raw)
                        native_response = engine.request({'op': 'act', 'action': action})
                        if not native_response['ok']:
                            rejection = native_response.get('error', 'Engine rejected model action')
                    except ValueError as exc:
                        rejection = str(exc)
                    if rejection is not None:
                        invalid += 1
                        last_error = {'content': raw, 'error': rejection}
                        write({'event': 'rejected_action', 'step': step, 'response_id': response_id,
                               'action': action, 'response': native_response, 'error': rejection})
                        # No observe_action call: rejected model actions never enter the prefix.
                        if invalid >= MAX_INVALID:
                            reason = 'invalid_action_limit'
                            break
                    else:
                        planner.observe_action(action)  # AFTER native acceptance, using actual model action.
                        engine.state = copy.deepcopy(native_response)
                        state = copy.deepcopy(native_response)
                        executed += 1
                        last_error = None
                        write({'event': 'step', 'step': step, 'source': SOURCE,
                               'game': game, 'level': level, 'split': 'train', 'episode_id': episode_id,
                               'observation': before['observation'], 'info': before['info'],
                               'student_prompt': student_prompt, 'teacher_prompt': teacher_prompt,
                               'prompt_version': PROMPT_VERSION,
                               'teacher_response': raw, 'teacher': teacher,
                               'response_id': response_id, 'action': action, 'response': state,
                               'planner_recommendation': recommendation,
                               'verification': {'action_valid': True,
                                                'engine_sha256': metadata['engine_sha256'],
                                                'recommendation_executed': action == recommendation}})
                    if _done(state):
                        reason = 'environment_finished'
                        break
                    if used >= tokens:
                        reason = 'token_budget'
                        break
        except KeyboardInterrupt:
            status, reason, error = 'error', 'interrupted', 'KeyboardInterrupt'
        except TimeoutError as exc:
            status, reason, error = 'error', 'wall_timeout', f'{type(exc).__name__}: {exc}'[:1024]
        except Exception as exc:
            status, reason, error = 'error', 'runtime_error', f'{type(exc).__name__}: {exc}'[:1024]
        finally:
            for resource in (planner, engine):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception as exc:
                        if error is None:
                            status, reason, error = 'error', 'cleanup_error', f'{type(exc).__name__}: {exc}'[:1024]
        if not written_metadata:
            write(metadata)
        if error:
            write({'event': 'error', 'reason': reason, 'error': error})
        summary = {'event': 'summary', 'status': status, 'reason': reason,
                   'source': SOURCE, 'runtime': 'ollama', 'role': 'teacher',
                   'executed_actions': executed, 'invalid_actions': invalid,
                   'decisions': decisions, 'tokens': used, 'final': state,
                   'planner_stats': copy.deepcopy(planner.stats) if planner is not None else None,
                   'elapsed_ms': round((time.monotonic() - started) * 1000)}
        write(summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', required=True)
    parser.add_argument('--game', choices=('angry-birds', 'getting-over-it'), required=True)
    parser.add_argument('--level', type=int, default=0)
    parser.add_argument('--model', default=None)
    parser.add_argument('--output', required=True)
    parser.add_argument('--steps', type=int, default=60)
    parser.add_argument('--tokens', type=int, default=100000)
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--candidate-budget', type=int, default=1200)
    parser.add_argument('--tick-budget', type=int, default=2000000)
    parser.add_argument('--samples', type=int, default=24)
    parser.add_argument('--horizon', type=int, default=3)
    args = vars(parser.parse_args())
    args['executable'] = args.pop('env')
    result = collect(**args)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
