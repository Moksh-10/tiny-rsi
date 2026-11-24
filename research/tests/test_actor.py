"""Mock-only actor tests: no model service, game process, or host gameplay."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

# Temporary standalone mode for development before parent integrates actor.py.
# In-repository discovery imports the actual installed/source package normally.
if os.environ.get('TINY_RSI_ACTOR_FILE'):
    package = types.ModuleType('_tiny_rsi_actor_tests')
    package.__path__ = []
    sys.modules[package.__name__] = package
    environment = types.ModuleType(package.__name__ + '.environment')
    environment.GameEnvironment = None
    environment.require_worker = None
    researcher = types.ModuleType(package.__name__ + '.researcher')
    researcher.OllamaResearcher = None
    sys.modules[environment.__name__] = environment
    sys.modules[researcher.__name__] = researcher
    spec = importlib.util.spec_from_file_location(package.__name__ + '.actor', os.environ['TINY_RSI_ACTOR_FILE'])
    actor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actor)
else:
    from tiny_rsi import actor


class FakeEngine:
    instances = []
    def __init__(self, executable, game, level):
        self.game, self.level = game, level
        self.closed = False
        self.state = None
        self.actions = []
        self.instances.append(self)
    def reset(self, seed=None):
        self.state = {'ok': True, 'protocol': 1, 'game': self.game,
                      'observation': {'phase': 'aiming', 'ability_ready': False,
                                      'position': [1.23456789, 2], 'score': 0,
                                      'next_bird': 'red', 'birds_left': 3, 'pigs_left': 2, 'entities': []},
                      'reward': 0, 'terminated': False, 'truncated': False,
                      'info': {'ticks': 0, 'success': False}}
        return copy.deepcopy(self.state['observation']), dict(self.state['info'])
    def request(self, request):
        if request['op'] == 'describe':
            return {'ok': True, 'protocol': 1, 'angry_birds': {}, 'getting_over_it': {}}
        action = request['action']
        self.actions.append(action)
        if action.get('type') not in ('wait', 'launch', 'hammer'):
            return {'ok': False, 'error': 'Invalid native action'}
        result = copy.deepcopy(self.state)
        result['info']['ticks'] += action['ticks']
        result['reward'] = .25
        result['terminated'] = True
        return result
    def close(self):
        self.closed = True


class FakeClient:
    replies = []
    calls = []
    fail_identity = False
    def __init__(self, **kwargs):
        pass
    def identity(self):
        if self.fail_identity:
            raise RuntimeError('identity failure')
        return {'name': 'qwen2.5:3b', 'digest': 'a' * 64, 'ollama_version': 'test'}
    def api(self, path, body=None):
        self.calls.append((path, body))
        if path == '/api/show':
            return {'capabilities': ['completion']}
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result()
        return result


def reply(content, prompt=100, completion=20):
    return {'message': {'content': content}, 'prompt_eval_count': prompt,
            'eval_count': completion, 'total_duration': 123}


class ActorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.executable = Path(self.temp.name) / 'game-env'
        self.executable.write_bytes(b'trusted fake engine bytes')
        self.output = Path(self.temp.name) / 'trace.jsonl'
        FakeEngine.instances.clear()
        FakeClient.calls.clear()
        FakeClient.fail_identity = False
        FakeClient.replies = [reply('{"type":"wait","ticks":120}')]
        self.guard = mock.patch.object(actor, 'require_worker')
        self.engine = mock.patch.object(actor, 'GameEnvironment', FakeEngine)
        self.client = mock.patch.object(actor, 'OllamaResearcher', FakeClient)
        self.guard_mock = self.guard.start()
        self.engine.start()
        self.client.start()
    def tearDown(self):
        self.client.stop()
        self.engine.stop()
        self.guard.stop()
        self.temp.cleanup()
    def run_episode(self, **kwargs):
        return actor.play_episode(str(self.executable), str(self.output), **kwargs)
    def events(self):
        return [json.loads(line) for line in self.output.read_text().splitlines()]

    def test_strict_action_decoder(self):
        for bad in ('null', '[]', '{} {}', '```json\n{}\n```', '{"x":NaN}',
                    '{"x":1e999}', '{"x":1,"x":2}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                actor.action_from(bad)
        self.assertEqual(actor.action_from(' {"type":"wait","ticks":120} \n'), {'type': 'wait', 'ticks': 120})

    def test_schema_excludes_unavailable_controls_and_compact_is_copy(self):
        state = {'observation': {'phase': 'flying', 'ability_ready': False}}
        encoded = json.dumps(actor.action_schema('angry-birds', state))
        self.assertNotIn('launch', encoded)
        self.assertNotIn('ability', encoded)
        state['observation']['ability_ready'] = True
        self.assertIn('ability', json.dumps(actor.action_schema('angry-birds', state)))
        self.assertIn('hold', json.dumps(actor.action_schema('getting-over-it', state)))
        original = {'position': [1.23456789, 2]}
        copied = actor.compact(original)
        self.assertEqual(copied['position'][0], 1.235)
        self.assertEqual(original['position'][0], 1.23456789)

    def test_full_trace_identity_permissions_and_role(self):
        with mock.patch.dict(os.environ, {'TINY_RSI_REVISION': 'deployed-sha'}):
            result = self.run_episode(role='teacher')
        self.assertEqual(result['reason'], 'environment_finished')
        self.assertEqual(result['executed_actions'], 1)
        self.assertEqual(result['tokens'], 120)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        events = self.events()
        self.assertEqual([e['event'] for e in events], ['metadata', 'reset', 'step', 'summary'])
        self.assertEqual(events[0]['role'], 'teacher')
        self.assertEqual(events[0]['revision'], 'deployed-sha')
        self.assertEqual(events[0]['digest'], 'a' * 64)
        self.assertEqual(len(events[0]['engine_sha256']), 64)
        self.assertEqual(events[1]['response']['observation']['position'][0], 1.23456789)
        self.assertIn('\"pigs\"', FakeClient.calls[-1][1]['messages'][1]['content'])
        self.assertNotIn('1.23456789', FakeClient.calls[-1][1]['messages'][1]['content'])
        self.assertTrue(FakeEngine.instances[0].closed)
        with self.assertRaises(FileExistsError):
            self.run_episode()
        self.assertEqual(self.events(), events)

    def test_guard_precedes_identity_spawn_and_output(self):
        self.guard_mock.side_effect = RuntimeError('VM required')
        with self.assertRaises(RuntimeError):
            self.run_episode()
        self.assertFalse(self.output.exists())
        self.assertFalse(FakeClient.calls)
        self.assertFalse(FakeEngine.instances)

    def test_five_invalid_actions_are_bounded_and_logged(self):
        FakeClient.replies = [reply('{"type":"shell","ticks":120}')] * 5
        result = self.run_episode()
        self.assertEqual(result['reason'], 'invalid_action_limit')
        self.assertEqual((result['invalid_actions'], result['executed_actions']), (5, 0))
        steps = [e for e in self.events() if e['event'] == 'step']
        self.assertEqual(len(steps), 5)
        self.assertTrue(all(e['response'] == {'ok': False, 'error': 'Invalid native action'} for e in steps))

    def test_parse_failures_never_reach_engine(self):
        FakeClient.replies = [reply('not json')] * 5
        result = self.run_episode()
        self.assertEqual(result['invalid_actions'], 5)
        self.assertEqual(FakeEngine.instances[0].actions, [])
        self.assertTrue(all(e['response'] is None for e in self.events() if e['event'] == 'step'))

    def test_budget_preflight_avoids_generation(self):
        result = self.run_episode(tokens=1024)
        self.assertEqual(result['reason'], 'token_budget')
        self.assertFalse(any(path == '/api/chat' for path, _ in FakeClient.calls))

    def test_identity_and_inference_errors_preserve_failure_trace(self):
        FakeClient.fail_identity = True
        result = self.run_episode()
        self.assertEqual(result['status'], 'error')
        self.assertEqual([e['event'] for e in self.events()], ['metadata', 'error', 'summary'])
        self.assertFalse(FakeEngine.instances)
        self.output.unlink()
        FakeClient.fail_identity = False
        FakeClient.replies = [RuntimeError('inference failed')]
        result = self.run_episode()
        self.assertEqual(result['status'], 'error')
        self.assertTrue(FakeEngine.instances[0].closed)
        self.assertEqual(self.events()[-2]['event'], 'error')

    def test_absolute_deadline_interrupts_slow_api_and_restores_outer_timer(self):
        def slow():
            time.sleep(.2)
            return reply('{}')
        FakeClient.replies = [slow]
        previous_handler = signal.getsignal(signal.SIGALRM)
        signal.setitimer(signal.ITIMER_REAL, 2)
        try:
            started = time.monotonic()
            result = self.run_episode(timeout=.05)
            self.assertLess(time.monotonic() - started, .5)
            self.assertEqual(result['reason'], 'wall_timeout')
            remaining, interval = signal.getitimer(signal.ITIMER_REAL)
            self.assertTrue(1 < remaining < 2)
            self.assertEqual(signal.getsignal(signal.SIGALRM), previous_handler)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        self.assertTrue(FakeEngine.instances[0].closed)
        self.assertEqual(self.events()[-2]['event'], 'error')

    def test_invalid_token_metrics_fail_closed(self):
        FakeClient.replies = [reply('{}', prompt=-1)]
        result = self.run_episode()
        self.assertEqual(result['status'], 'error')
        self.assertFalse(FakeEngine.instances[0].actions)

if __name__ == '__main__':
    unittest.main()
