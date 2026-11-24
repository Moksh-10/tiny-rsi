"""No model/physics rollout is launched: HTTP and native runtime are fakes."""
from __future__ import annotations
import copy
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1] / 'src'
if SOURCE_ROOT.is_dir():
    sys.path.insert(0, str(SOURCE_ROOT))
if importlib.util.find_spec('tiny_rsi.model_teacher') is not None:
    teacher = importlib.import_module('tiny_rsi.model_teacher')
else:
    SPEC = importlib.util.spec_from_file_location('tiny_rsi.model_teacher_candidate', '/tmp/tiny-rsi-model-teacher.py')
    teacher = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(teacher)


class FakeEnvironment:
    instances = []
    def __init__(self, executable, game, level=0):
        self.game, self.level, self.closed = game, level, False
        self.actions = []
        self.instances.append(self)
    def reset(self, seed=0):
        self.state = {'ok': True, 'observation': {'phase': 'aiming', 'next_bird': 'red', 'entities': [], 'ability_ready': False, 'birds_left': 3, 'pigs_left': 2, 'score': 0},
                      'info': {'ticks': 0, 'max_ticks': 18000, 'success': False},
                      'terminated': False, 'truncated': False, 'game': self.game}
        return self.state['observation'], self.state['info']
    def request(self, q):
        if q['op'] == 'describe':
            return {'ok': True, 'angry_birds': {'coordinates': 'pixels'}}
        action = q['action']
        if action.get('x', 0) > 95:
            return {'ok': False, 'error': 'out of range: x'}
        self.actions.append(copy.deepcopy(action))
        result = copy.deepcopy(self.state)
        result['info']['ticks'] += action['ticks']
        if action['type'] == 'launch':
            result['observation']['phase'] = 'won'
            result['info']['success'] = result['terminated'] = True
        return result
    def close(self):
        self.closed = True


class FakePlanner:
    instances = []
    def __init__(self, *args, **kwargs):
        self.history, self.observed_history_lengths, self.closed = [], [], False
        self.stats = {'candidate_rollouts': 0, 'oracle_ticks': 0, 'budget_exhausted': False}
        self.instances.append(self)
    def label(self, observation, info):
        self.observed_history_lengths.append(len(self.history))
        self.stats['candidate_rollouts'] += 1
        self.stats['oracle_ticks'] += 60
        return {'type': 'launch', 'x': -85, 'y': 0, 'ticks': 30}
    def observe_action(self, action):
        # The collector must not record history before native acceptance.
        if FakeEnvironment.instances[-1].actions[-1] != action:
            raise AssertionError('planner history advanced before native acceptance')
        self.history.append(copy.deepcopy(action))
    def close(self):
        self.closed = True


class FakeOllama:
    instances = []
    replies = []
    identity_digest = 'a' * 64
    failure = None
    def __init__(self, model, **kwargs):
        self.model, self.requests = model, []
        self.replies = copy.deepcopy(type(self).replies)
        self.instances.append(self)
    def identity(self):
        return {'name': self.model, 'digest': self.identity_digest, 'ollama_version': 'test'}
    def api(self, path, body=None):
        if path != '/api/chat':
            raise AssertionError(path)
        self.requests.append(copy.deepcopy(body))
        if self.failure:
            raise self.failure
        return {'message': {'content': self.replies.pop(0), 'thinking': 'PRIVATE_THOUGHT'},
                'prompt_eval_count': 100, 'eval_count': 20, 'total_duration': 1000000, 'done_reason': 'stop'}


class ModelTeacherTest(unittest.TestCase):
    def setUp(self):
        FakeEnvironment.instances.clear()
        FakePlanner.instances.clear()
        FakeOllama.instances.clear()
        FakeOllama.replies = []
        FakeOllama.identity_digest = 'a' * 64
        FakeOllama.failure = None
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = str(Path(self.directory.name) / 'teacher.jsonl')
        for name, value in (
            ('require_worker', lambda: None), ('GameEnvironment', FakeEnvironment),
            ('PlanningPolicy', FakePlanner), ('OllamaResearcher', FakeOllama),
            ('file_sha256', lambda _: 'b' * 64),
            ('load_roles', lambda: {'roles': {'teacher': {'context_tokens': 2048}}}),
        ):
            context = patch.object(teacher, name, value)
            context.start()
            self.addCleanup(context.stop)
    def collect(self, **kwargs):
        return teacher.collect('/unused/game-env', 'angry-birds', self.output, model='qwen2.5:3b', **kwargs)
    def records(self):
        return [json.loads(line) for line in Path(self.output).read_text().splitlines()]

    def test_actual_model_response_not_planner_answer_is_executed_and_labeled(self):
        wait = '{"type":"wait","ticks":30}'
        launch = ' { "type" : "launch", "x":-75, "y":5, "ticks":30 } '
        FakeOllama.replies = [wait, launch]
        result = self.collect(steps=2)
        self.assertEqual(result['executed_actions'], 2)
        self.assertEqual(FakeEnvironment.instances[0].actions, [json.loads(wait), json.loads(launch)])
        self.assertEqual(FakePlanner.instances[0].history, FakeEnvironment.instances[0].actions)
        self.assertEqual(FakePlanner.instances[0].observed_history_lengths, [0, 1])
        rows = [r for r in self.records() if r['event'] == 'step']
        self.assertEqual(rows[-1]['teacher_response'], launch)
        self.assertEqual(rows[-1]['teacher']['runtime'], 'ollama')
        self.assertEqual(rows[-1]['teacher']['digest'], 'a' * 64)
        self.assertTrue(rows[-1]['verification']['action_valid'])
        self.assertEqual(rows[-1]['info']['ticks'], 30)  # pre-action info
        student = json.dumps(rows[-1]['student_prompt'])
        self.assertNotIn('recommendation', student)
        self.assertNotIn('-85', student)
        self.assertIn('-85', json.dumps(rows[-1]['teacher_prompt']))
        self.assertNotIn('PRIVATE_THOUGHT', Path(self.output).read_text())
        self.assertTrue(all(r['source'] == teacher.SOURCE for r in rows))

    def test_invalid_model_text_never_creates_training_row_or_history(self):
        FakeOllama.replies = ['{"type":"wait","type":"launch","ticks":30}',
                              '{"type":"launch","x":-75,"y":5,"ticks":30}']
        result = self.collect(steps=2)
        self.assertEqual(result['invalid_actions'], 1)
        self.assertEqual(result['executed_actions'], 1)
        self.assertEqual(FakePlanner.instances[0].observed_history_lengths, [0, 0])
        self.assertEqual(len(FakePlanner.instances[0].history), 1)
        self.assertEqual(len([r for r in self.records() if r['event'] == 'step']), 1)
        self.assertEqual(len([r for r in self.records() if r['event'] == 'rejected_action']), 1)

    def test_native_rejection_never_advances_planner_prefix(self):
        FakeOllama.replies = ['{"type":"launch","x":100,"y":0,"ticks":30}',
                              '{"type":"launch","x":-75,"y":5,"ticks":30}']
        result = self.collect(steps=2)
        self.assertEqual(result['invalid_actions'], 1)
        self.assertEqual(FakePlanner.instances[0].observed_history_lengths, [0, 0])
        self.assertEqual(len(FakeEnvironment.instances[0].actions), 1)

    def test_guard_precedes_output_engine_reads_network_or_spawns(self):
        with patch.object(teacher, 'require_worker', side_effect=RuntimeError('not guest')):
            with self.assertRaises(RuntimeError):
                self.collect()
        self.assertFalse(Path(self.output).exists())
        self.assertFalse(FakeEnvironment.instances)
        self.assertFalse(FakeOllama.instances)

    def test_holdout_and_validation_collection_rejected(self):
        for level in (6, 7, 8, 11):
            with self.assertRaises(ValueError):
                self.collect(level=level)
        self.assertFalse(Path(self.output).exists())
        self.assertFalse(FakeOllama.instances)

    def test_existing_artifact_never_overwritten(self):
        Path(self.output).write_text('original')
        with self.assertRaises(FileExistsError):
            self.collect()
        self.assertEqual(Path(self.output).read_text(), 'original')
        self.assertFalse(FakeOllama.instances)

    def test_bad_model_identity_fails_closed_without_spawning_physics(self):
        FakeOllama.identity_digest = 'not-a-digest'
        result = self.collect()
        self.assertEqual(result['status'], 'error')
        self.assertFalse(FakeEnvironment.instances)
        self.assertFalse([r for r in self.records() if r['event'] == 'step'])

    def test_token_preflight_does_not_issue_generation(self):
        result = self.collect(tokens=1024)
        self.assertEqual(result['reason'], 'token_budget')
        self.assertEqual(result['decisions'], 0)
        self.assertFalse(FakeOllama.instances[0].requests)
        self.assertTrue(FakeEnvironment.instances[0].closed)
        self.assertTrue(FakePlanner.instances[0].closed)

    def test_api_timeout_preserves_error_summary_and_releases_both_engines(self):
        FakeOllama.failure = TimeoutError('model deadline')
        result = self.collect()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'wall_timeout')
        self.assertTrue(FakeEnvironment.instances[0].closed)
        self.assertTrue(FakePlanner.instances[0].closed)
        self.assertFalse([r for r in self.records() if r['event'] == 'step'])
        self.assertEqual(self.records()[-1]['event'], 'summary')


class FakeOracle(FakeEnvironment):
    def act(self, action):
        self.state = self.request({'op':'act','action':action})
        return copy.deepcopy(self.state)


class PlannerHistoryTest(unittest.TestCase):
    def setUp(self):
        live = importlib.import_module('tiny_rsi.planner')
        if hasattr(live.PlanningPolicy, 'label'):
            self.module = live
        else:
            spec = importlib.util.spec_from_file_location('tiny_rsi.planner_candidate', '/tmp/tiny-rsi-patched-planner.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        for name,value in (('require_worker',lambda:None),('GameEnvironment',FakeOracle)):
            context=patch.object(self.module,name,value);context.start();self.addCleanup(context.stop)
        self.policy=self.module.PlanningPolicy('unused','angry-birds')
        self.addCleanup(self.policy.close)
        self.policy.oracle.reset()
        self.initial=copy.deepcopy(self.policy.oracle.state)

    def test_label_does_not_claim_the_tool_action_was_executed(self):
        action=self.policy.label(self.initial['observation'],self.initial['info'])
        self.assertEqual(action['type'],'launch')
        self.assertEqual(self.policy.history,[])

    def test_actual_different_action_replaces_future_plan_not_history(self):
        self.policy.label(self.initial['observation'],self.initial['info'])
        self.policy.queue=[{'type':'wait','ticks':120}]
        self.policy.warm=[{'type':'wait','ticks':30}]
        actual={'type':'wait','ticks':30}
        self.policy.observe_action(actual)
        self.assertEqual(self.policy.history,[actual])
        self.assertEqual(self.policy.queue,[])
        self.assertEqual(self.policy.warm,[])

    def test_rejected_label_is_discarded_before_another_recommendation(self):
        self.policy.label(self.initial['observation'],self.initial['info'])
        self.policy.queue=[{'type':'wait','ticks':120}]
        again=self.policy.label(self.initial['observation'],self.initial['info'])
        self.assertEqual(again['type'],'launch')
        self.assertEqual(self.policy.history,[])

    def test_mismatched_public_prefix_fails_before_hypothetical_actions(self):
        self.policy._expected_observation={'phase':'flying'}
        with self.assertRaisesRegex(RuntimeError,'prefix differs'):
            self.policy._trial([{'type':'wait','ticks':30}])

    def test_mismatched_simulation_time_fails_even_if_geometry_is_static(self):
        self.policy._expected_tick=30
        with self.assertRaisesRegex(RuntimeError,'simulation time'):
            self.policy._trial([])


if __name__ == '__main__':
    unittest.main()
