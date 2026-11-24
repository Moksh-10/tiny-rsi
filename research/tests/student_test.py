"""Synthetic numerical unit tests only; no game agent rollout or real-data training."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'tiny_rsi' / 'policy.py'
SPEC = importlib.util.spec_from_file_location('student_under_test', SOURCE)
student = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(student)


class StudentTests(unittest.TestCase):
    def test_cart_learns_a_data_threshold(self):
        xs = [[-2.0], [-0.2], [0.3], [1.0]]
        ys = [0, 0, 1, 1]
        model = student.tree_fit(xs, ys, 2, depth=2)
        self.assertEqual([student.predict_index(model, x) for x in xs], ys)
        self.assertAlmostEqual(model['root']['threshold'], 0.05)
        self.assertEqual(student.predict_index(model, [-0.1]), 0)
        self.assertEqual(student.predict_index(model, [0.2]), 1)

    def test_neural_backprop_learns_nonlinear_xor(self):
        xs = [[-1.0, -1.0], [-1.0, 1.0], [1.0, -1.0], [1.0, 1.0]]
        ys = [0, 1, 1, 0]
        model = student.neural_fit(xs, ys, 2, hidden=8, epochs=800, learning_rate=0.1, seed=2)
        self.assertEqual([student.predict_index(model, x) for x in xs], ys)
        self.assertLess(model['training_loss'][-1], model['training_loss'][0] * 0.1)
        # Both layers contain learned nonzero parameters, rather than a lookup table.
        self.assertEqual(student.model_parameters(model), 42)

    def test_features_have_fixed_finite_size(self):
        for game in student.GAMES:
            empty = student.features(game, {})
            actual = student.features(game, {'position': [2, 60], 'velocity': [0, 2], 'tip': [1, 62], 'aim': [1, 2]})
            self.assertEqual(len(empty), len(actual))
            self.assertTrue(all(math.isfinite(v) for v in actual))
        self.assertNotEqual(student.features('getting-over-it', {'position': [0, 50]}),
                            student.features('getting-over-it', {'position': [0, 60]}))

    def test_validation_and_holdout_labels_cannot_train(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'data.jsonl'
            for level, split in [(6, 'train'), (8, 'train'), (0, 'heldout')]:
                p.write_text(json.dumps(dict(game='angry-birds', level=level, split=split,
                    observation={'phase': 'aiming'}, action={'type':'wait','ticks':120}))+'\n')
                with self.assertRaisesRegex(ValueError, 'held-out'):
                    student.load_examples([str(p)], 'angry-birds')

    def test_trajectory_pairs_pre_action_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'data.jsonl'
            rows = [dict(event='metadata', game='angry-birds', level=0),
                    dict(event='reset', response={'observation': {'phase':'aiming'}, 'info':{'ticks':0}}),
                    dict(event='step', action={'type':'wait','ticks':120},
                         response={'ok':True,'observation':{'phase':'flying'},'info':{'ticks':120}}),
                    dict(event='summary',final={'info':{'success':True}})]
            p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            examples, _ = student.load_examples([str(p)], 'angry-birds')
            self.assertEqual(examples[0]['x'], student.features('angry-birds', {'phase':'aiming'}, {'ticks':0}))

    def test_checkpoint_rejects_nan_weights_and_masks_illegal_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'policy.json'
            dimensions = len(student.features('angry-birds', {}))
            checkpoint = dict(format='game-student-v1', feature_version=1, game='angry-birds',
                actions=[{'type':'launch','x':-75,'y':5,'ticks':120}],
                model=dict(architecture='tree', dimensions=dimensions, classes=1, root={'class':0, 'counts':[1]}))
            p.write_text(json.dumps(checkpoint))
            policy = student.PolicyBaseline.load(p)
            self.assertEqual(policy({'phase':'flying'}), {'type':'wait','ticks':120})
            self.assertEqual(policy({'phase':'aiming'})['type'], 'launch')
            checkpoint['model'] = dict(architecture='mlp', dimensions=dimensions, classes=1,
                w1=[[float('nan')]*dimensions], b1=[0], w2=[[0]], b2=[0])
            p.write_text(json.dumps(checkpoint))
            with self.assertRaisesRegex(ValueError, 'weights'):
                student.PolicyBaseline.load(p)

    def test_model_proposals_are_bounded_json_data(self):
        for config in [{'epochs':[100000]}, {'hidden_sizes':[1000]}, {'max_seconds':-1}, {'shell':'oops'}]:
            with self.assertRaises(ValueError):
                student._config(config)


if __name__ == '__main__':
    unittest.main()
