"""Mock-only evaluator tests: never infer, train, or run a game on the host."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

if os.environ.get('TINY_RSI_MODEL_EVALUATION_FILE'):
    # Real helper modules are safe to import; all execution boundaries are mocked.
    from tiny_rsi import actor
    spec = importlib.util.spec_from_file_location('tiny_rsi._temporary_model_evaluation', os.environ['TINY_RSI_MODEL_EVALUATION_FILE'])
    model_evaluation = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = model_evaluation
    spec.loader.exec_module(model_evaluation)
else:
    from tiny_rsi import model_evaluation


CRITIC = {'diagnosis': 'The shots repeat a high trajectory.', 'evidence': ['All birds used the same pull.'],
          'recommendations': [{'control': 'aiming', 'advice': 'Try a lower arc and observe the impact.'}],
          'confidence': 'medium'}


class FakeClient:
    calls = []
    quantization = {}
    critic_reply = CRITIC
    def __init__(self, model, **kwargs):
        self.model = model
    def identity(self):
        digest = {'base': 'a', 'trained': 'b', 'judge': 'c'}.get(self.model, 'd') * 64
        return {'name': self.model, 'digest': digest, 'ollama_version': 'test'}
    def api(self, path, body=None):
        self.calls.append((self.model, path, body))
        if path == '/api/show':
            return {'details': {'family': 'qwen2', 'parameter_size': '0.5B', 'format': 'gguf',
                                'quantization_level': self.quantization.get(self.model, 'Q4_K_M')},
                    'template': 'common template', 'system': '', 'parameters': '',
                    'model_info': {'general.architecture': 'qwen2', 'general.parameter_count': 500000000}}
        return {'message': {'content': json.dumps(self.critic_reply)},
                'prompt_eval_count': 100, 'eval_count': 40}


class ModelEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = self.root / 'game-env'
        self.engine.write_bytes(b'trusted fake engine')
        self.fake_actor_file = self.root / 'actor.py'
        self.fake_actor_file.write_text('same actor')
        (self.root / 'prompts.py').write_text('same public prompt builder')
        self.guard = mock.patch.object(model_evaluation, 'require_worker')
        self.client = mock.patch.object(model_evaluation, 'OllamaResearcher', FakeClient)
        self.play = mock.patch.object(model_evaluation.actor, 'play_episode', side_effect=self.fake_episode)
        self.actor_path = mock.patch.object(model_evaluation.actor, '__file__', str(self.fake_actor_file))
        self.guard_mock = self.guard.start()
        self.client.start();self.play.start();self.actor_path.start()
        FakeClient.calls.clear();FakeClient.quantization.clear();FakeClient.critic_reply = copy.deepcopy(CRITIC)
    def tearDown(self):
        self.actor_path.stop();self.play.stop();self.client.stop();self.guard.stop()
        self.temp.cleanup()

    def fake_episode(self, executable, output, *, model, game, level, role, **budget):
        success = model == 'trained'
        observation = {'pigs_left': 2, 'score': 0, 'position': [-5,.55], 'best_height': 0}
        initial = {'ok': True, 'protocol': 1, 'game': game, 'observation': observation,
                   'reward': 0, 'terminated': False, 'truncated': False,
                   'info': {'ticks': 0, 'success': False}}
        final = copy.deepcopy(initial)
        final['observation']['pigs_left'] = 0 if success else 2
        final['observation']['score'] = 2000 if success else 0
        final['observation']['best_height'] = 2 if success else 0
        final['info'].update(ticks=120, success=success)
        final['terminated'] = success
        final['reward'] = 2 if success else 0
        events = [
            {'event': 'metadata', 'game': game, 'level': level, 'model': model,
             'digest': FakeClient(model).identity()['digest'], 'role': role,
             'engine_sha256': model_evaluation._file_hash(executable),
             'options': {'num_ctx': 4096, 'num_predict': 256, 'temperature': 0, 'seed': 0}},
            {'event': 'reset', 'request': {'op':'reset','game':game,'level':level}, 'response': initial},
            {'event': 'step', 'action': {'type':'wait','ticks':120}, 'response': final},
            {'event': 'summary', 'status':'ok', 'reason':'environment_finished' if success else 'decision_limit',
             'executed_actions':1,'invalid_actions':0,'tokens':100,'elapsed_ms':10,'final':final},
        ]
        with open(output,'x') as target:
            for event in events:target.write(json.dumps(event)+'\n')
        return events[-1]

    def evaluate(self, model='base', name='report', **kwargs):
        return model_evaluation.evaluate_model(str(self.engine), model, 'angry-birds', self.root/name,
                                               budget=model_evaluation.ModelBudget(steps=2), **kwargs)

    def manifest(self, baseline, candidate):
        conversion = {'converter_commit':'e'*40, 'quantization':'Q4_K_M', 'recipe_sha256':'f'*64,
                      'template_sha256':baseline['model_profile']['template_sha256']}
        value = {'schema_version':1, 'base_digest':baseline['model_identity']['digest'],
                 'trained_digest':candidate['model_identity']['digest'], 'hf_base_revision':'d'*40,
                 'artifact_fingerprints':{'adapter':'1'*64,'merged_weights':'2'*64,'training_run':'3'*64},
                 'base_conversion':conversion, 'trained_conversion':copy.deepcopy(conversion)}
        path=self.root/'manifest.json';path.write_text(json.dumps(value));return path

    def test_native_evaluation_uses_fixed_cases_and_records_prompt_fingerprint(self):
        report=self.evaluate()
        self.assertEqual(report['levels'],(6,7))
        self.assertEqual(report['aggregate']['success_rate'],0)
        self.assertEqual(report['aggregate']['tokens'],200)
        self.assertEqual(len(report['prompts_sha256']),64)
        self.assertEqual(report['metrics_source'],'native-cpp-engine')
        self.assertEqual((self.root/'report'/'report.json').stat().st_mode & 0o777,0o600)
        self.assertEqual({e['level'] for e in report['episodes']},{6,7})

    def test_compare_requires_equal_quantization_prompt_budget_and_real_lineage(self):
        baseline=self.evaluate()
        candidate=self.evaluate('trained','candidate',source_model='base')
        unverified=model_evaluation.compare_model_reports(baseline,candidate)
        self.assertTrue(unverified['native_improvement'])
        self.assertFalse(unverified['promote'])
        manifest=self.manifest(baseline,candidate)
        verified=model_evaluation.compare_model_reports(baseline,candidate,training_manifest=manifest)
        self.assertTrue(verified['promote'])
        self.assertFalse(verified['critic_has_vote'])
        self.assertFalse(verified['training_provenance']['training_reproduced'])
        changed=copy.deepcopy(candidate);changed['budget']['steps']=3
        with self.assertRaises(ValueError):model_evaluation.compare_model_reports(baseline,changed)
        changed=copy.deepcopy(candidate);changed['source_identity']['digest']='c'*64
        with self.assertRaises(ValueError):model_evaluation.compare_model_reports(baseline,changed)
        FakeClient.quantization['trained']='F16'
        with self.assertRaises(ValueError):self.evaluate('trained','f16',source_model='base')

    def test_changed_prompt_module_invalidates_paired_comparison(self):
        baseline=self.evaluate()
        (self.root/'prompts.py').write_text('different prompt builder')
        candidate=self.evaluate('trained','candidate',source_model='base')
        with self.assertRaises(ValueError):model_evaluation.compare_model_reports(baseline,candidate)

    def test_model_critic_is_advisory_and_cannot_mutate_native_outcome(self):
        report=self.evaluate();original=copy.deepcopy(report)
        result=model_evaluation.critique_report(report,self.root/'critic.json',model='judge')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['role'],'evaluator')
        self.assertEqual(result['identity']['digest'],'c'*64)
        self.assertEqual(result['tokens'],140)
        self.assertTrue(result['advisory_only'])
        self.assertFalse(result['can_override_ground_truth'])
        self.assertEqual(report,original)
        self.assertEqual((self.root/'critic.json').stat().st_mode & 0o777,0o600)
        FakeClient.critic_reply=dict(CRITIC,score=999,promote=True)
        failed=model_evaluation.critique_report(report,self.root/'bad-critic.json',model='judge')
        self.assertEqual(failed['status'],'error')
        self.assertIsNone(failed['critic'])
        self.assertEqual(report,original)

    def test_hidden_heldout_data_is_rejected_before_model_call(self):
        report=self.evaluate(split='heldout')
        FakeClient.calls.clear()
        with self.assertRaises(ValueError):model_evaluation.critique_report(report,self.root/'forbidden.json',model='judge')
        self.assertFalse(FakeClient.calls)
        self.assertFalse((self.root/'forbidden.json').exists())
        report['split']='validation';report['evaluation_scope']='development-levels'
        with self.assertRaises(ValueError):model_evaluation.critique_report(report,self.root/'forbidden.json',model='judge')
        report=self.evaluate(name='validation')
        report['aggregate']['nested']={'split':'heldout','mean_progress':1}
        with self.assertRaises(ValueError):model_evaluation.critique_report(report,self.root/'forbidden.json',model='judge')

    def test_manifest_rejects_conversion_changes_and_changed_artifact(self):
        baseline=self.evaluate();candidate=self.evaluate('trained','candidate',source_model='base')
        path=self.manifest(baseline,candidate);data=json.loads(path.read_text())
        data['trained_conversion']['recipe_sha256']='a'*64;path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):model_evaluation.validate_training_manifest(path,baseline,candidate)
        path.unlink();path=self.manifest(baseline,candidate);data=json.loads(path.read_text())
        artifact=self.root/'adapter.bin';artifact.write_bytes(b'wrong contents')
        data['artifact_paths']={'adapter':str(artifact)};path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):model_evaluation.validate_training_manifest(path,baseline,candidate)

    def test_guard_blocks_actual_model_operations_and_duplicate_critic_cost(self):
        self.guard_mock.side_effect=RuntimeError('VM required')
        with self.assertRaises(RuntimeError):self.evaluate()
        self.assertFalse(FakeClient.calls)
        self.guard_mock.side_effect=None
        report=self.evaluate()
        model_evaluation.critique_report(report,self.root/'critic.json',model='judge')
        before=len(FakeClient.calls)
        with self.assertRaises(FileExistsError):model_evaluation.critique_report(report,self.root/'critic.json',model='judge')
        self.assertEqual(len(FakeClient.calls),before)

if __name__=='__main__':unittest.main()
