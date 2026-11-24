"""Synthetic linked traces only; no model or simulator is launched."""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1] / 'src'
if SOURCE_ROOT.is_dir(): sys.path.insert(0, str(SOURCE_ROOT))
if importlib.util.find_spec('tiny_rsi.datasets') is not None:
    datasets = importlib.import_module('tiny_rsi.datasets')
else:
    spec = importlib.util.spec_from_file_location('tiny_rsi.datasets_candidate', '/tmp/tiny-rsi-datasets.py')
    datasets = importlib.util.module_from_spec(spec); spec.loader.exec_module(datasets)
from tiny_rsi.actor import action_schema
from tiny_rsi.distillation import load_rows
from tiny_rsi.prompts import messages_for_state


def fixture(game='angry-birds', level=0, success=True, height=2.5, episode='episode1', engine='b'*64):
    teacher = {'runtime':'ollama','role':'teacher','model':'qwen2.5:3b','digest':'a'*64}
    metadata = {'event':'metadata','protocol':1,'source':datasets.SOURCE,'runtime':'ollama','role':'teacher',
                'game':game,'level':level,'split':'train','prompt_version':datasets.PROMPT_VERSION,
                'engine_sha256':engine,'collector_sha256':'c'*64,'planner_source_sha256':'d'*64,
                'digest':teacher['digest'],'model':teacher['model'],'resolved_model':teacher['model'],'episode_id':episode}
    if game == 'angry-birds':
        observation = {'phase':'aiming','next_bird':'red','birds_left':3,'pigs_left':1,'score':0,'ability_ready':False,
                       'entities':[{'id':0,'kind':'pig','position':[850,600],'size':[40,40],'health':4.5}]}
        action = {'type':'launch','x':-85,'y':0,'ticks':30}
        recommendation = {'type':'launch','x':-75,'y':5,'ticks':30}
    else:
        observation = {'position':[-5,.55],'velocity':[0,0],'tip':[-3,1.8],'aim':[2,1.2],
                       'gripping':False,'grounded':True,'best_height':0,'falls':0,
                       'nearby_terrain':[[[-30,-5],[13,-5],[13,0],[-30,0]]],
                       'summit_height':66,'winning_body_height':65.75}
        action = {'type':'hammer','x':-2.19203,'y':-2.19203,'hold':False,'ticks':15}
        recommendation = {'type':'hammer','x':0,'y':-3.1,'hold':True,'ticks':15}
    before = {'ok':True,'protocol':1,'game':game,'observation':observation,
              'info':{'ticks':0,'max_ticks':18000,'success':False,'track':'structured-state'},
              'reward':0,'terminated':False,'truncated':False}
    after = copy.deepcopy(before);after['info']['ticks']=action['ticks'];after['info']['success']=success
    after['terminated']=success or game=='angry-birds'
    if game=='angry-birds':
        after['observation'].update(phase='won' if success else 'lost',pigs_left=0 if success else 1,score=1000 if success else 0)
    else:
        after['observation'].update(position=[0,66] if success else [0,height+.55],best_height=65.45 if success else height)
    public = messages_for_state(game,before)
    teacher_prompt = copy.deepcopy(public)+[{'role':'user','content':json.dumps({'recommendation':recommendation})}]
    body = {'model':teacher['model'],'stream':False,'messages':teacher_prompt,'format':action_schema(game,before),'options':{'num_ctx':4096}}
    rid=episode+':0';raw=' '+json.dumps(action)+' '
    records = [metadata,
               {'event':'reset','request':{'op':'reset','game':game,'level':level},'response':before},
               {'event':'planner_tool','step':0,'tool':'plan_action','recommendation':recommendation,'cost':{'oracle_ticks':120}},
               {'event':'model_request','response_id':rid,'role':'teacher','request':body,
                'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()},
               {'event':'model_response','response_id':rid,'teacher':teacher,'content':raw,'prompt_tokens':64,'completion_tokens':24},
               {'event':'step','step':0,'source':datasets.SOURCE,'game':game,'level':level,'split':'train','episode_id':episode,
                'prompt_version':datasets.PROMPT_VERSION,'observation':copy.deepcopy(observation),'info':copy.deepcopy(before['info']),
                'student_prompt':public,'teacher_prompt':teacher_prompt,'teacher_response':raw,'teacher':teacher,
                'response_id':rid,'action':action,'response':after,'planner_recommendation':recommendation,
                'verification':{'action_valid':True,'engine_sha256':engine}},
               {'event':'summary','status':'ok','source':datasets.SOURCE,'runtime':'ollama','role':'teacher',
                'executed_actions':1,'invalid_actions':0,'decisions':1,'tokens':88,'final':copy.deepcopy(after)}]
    return records


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'dataset.jsonl'
        context=patch.object(datasets,'require_worker',lambda:None);context.start();self.addCleanup(context.stop)
    def write(self,records,name='trace.jsonl'):
        path=self.root/name
        path.write_bytes(b''.join(json.dumps(e,sort_keys=True).encode()+b'\n' for e in records))
        return path
    def extract(self,records=None,**kwargs):
        path=self.write(fixture() if records is None else records)
        return datasets.extract_teacher_rows([path],self.output,**kwargs)
    def test_valid_trace_becomes_only_canonical_rows_with_complete_lineage(self):
        records=fixture();path=self.write(records)
        report=datasets.extract_teacher_rows([path],self.output)
        row=json.loads(self.output.read_text())
        self.assertNotIn('event',row)
        self.assertEqual(row['teacher_response'],records[4]['content'])
        self.assertNotEqual(json.loads(row['teacher_response']),records[2]['recommendation'])
        self.assertEqual(row['lineage']['step_line'],6)
        self.assertEqual(row['lineage']['model_response_line'],5)
        self.assertEqual(row['lineage']['trace_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report['dataset_sha256'],hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertTrue(row['verification']['episode_success'])
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(Path(str(self.output)+'.manifest.json').stat().st_mode),0o600)
        loaded,sources=load_rows([str(self.output)])
        self.assertEqual(len(loaded),1)
        self.assertEqual(loaded[0]['target'],json.dumps(records[5]['action'],sort_keys=True,separators=(',',':')))
    def test_successful_ascent_remains_distinct_from_progress_only(self):
        report=self.extract(fixture(game='getting-over-it',success=True))
        self.assertTrue(report['sources'][0]['native_success'])
        self.assertFalse(report['sources'][0]['ascent_progress_only'])
    def test_native_success_flag_cannot_contradict_game_observation(self):
        records=fixture();records[5]['response']['observation']['phase']='lost'
        records[-1]['final']=copy.deepcopy(records[5]['response'])
        with self.assertRaisesRegex(ValueError,'phase'):self.extract(records)
        records=fixture(game='getting-over-it');records[5]['response']['observation']['position'][1]=1
        records[-1]['final']=copy.deepcopy(records[5]['response'])
        with self.assertRaisesRegex(ValueError,'summit height'):self.extract(records)
    def test_guard_precedes_input_reads_or_output_creation(self):
        with patch.object(datasets,'require_worker',side_effect=RuntimeError('not guest')):
            with self.assertRaises(RuntimeError):datasets.extract_teacher_rows(['/missing/trace'],self.output)
        self.assertFalse(self.output.exists())
    def test_failed_birds_rejected_even_with_progress_override(self):
        for override in (True,False):
            with self.assertRaisesRegex(ValueError,'success'):
                self.extract(fixture(success=False),require_success=override)
        self.assertFalse(self.output.exists())
    def test_ascent_requires_success_unless_progress_is_explicit(self):
        data=fixture(game='getting-over-it',success=False)
        with self.assertRaisesRegex(ValueError,'success'):self.extract(data)
        report=self.extract(data,require_success=False)
        self.assertTrue(report['sources'][0]['ascent_progress_only'])
        self.assertFalse(json.loads(self.output.read_text())['verification']['episode_success'])
    def test_tiny_ascent_progress_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'1m'):
            self.extract(fixture(game='getting-over-it',success=False,height=.1),require_success=False)
    def test_holdout_or_validation_scope_rejected_before_output(self):
        for level in (6,7,8,11):
            with self.assertRaisesRegex(ValueError,'heldout'):self.extract(fixture(level=level))
        self.assertFalse(self.output.exists())
    def test_raw_planner_does_not_become_a_model_teacher(self):
        records=fixture();records[0]['runtime']='planner'
        with self.assertRaisesRegex(ValueError,'Planner-only'):self.extract(records)
    def test_label_cannot_be_substituted_for_the_model_response(self):
        records=fixture();records[5]['teacher_response']=json.dumps(records[2]['recommendation'])
        with self.assertRaisesRegex(ValueError,'actual Ollama response'):self.extract(records)
    def test_model_response_identity_must_match_metadata(self):
        records=fixture();records[4]['teacher']=dict(records[4]['teacher'],digest='e'*64)
        with self.assertRaisesRegex(ValueError,'identity differs'):self.extract(records)
    def test_response_id_must_link_to_actual_model_response(self):
        records=fixture();records[5]['response_id']='other:0'
        with self.assertRaisesRegex(ValueError,'unique actual model response'):self.extract(records)
    def test_student_prompt_cannot_receive_the_planner_answer(self):
        records=fixture();records[5]['student_prompt']=records[5]['teacher_prompt']
        with self.assertRaisesRegex(ValueError,'leaks tool'):self.extract(records)
    def test_rejected_native_action_cannot_be_extracted(self):
        records=fixture();records[5]['response']['ok']=False
        with self.assertRaisesRegex(ValueError,'native acceptance'):self.extract(records)
    def test_boolean_acceptance_proof_is_not_an_integer(self):
        records=fixture();records[5]['verification']['action_valid']=1
        with self.assertRaisesRegex(ValueError,'acceptance'):self.extract(records)
    def test_native_engine_and_pre_action_state_must_match(self):
        records=fixture();records[5]['verification']['engine_sha256']='e'*64
        with self.assertRaisesRegex(ValueError,'engine proof'):self.extract(records)
        records=fixture();records[5]['info']['ticks']=1
        with self.assertRaisesRegex(ValueError,'pre-action'):self.extract(records)
    def test_request_hash_and_summary_counts_are_checked(self):
        records=fixture();records[3]['request_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'request SHA256'):self.extract(records)
        records=fixture();records[-1]['tokens']=87
        with self.assertRaisesRegex(ValueError,'accounting'):self.extract(records)
        records=fixture();records[-1]['executed_actions']=True
        with self.assertRaisesRegex(ValueError,'integers'):self.extract(records)
    def test_truncated_or_appended_trace_is_not_complete_evidence(self):
        records=fixture()
        with self.assertRaisesRegex(ValueError,'complete teacher summary'):self.extract(records[:-1])
        with self.assertRaisesRegex(ValueError,'after its final summary'):self.extract(records+[{'event':'extra'}])
    def test_duplicate_json_keys_are_rejected(self):
        path=self.write(fixture());raw=path.read_bytes();raw=raw.replace(b'"protocol": 1',b'"protocol": 0, "protocol": 1',1);path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'Duplicate JSON key'):
            datasets.extract_teacher_rows([path],self.output)
    def test_duplicate_episode_or_engine_mix_is_rejected(self):
        first=self.write(fixture(),'one.jsonl');same=self.write(fixture(),'copy.jsonl')
        with self.assertRaisesRegex(ValueError,'Duplicate teacher trace'):
            datasets.extract_teacher_rows([first,same],self.output)
        other=self.write(fixture(episode='episode2',engine='e'*64),'different.jsonl')
        with self.assertRaisesRegex(ValueError,'Different engine'):
            datasets.extract_teacher_rows([first,other],self.output)
    def test_byte_and_row_budgets_are_fail_closed(self):
        for name,value in (('MAX_FILE_BYTES',10),('MAX_RECORD_BYTES',10),('MAX_DATA_BYTES',10),('MAX_ROWS',0),('MAX_OUTPUT_BYTES',10)):
            with self.subTest(name=name),patch.object(datasets,name,value):
                with self.assertRaises(ValueError):self.extract()
                self.assertFalse(self.output.exists())
    def test_existing_output_or_manifest_is_never_overwritten(self):
        self.output.write_text('original')
        with self.assertRaises(FileExistsError):self.extract()
        self.assertEqual(self.output.read_text(),'original');self.output.unlink()
        manifest=Path(str(self.output)+'.manifest.json');manifest.write_text('original manifest')
        with self.assertRaises(FileExistsError):self.extract()
        self.assertFalse(self.output.exists());self.assertEqual(manifest.read_text(),'original manifest')
    def test_manifest_creation_race_cleans_only_new_dataset(self):
        original_open=os.open;manifest=Path(str(self.output)+'.manifest.json')
        def racing_open(path,*args,**kwargs):
            if Path(path)==manifest:manifest.write_text('other writer')
            return original_open(path,*args,**kwargs)
        with patch.object(datasets.os,'open',side_effect=racing_open):
            with self.assertRaises(FileExistsError):self.extract()
        self.assertFalse(self.output.exists());self.assertEqual(manifest.read_text(),'other writer')


if __name__=='__main__':unittest.main()
