"""Versioned evaluation with fixed splits, equal budgets and explicit limitations.

The evaluator never trains policies or changes rewards. Development tests can
inject fake environments; real CLI/callable experiments require a sealed VM.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
import math
from pathlib import Path
import random
import signal
import threading
import time
from typing import Any, Callable

from .environment import GameEnvironment, InvalidAction, require_worker

SCHEMA_VERSION = 1
TRAINING_LEVELS = tuple(range(6))
VALIDATION_LEVELS = (6, 7)
HELDOUT_LEVELS = (8, 9, 10, 11)
# Explicit alias: training never includes validation or held-out levels.
TRAIN_LEVELS = TRAINING_LEVELS
SPLITS = {'train': TRAINING_LEVELS, 'validation': VALIDATION_LEVELS,
          'heldout': HELDOUT_LEVELS, 'eval': HELDOUT_LEVELS}


@dataclass(frozen=True)
class EpisodeBudget:
    max_decisions: int = 128
    max_ticks: int = 18000
    max_invalid: int = 5
    timeout_seconds: float = 120.0

    def __post_init__(self):
        for key, maximum in (('max_decisions', 10000), ('max_ticks', 18000), ('max_invalid', 1000)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{key} must be an integer in [1,{maximum}]')
        if not isinstance(self.timeout_seconds, (float, int)) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 3600:
            raise ValueError('timeout_seconds must be in (0,3600]')


class EvaluationTimeout(TimeoutError):
    pass


@contextmanager
def _deadline(seconds):
    # The CLI runs one evaluator per process. A signal deadline also interrupts
    # bounded Python planners; a timeout check between decisions alone would not.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Evaluate in the main thread or a dedicated process')
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expired(signum, frame):
        raise EvaluationTimeout('Episode wall-time budget exhausted')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, old_timer[0]) if old_timer[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, old_timer[0] - (time.monotonic() - started)), old_timer[1])


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for part in iter(lambda: source.read(1 << 20), b''):
            digest.update(part)
    return digest.hexdigest()


def _numeric_stats(policy):
    stats = getattr(policy, 'stats', {})
    if callable(stats):
        stats = stats()
    if not isinstance(stats, dict):
        return {}
    return {str(k): v for k, v in stats.items()
            if type(v) in (int, float) and math.isfinite(v) and v >= 0}


def _episode(executable, policy, game, level, budget, env_factory):
    initial = final = None
    reward = 0.0
    decisions = valid = invalid = 0
    policy_seconds = engine_seconds = 0.0
    reason = 'decision_limit'
    error = None
    stats_before = {}
    started = time.monotonic()
    env = None
    try:
        with _deadline(budget.timeout_seconds):
            env = env_factory(executable, game, level)
            observation, info = env.reset(seed=0)
            initial = final = env.state
            if hasattr(policy, 'reset'):
                policy.reset()
            stats_before = _numeric_stats(policy)
            for _ in range(budget.max_decisions):
                if final['terminated'] or final['truncated']:
                    reason = 'environment_finished'
                    break
                remaining = budget.max_ticks - final['info']['ticks']
                if remaining <= 0:
                    reason = 'tick_limit'
                    break
                before = time.monotonic()
                try:
                    action = policy(observation, info)
                finally:
                    policy_seconds += time.monotonic() - before
                decisions += 1
                if not isinstance(action, dict):
                    invalid += 1
                    info = dict(info, invalid_action=True, error='Policy must return an action object')
                else:
                    action = dict(action)
                    # The same final-action clipping rule applies to every policy.
                    ticks = action.get('ticks')
                    if type(ticks) is int and ticks > 0:
                        action['ticks'] = min(ticks, remaining)
                    before = time.monotonic()
                    try:
                        observation, r, _, _, info = env.step(action)
                        final = env.state
                        reward += r
                        valid += 1
                    except InvalidAction as exc:
                        invalid += 1
                        info = dict(info, invalid_action=True, error=str(exc))
                    finally:
                        engine_seconds += time.monotonic() - before
                if invalid >= budget.max_invalid:
                    reason = 'invalid_action_limit'
                    break
            if final['terminated'] or final['truncated']:
                reason = 'environment_finished'
            elif final['info']['ticks'] >= budget.max_ticks:
                reason = 'tick_limit'
    except EvaluationTimeout:
        reason = 'wall_timeout'
    except Exception as exc:
        reason = 'policy_or_environment_error'
        error = f'{type(exc).__name__}: {exc}'[:1024]
    finally:
        if env is not None:
            env.close()
    obs = final['observation'] if final is not None else {}
    if game == 'angry-birds':
        initial_pigs = initial['observation']['pigs_left'] if initial else 0
        progress = (initial_pigs - obs.get('pigs_left', initial_pigs)) / initial_pigs if initial_pigs else 0.0
    else:
        progress = obs.get('best_height', 0.0) / 66.0
    result = {
        'case_id': f'{game}:level:{level}', 'game': game, 'level': level,
        'success': bool(final and final['info']['success']),
        'progress': max(0.0, min(1.0, progress)), 'reward': reward,
        'decisions': decisions, 'valid_actions': valid, 'invalid_actions': invalid,
        'ticks': final['info']['ticks'] if final else 0,
        'elapsed_seconds': time.monotonic() - started,
        'policy_seconds': policy_seconds, 'engine_seconds': engine_seconds,
        'reason': reason, 'final_observation': obs,
        'policy_reported_compute': {key: max(0, value - stats_before.get(key, 0))
                                    for key, value in _numeric_stats(policy).items()},
    }
    if error:
        result['error'] = error
    return result


def evaluate_policy(executable, policy, game, *, split='validation', budget=None,
                    levels=None, require_sandbox=True, policy_factory=None,
                    env_factory=GameEnvironment):
    """Evaluate without learning; policies receive (observation, info).

    policy_factory(game, level) can create a fresh planner per episode; factory
    instances are closed after each episode. A shared policy is reset per case
    when it exposes reset(), and remains owned by its caller.
    """
    if require_sandbox:
        require_worker()
    if game not in ('angry-birds', 'getting-over-it') or split not in SPLITS:
        raise ValueError('Unsupported game or split')
    budget = EpisodeBudget() if budget is None else budget
    if not isinstance(budget, EpisodeBudget):
        raise TypeError('budget must be EpisodeBudget')
    if (policy is None) == (policy_factory is None):
        raise ValueError('Provide exactly one policy or policy_factory')
    selected = tuple(SPLITS[split] if game == 'angry-birds' else (0,)) if levels is None else tuple(levels)
    allowed = set(SPLITS[split]) if game == 'angry-birds' else {0}
    if not selected or len(set(selected)) != len(selected) or any(type(x) is not int or x not in allowed for x in selected):
        raise ValueError('Evaluation levels must be unique and belong to the requested fixed split')
    split = 'heldout' if split == 'eval' else split
    engine_hash = _hash_file(executable)
    configuration = {'schema_version': SCHEMA_VERSION, 'game': game, 'split': split,
                     'levels': selected, 'budget': asdict(budget), 'track': 'structured-state',
                     'engine_sha256': engine_hash, 'evaluator_sha256': _hash_file(__file__)}
    suite_id = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    episodes = []
    for level in selected:
        actor = policy_factory(game, level) if policy_factory is not None else policy
        try:
            episodes.append(_episode(executable, actor, game, level, budget, env_factory))
        finally:
            if policy_factory is not None and hasattr(actor, 'close'):
                actor.close()
    n = len(episodes)
    compute = {}
    for episode in episodes:
        for key, value in episode['policy_reported_compute'].items():
            compute[key] = compute.get(key, 0) + value
    return {
        **configuration, 'suite_id': suite_id,
        'evaluation_scope': 'held-out-layouts' if game == 'angry-birds' and split == 'heldout'
            else 'fixed-course-replication' if game == 'getting-over-it' else 'development-levels',
        'unseen_layout_generalization': game == 'angry-birds' and split == 'heldout',
        'episodes': episodes,
        'aggregate': {
            'episodes': n, 'success_rate': sum(e['success'] for e in episodes) / n,
            'mean_progress': sum(e['progress'] for e in episodes) / n,
            'mean_reward': sum(e['reward'] for e in episodes) / n,
            'total_actions': sum(e['valid_actions'] for e in episodes),
            'total_decisions': sum(e['decisions'] for e in episodes),
            'invalid_actions': sum(e['invalid_actions'] for e in episodes),
            'total_ticks': sum(e['ticks'] for e in episodes),
            'elapsed_seconds': sum(e['elapsed_seconds'] for e in episodes),
            'policy_seconds': sum(e['policy_seconds'] for e in episodes),
            'policy_reported_compute': compute,
            'errors': sum(e['reason'] == 'policy_or_environment_error' for e in episodes),
            'wall_timeouts': sum(e['reason'] == 'wall_timeout' for e in episodes),
        },
    }


def compare_reports(baseline, candidate, *, min_progress_gain=1e-9):
    """Promotion gate: same engine, cases, track and budgets; wins then progress.

    Native reward is reported but cannot alone promote a candidate. The caller
    must keep held-out results away from proposal/training feedback.
    """
    if baseline['suite_id'] != candidate['suite_id']:
        raise ValueError('Reports use different engines, cases, splits or budgets')
    old, new = baseline['aggregate'], candidate['aggregate']
    eligible = new['errors'] == 0 and new['wall_timeouts'] == 0
    win_gain = new['success_rate'] - old['success_rate']
    progress_gain = new['mean_progress'] - old['mean_progress']
    improved = eligible and (win_gain > 0 or (win_gain == 0 and progress_gain > min_progress_gain))
    return {'eligible': eligible, 'promote': improved,
            'success_rate_gain': win_gain, 'mean_progress_gain': progress_gain,
            'comparison': 'paired-fixed-suite', 'suite_id': baseline['suite_id']}


class NoOpPolicy:
    def __init__(self, game):
        self.game = game
    def __call__(self, observation, info):
        return ({'type': 'wait', 'ticks': 120} if self.game == 'angry-birds'
                else {'type': 'hammer', 'x': 2, 'y': 1, 'hold': False, 'ticks': 15})


class RandomPolicy:
    """Seeded legal-control baseline; seed varies policy choices, not terrain."""
    def __init__(self, game, seed=0):
        self.game, self.seed = game, seed
        self.reset()
    def reset(self):
        self.rng = random.Random(self.seed)
    def __call__(self, observation, info):
        if self.game == 'angry-birds':
            if observation['phase'] == 'aiming':
                angle = self.rng.uniform(-0.3, 1.0)
                power = self.rng.uniform(50, 95)
                return {'type': 'launch', 'x': -power * math.cos(angle),
                        'y': power * math.sin(angle), 'ticks': 120}
            return {'type': 'ability' if observation['ability_ready'] and self.rng.random() < .25 else 'wait', 'ticks': 120}
        angle = self.rng.randrange(16) * math.tau / 16
        return {'type': 'hammer', 'x': 3.1 * math.cos(angle), 'y': 3.1 * math.sin(angle),
                'hold': self.rng.random() < .75, 'ticks': 15}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', required=True)
    parser.add_argument('--game', choices=('angry-birds', 'getting-over-it'), required=True)
    parser.add_argument('--split', choices=tuple(SPLITS), default='validation')
    parser.add_argument('--policy', default='random', help='random, noop, or module:factory')
    parser.add_argument('--policy-config', default='{}', help='Trusted factory keyword arguments as JSON')
    parser.add_argument('--decisions', type=int, default=128)
    parser.add_argument('--ticks', type=int, default=18000)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    require_worker()
    kwargs = json.loads(args.policy_config)
    if not isinstance(kwargs, dict):
        raise ValueError('policy-config must be an object')
    if args.policy == 'random':
        factory = lambda game, level: RandomPolicy(game, **kwargs)
    elif args.policy == 'noop':
        factory = lambda game, level: NoOpPolicy(game)
    else:
        module, name = args.policy.split(':', 1)
        constructor = getattr(importlib.import_module(module), name)
        factory = lambda game, level: constructor(executable=args.env, game=game, level=level, **kwargs)
    report = evaluate_policy(args.env, None, args.game, split=args.split,
                             budget=EpisodeBudget(args.decisions, args.ticks, timeout_seconds=args.timeout),
                             policy_factory=factory)
    with open(args.output, 'x') as output:
        json.dump(report, output, sort_keys=True, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps(report['aggregate'], sort_keys=True))


if __name__ == '__main__':
    main()
