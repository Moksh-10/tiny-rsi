"""Validation/masking/budget tests only: no framework installation or model training."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

try:
    from tiny_rsi import distillation as d
except ModuleNotFoundError:
    SOURCE = Path('/tmp/tiny-rsi-distillation.py')
    SPEC = importlib.util.spec_from_file_location('distillation_under_test', SOURCE)
    d = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(d)


def row():
    return {'game':'angry-birds','level':0,'split':'train',
            'student_prompt':[{'role':'system','content':'Choose one action.'},
                              {'role':'user','content':'Current game observation'}],
            'teacher_response':'{"type":"launch","x":-75,"y":5,"ticks":30}',
            'teacher':{'runtime':'ollama','role':'teacher','model':'qwen2.5:3b','digest':'a'*64},
            'verification':{'action_valid':True}}


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        if messages[-1]['role'] == 'assistant':
            return [10,11,20,21,22]
        return [10,11]


class DistillationTests(unittest.TestCase):
    def test_actual_teacher_provenance_and_accepted_action_are_required(self):
        self.assertEqual(d.validate_row(row())['teacher']['runtime'],'ollama')
        for key,value in [('runtime','planner'),('role','student'),('digest','short')]:
            bad=row();bad['teacher'][key]=value
            with self.assertRaises(ValueError):d.validate_row(bad)
        for proof in ({},{'action_valid':False},{'action_valid':1}):
            bad=row();bad['verification']=proof
            with self.assertRaises(ValueError):d.validate_row(bad)

    def test_validation_and_holdout_labels_rejected(self):
        for level in range(6,12):
            bad=row();bad['level']=level
            with self.assertRaisesRegex(ValueError,'heldout'):d.validate_row(bad)
        bad=row();bad['split']='validation'
        with self.assertRaises(ValueError):d.validate_row(bad)
        bad=row();bad['level']=True
        with self.assertRaises(ValueError):d.validate_row(bad)

    def test_action_validation_does_not_execute_model_text(self):
        for content in ['print(1)','{} {}','{"type":"launch","x":NaN,"y":0,"ticks":30}',
                        '{"type":"launch","x":95,"y":95,"ticks":30}',
                        '{"type":"wait","ticks":30,"shell":"echo nope"}']:
            bad=row();bad['teacher_response']=content
            with self.assertRaises(ValueError):d.validate_row(bad)
        with self.assertRaises(ValueError):d.motor_action('getting-over-it','{"type":"hammer","x":1,"y":1,"hold":1,"ticks":15}')

    def test_masking_supervises_only_teacher_response_and_turn_end(self):
        encoded=d.tokenize_rows(FakeTokenizer(),[d.validate_row(row())])[0]
        self.assertEqual(encoded['input_ids'],[10,11,20,21,22])
        self.assertEqual(encoded['labels'],[-100,-100,20,21,22])
        self.assertEqual(encoded['prompt_tokens'],2)
        self.assertEqual(encoded['target_tokens'],3)

    def test_target_never_silently_truncated(self):
        with self.assertRaisesRegex(ValueError,'silently truncate'):
            d.tokenize_rows(FakeTokenizer(),[d.validate_row(row())],sequence_length=4)
        class BadPrefix(FakeTokenizer):
            def apply_chat_template(self,messages,**kwargs):
                return [9,20,21] if messages[-1]['role']=='assistant' else [10,11]
        with self.assertRaisesRegex(ValueError,'matching assistant prefix'):
            d.tokenize_rows(BadPrefix(),[d.validate_row(row())])

    def test_data_budgets_and_file_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'teacher.jsonl'
            path.write_text(json.dumps(row())+'\n')
            rows,sources=d.load_rows([str(path)])
            self.assertEqual(len(rows),1)
            self.assertEqual(sources[0]['sha256'],d.sha256_file(path))
            path.write_text(json.dumps(row())+'\n'+json.dumps(row())+'\n')
            with self.assertRaisesRegex(ValueError,'row budget'):
                d.load_rows([str(path)],max_rows=1)
            path.write_text('\n')
            with self.assertRaisesRegex(ValueError,'Blank'):d.load_rows([str(path)])

    def test_prompt_role_and_content_guards(self):
        for prompt in ['',None,[{'role':'assistant','content':'I already chose an action'}],
                       [{'role':'system','content':'Only a system without observation'}],
                       [{'role':'user','content':'x','extra':'ignored?'}]]:
            bad=row();bad['student_prompt']=prompt
            with self.assertRaises(ValueError):d.validate_row(bad)

    def test_base_must_be_resource_bounded_safetensors(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            config=dict(d.QWEN_CONFIG,architectures=['Qwen2ForCausalLM'])
            (p/'config.json').write_text(json.dumps(config))
            (p/'tokenizer.json').write_text('{}')
            (p/'tokenizer_config.json').write_text('{}')
            (p/'model.safetensors').write_bytes(b'synthetic: never passed to a model loader')
            self.assertEqual(d.validate_base(p)[0],p.resolve())
            (p/'pytorch_model.bin').write_bytes(b'not a real pickle; rejection fixture')
            with self.assertRaisesRegex(ValueError,'Pickle'):d.validate_base(p)
            (p/'pytorch_model.bin').unlink()
            config['hidden_size']=4096
            (p/'config.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'architecture'):d.validate_base(p)

    def test_nested_deadline_restores_elapsed_outer_budget(self):
        with mock.patch.object(d.signal,'getsignal',return_value=d.signal.SIG_DFL), \
             mock.patch.object(d.signal,'getitimer',return_value=(0.5,0)), \
             mock.patch.object(d.signal,'signal'), \
             mock.patch.object(d.signal,'setitimer') as timer, \
             mock.patch.object(d.time,'monotonic',side_effect=[10,10.1]):
            with d.deadline(0.25):pass
        self.assertEqual(timer.call_args_list[0].args,(d.signal.ITIMER_REAL,0.25))
        self.assertAlmostEqual(timer.call_args_list[-1].args[1],0.4)

    def test_host_guard_runs_before_heavy_imports(self):
        import builtins
        original = builtins.__import__
        attempted = []
        def checked(name, *args, **kwargs):
            if name.split('.')[0] in ('torch','transformers','peft'):
                attempted.append(name)
                raise AssertionError('Host guard imported a heavy dependency')
            return original(name,*args,**kwargs)
        with mock.patch.object(d.sys,'platform','darwin'), mock.patch.object(builtins,'__import__',side_effect=checked):
            with self.assertRaisesRegex(RuntimeError,'Linux VM'):
                d.train('/nonexistent',[], '/nonexistent')
        self.assertEqual(attempted, [])


if __name__=='__main__':unittest.main()
