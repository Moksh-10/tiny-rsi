import json
from pathlib import Path
import tempfile
import unittest
from tiny_rsi.models import DEFAULT_ROLES, load_roles


class ModelRoles(unittest.TestCase):
    def test_roles_are_actual_model_names(self):
        config=load_roles()
        self.assertEqual({role: entry['model'] for role,entry in config['roles'].items()}, DEFAULT_ROLES)
        self.assertNotEqual(config['roles']['teacher']['model'],config['roles']['student']['model'])

    def test_external_inference_and_unbounded_context_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'models.json'
            config=load_roles();config['endpoint']='https://external.example/api'
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):load_roles(path)
            config=load_roles();config['roles']['student']['context_tokens']=100000
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):load_roles(path)
