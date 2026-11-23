"""Control-flow integrity tests using mocks; no real training, model, or game execution."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import loop


class FakePolicy:
    def __init__(self, path):
        self.path = str(path)


class ResearchLoopTests(unittest.TestCase):
    def pipeline(self, candidate_progress, initial_progress=0.05):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        engine = base / 'engine'
        engine.write_bytes(b'synthetic engine identity; never executed')
        data = base / 'teacher.jsonl'
        data.write_text('synthetic fixture; loader is mocked\n')
        events, feedback, configs = [], [], []
        trained = 0
        class Researcher:
            tokens = 17
            def __init__(self, **kwargs):
                pass
            def identity(self):
                return {'name':'mock-model', 'digest':'mock-digest'}
            def propose(self, summary, audit):
                events.append('proposal')
                feedback.append(summary)
                return {'architecture':'mlp','depth':4,'min_leaf':1,'hidden_size':8,
                        'epochs':20,'learning_rate':0.03}
        def train(paths, output, game, config):
            nonlocal trained
            events.append('train')
            configs.append(config)
            directory = Path(output)
            directory.mkdir()
            final = directory / f'student-{trained}.json'
            initial = directory / f'untrained-{trained}.json'
            final.write_text('{}')
            initial.write_text('{}')
            result = dict(checkpoint=str(final), untrained_checkpoint=str(initial),
                          architecture='mlp', checkpoint_bytes=2, parameters=32,
                          training_seconds=0.01, sha256=f'mock-trained-{trained}')
            trained += 1
            return result
        def evaluate(executable, policy, game, *, split, budget):
            kind = 'noop' if isinstance(policy, loop.NoOpPolicy) else 'untrained' if 'untrained-' in policy.path else 'trained'
            events.append(f'evaluate-{split}-{kind}')
            if kind == 'noop':
                progress = 0.0
            elif kind == 'untrained':
                progress = initial_progress
            else:
                index = int(Path(policy.path).stem.rsplit('-',1)[1])
                progress = candidate_progress[index]
            return {'suite_id':f'synthetic-{split}', 'split':split,
                    'aggregate':dict(errors=0,wall_timeouts=0,success_rate=0,
                                     mean_progress=progress)}
        patches = [mock.patch.object(loop, 'require_worker'),
                   mock.patch.object(loop, 'OllamaResearcher', Researcher),
                   mock.patch.object(loop, 'train_candidates', train),
                   mock.patch.object(loop.StudentPolicy, 'load', side_effect=FakePolicy),
                   mock.patch.object(loop, 'evaluate_policy', evaluate)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        result = loop.run(str(engine), 'angry-birds', str(base/'output'), [str(data)],
                          rounds=len(candidate_progress), decisions=8,
                          max_ticks=600, max_seconds=600)
        return result, events, feedback, configs

    def test_only_validation_selects_then_holdout_runs_last(self):
        result, events, feedback, configs = self.pipeline([0.2, 0.1, 0.3])
        self.assertEqual([p['round'] for p in result['promotions']], [0, 2])
        self.assertTrue(result['selected_checkpoint'].endswith('student-2.json'))
        holdout = [i for i,event in enumerate(events) if event.startswith('evaluate-heldout')]
        self.assertTrue(holdout)
        self.assertGreater(min(holdout), max(i for i,event in enumerate(events) if event in ('proposal','train')))
        self.assertEqual(len(feedback), 2)
        for summary in feedback:
            # Feedback never contains final heldout results or a heldout report scope.
            self.assertNotIn('heldout', json.dumps(summary).lower())
            self.assertIn('incumbent_validation', summary)
        self.assertEqual(configs[0]['architecture'], 'mlp')
        self.assertEqual(configs[0]['max_candidates'], 1)

    def test_no_improvement_never_touches_heldout(self):
        result, events, _, _ = self.pipeline([0.0, 0.0], initial_progress=0.0)
        self.assertEqual(result['promotions'], [])
        self.assertIsNone(result['selected_checkpoint'])
        self.assertIsNone(result['final_evaluation'])
        self.assertFalse(any(event.startswith('evaluate-heldout') for event in events))
        self.assertIn('no candidate passed promotion', result['claim'])

    def test_policy_discovery_is_not_mislabeled_as_weight_learning_gain(self):
        result, _, _, _ = self.pipeline([0.2], initial_progress=0.4)
        self.assertEqual(len(result['promotions']), 1)
        experiment = result['experiments'][0]
        self.assertTrue(experiment['promotion']['promote'])
        self.assertFalse(experiment['training_gain']['promote'])
        self.assertLess(experiment['training_gain']['mean_progress_gain'], 0)
        self.assertIn('no base-LLM self-modification', result['claim'])


if __name__ == '__main__':
    unittest.main()
