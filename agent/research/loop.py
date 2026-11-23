"""Bounded automated policy research: propose -> train -> validate -> gate -> final holdout.

Ollama proposes finite data-only configurations. It cannot change code, rewards,
partitions, budgets, or the evaluator. Held-out scores are produced only after
selection and are never sent back to the researcher.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import time

from .environment import require_worker
from .evaluation import EpisodeBudget, NoOpPolicy, evaluate_policy, compare_reports
from .researcher import OllamaResearcher, training_config
from .student import StudentPolicy, train_candidates
from .teacher import collect


def save(path, value):
    with Path(path).open('x') as target:
        json.dump(value, target, sort_keys=True, indent=2, allow_nan=False)
        target.write('\n')


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def run(executable, game, output, datasets=None, rounds=3, decisions=64,
        max_ticks=7200, max_seconds=1800, model='qwen2.5:3b', teacher_steps=120):
    require_worker()
    if game not in ('angry-birds', 'getting-over-it') or not 1 <= rounds <= 8:
        raise ValueError('Invalid game or round budget')
    if not 60 <= max_seconds <= 3600:
        raise ValueError('Research wall budget must be 60–3600 seconds')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    budget = EpisodeBudget(max_decisions=decisions, max_ticks=max_ticks,
                           timeout_seconds=120)
    identity = {'engine_sha256': fingerprint(executable), 'game': game,
                'budget': asdict(budget), 'partition': {'train': list(range(6)),
                'validation': [6, 7], 'heldout': [8, 9, 10, 11]},
                'scope': 'structured-state small-policy distillation; not LLM fine-tuning'}
    if game == 'getting-over-it':
        identity['partition'] = {'train': [0], 'validation': [0], 'heldout': [0]}
        identity['scope'] += '; same-course replication, not unseen-course generalization'
    save(root / 'identity.json', identity)
    data = list(datasets or [])
    if not data:
        directory = root / 'demonstrations'
        directory.mkdir()
        levels = range(6) if game == 'angry-birds' else (0,)
        for level in levels:
            if time.monotonic() - started > max_seconds / 2:
                raise TimeoutError('Teacher data collection exceeded allotted research budget')
            path = directory / f'teacher-{game}-{level}.jsonl'
            collect(executable, game, level, str(path), steps=teacher_steps,
                    candidate_budget=1800, tick_budget=2_000_000, samples=24, horizon=3)
            data.append(str(path))
    save(root / 'datasets.json', [{'path': p, 'sha256': fingerprint(p)} for p in data])
    researcher = OllamaResearcher(model=model, token_budget=30000)
    save(root / 'researcher-identity.json', researcher.identity())
    incumbent = evaluate_policy(executable, NoOpPolicy(game), game,
                                split='validation', budget=budget)
    save(root / 'baseline-noop-validation.json', incumbent)
    selected = None
    experiments = []
    promotions = []
    for index in range(rounds):
        if time.monotonic() - started > max_seconds - 180:
            break
        directory = root / f'round-{index:02d}'
        directory.mkdir()
        if index == 0:
            # A controlled neural baseline guarantees a genuine weight-learning experiment.
            config = {'architecture': 'mlp', 'hidden_sizes': [16], 'epochs': [50],
                      'learning_rates': [0.03], 'seed': 0, 'max_candidates': 1,
                      'max_rows': 10000, 'max_seconds': 120}
            source = 'fixed neural control experiment'
        else:
            feedback = {'goal': 'Improve validation win/progress at fixed action/compute limits',
                        'game': game, 'round': index, 'experiments': experiments,
                        'incumbent_validation': incumbent['aggregate'], 'budget': asdict(budget)}
            proposal = researcher.propose(feedback, directory / 'proposal-audit.json')
            config = training_config(proposal, seed=index)
            source = 'guest-local Ollama proposal'
        save(directory / 'configuration.json', {'source': source, 'config': config})
        training = train_candidates(data, str(directory / 'training'), game, config)
        untrained = evaluate_policy(executable, StudentPolicy.load(training['untrained_checkpoint']),
                                    game, split='validation', budget=budget)
        candidate = evaluate_policy(executable, StudentPolicy.load(training['checkpoint']),
                                    game, split='validation', budget=budget)
        save(directory / 'untrained-validation.json', untrained)
        save(directory / 'candidate-validation.json', candidate)
        gate = compare_reports(incumbent, candidate)
        learned = compare_reports(untrained, candidate)
        event = {'round': index, 'source': source, 'architecture': training['architecture'],
                 'configuration': config, 'validation': candidate['aggregate'],
                 'matched_untrained_validation': untrained['aggregate'],
                 'training_gain': learned, 'promotion': gate,
                 'checkpoint_bytes': training['checkpoint_bytes'],
                 'parameters': training['parameters'], 'training_seconds': training['training_seconds']}
        save(directory / 'decision.json', event)
        experiments.append(event)
        if gate['promote']:
            incumbent = candidate
            selected = training['checkpoint']
            promotions.append({'round': index, 'sha256': training['sha256'], 'gate': gate})
        save(root / f'progress-{index:02d}.json', {'experiments': experiments, 'promotions': promotions})
    report = {'identity': identity, 'experiments': experiments, 'promotions': promotions,
              'selected_checkpoint': selected, 'researcher_tokens': researcher.tokens,
              'elapsed_seconds': time.monotonic() - started,
              'claim': 'Bounded automated policy experimentation; no base-LLM self-modification'}
    # This final result is deliberately downstream of every researcher call and selection decision.
    if selected:
        destination = root / 'promoted-student.json'
        shutil.copyfile(selected, destination)
        heldout = evaluate_policy(executable, StudentPolicy.load(selected), game,
                                  split='heldout', budget=budget)
        save(root / 'final-heldout.json', heldout)
        report['final_evaluation'] = heldout['aggregate']
        report['promoted_checkpoint'] = str(destination)
    else:
        report['final_evaluation'] = None
        report['claim'] += '; no candidate passed promotion'
    save(root / 'research-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', required=True)
    parser.add_argument('--game', choices=['angry-birds', 'getting-over-it'], required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--data', nargs='*')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--decisions', type=int, default=64)
    parser.add_argument('--ticks', type=int, default=7200)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--model', default='qwen2.5:3b')
    parser.add_argument('--teacher-steps', type=int, default=120)
    args = parser.parse_args()
    result = run(args.env, args.game, args.output, args.data, args.rounds,
                 args.decisions, args.ticks, args.seconds, args.model, args.teacher_steps)
    print(json.dumps({'promotions': result['promotions'], 'final_evaluation': result['final_evaluation'],
                      'selected_checkpoint': result['selected_checkpoint'], 'elapsed_seconds': result['elapsed_seconds']}))


if __name__ == '__main__':
    main()
