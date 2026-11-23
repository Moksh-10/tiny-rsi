"""Transport and evaluation tests use a fake simulator, never model gameplay."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import stat
from types import SimpleNamespace
from unittest import mock
import textwrap
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.environment import GameEnvironment, VectorEnvironment, EnvironmentError, InvalidAction, require_worker
from research.evaluation import (EpisodeBudget, NoOpPolicy, RandomPolicy,
                                compare_reports, evaluate_policy)

FAKE_ENGINE = '''
import json,sys
state=None
for line in sys.stdin:
 q=json.loads(line)
 if q['op']=='reset':
  state=dict(ok=True,protocol=1,game=q['game'],observation=dict(phase='aiming',pigs_left=2,score=0,ability_ready=False,best_height=0),reward=0,terminated=False,truncated=False,info=dict(ticks=0,max_ticks=18000,success=False))
  result=state
 elif q['op']=='act':
  a=q['action']
  if a.get('type') not in ('wait','launch','hammer') or type(a.get('ticks')) is not int or not 1<=a['ticks']<=120:
   result=dict(ok=False,error='invalid action')
  elif state['terminated']:
   result=dict(ok=False,error='finished')
  else:
   state['info']['ticks']+=a['ticks']
   state['observation']['score']+=1
   state['observation']['best_height']+=0.1
   if a['type']=='launch':state['observation']['pigs_left']-=1
   state['terminated']=state['observation']['pigs_left']==0
   state['info']['success']=state['terminated']
   state['reward']=1
   result=state
 else:result=state
 print(json.dumps(result),flush=True)
'''

class ResearchEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.executable=Path(self.temp.name)/'fake-env'
        self.executable.write_text('#!'+sys.executable+'\n'+textwrap.dedent(FAKE_ENGINE))
        self.executable.chmod(0o755)
    def tearDown(self):self.temp.cleanup()

    def test_worker_guard_rejects_host_root_and_symlink_markers(self):
        with mock.patch('research.environment.platform.system',return_value='Darwin'):
            with self.assertRaises(RuntimeError):require_worker()
        with mock.patch('research.environment.platform.system',return_value='Linux'):
            with mock.patch('research.environment.os.geteuid',return_value=0):
                with self.assertRaises(RuntimeError):require_worker()
            with mock.patch('research.environment.os.geteuid',return_value=1001):
                for mode in (stat.S_IFLNK|0o444,stat.S_IFREG|0o666):
                    with mock.patch('research.environment.Path.lstat',return_value=SimpleNamespace(st_mode=mode,st_uid=0)):
                        with self.assertRaises(RuntimeError):require_worker()

    def test_persistent_reset_and_invalid_atomicity(self):
        with GameEnvironment(self.executable,'angry-birds') as env:
            observation, info=env.reset(seed=0)
            self.assertFalse(info['layout_randomized'])
            self.assertEqual(observation['score'],0)
            state=copy.deepcopy(env.state)
            with self.assertRaises(InvalidAction):env.act(dict(type='shell',ticks=1))
            self.assertEqual(env.state,state)
            self.assertEqual(env.observe(),state)
            observation,reward,term,trunc,info=env.step(dict(type='wait',ticks=2))
            self.assertEqual(observation['score'],1)
            self.assertEqual(info['ticks'],2)
            self.assertEqual(reward,1)
            self.assertFalse(term or trunc)
            for seed in (42,False,0.0):
                with self.assertRaises(ValueError):env.reset(seed=seed)
            self.assertEqual(env.state['info']['ticks'],2)
            env.reset()
            self.assertEqual(env.state['info']['ticks'],0)
        self.assertIsNotNone(env.process.poll())

    def test_transport_timeout_kills_child(self):
        with GameEnvironment(self.executable,'angry-birds',timeout=.05,
                             command=[sys.executable,'-c','import time;time.sleep(5)']) as env:
            started=time.monotonic()
            with self.assertRaises(EnvironmentError):env.reset()
            self.assertLess(time.monotonic()-started,1)
            self.assertIsNotNone(env.process.poll())

    def test_oversized_or_malformed_response_closes_child(self):
        for program in ('print("x"*1100000,flush=True)', 'print("[]",flush=True)'):
            with GameEnvironment(self.executable,'angry-birds',
                                 command=[sys.executable,'-c',program]) as env:
                with self.assertRaises(EnvironmentError):env.reset()
                self.assertIsNotNone(env.process.poll())

    def test_vector_independent_state_and_shape(self):
        with VectorEnvironment(self.executable,[('angry-birds',0),('angry-birds',1)],max_workers=2) as vector:
            self.assertEqual(len(vector.reset()),2)
            with self.assertRaises(ValueError):vector.step([dict(type='wait',ticks=2)])
            results=vector.step([dict(type='wait',ticks=2),dict(type='wait',ticks=3)])
            self.assertEqual([r[4]['ticks'] for r in results],[2,3])
        self.assertTrue(all(e.process.poll() is not None for e in vector.envs))

    def test_equal_budget_and_promotion_gate(self):
        budget=EpisodeBudget(max_decisions=3,max_ticks=5,timeout_seconds=1)
        baseline=evaluate_policy(self.executable,NoOpPolicy('angry-birds'),'angry-birds',
                                 budget=budget,require_sandbox=False)
        candidate=evaluate_policy(self.executable,lambda o,i:dict(type='launch',x=-60,y=0,ticks=2),
                                  'angry-birds',budget=budget,require_sandbox=False)
        self.assertTrue(compare_reports(baseline,candidate)['promote'])
        self.assertEqual(baseline['levels'],(6,7))
        self.assertEqual([e['ticks'] for e in baseline['episodes']],[5,5])
        other=evaluate_policy(self.executable,NoOpPolicy('angry-birds'),'angry-birds',
                              budget=EpisodeBudget(max_decisions=2),require_sandbox=False)
        with self.assertRaises(ValueError):compare_reports(baseline,other)
        with self.assertRaises(ValueError):evaluate_policy(self.executable,NoOpPolicy('angry-birds'),
                                      'angry-birds',levels=[8],require_sandbox=False)

    def test_invalid_attempts_and_wall_deadline(self):
        report=evaluate_policy(self.executable,lambda o,i:dict(type='shell',ticks=2),
                               'getting-over-it',budget=EpisodeBudget(max_invalid=2),require_sandbox=False)
        e=report['episodes'][0]
        self.assertEqual((e['invalid_actions'],e['ticks'],e['reason']),(2,0,'invalid_action_limit'))
        self.assertFalse(report['unseen_layout_generalization'])
        def slow(o,i):time.sleep(.2);return dict(type='wait',ticks=1)
        report=evaluate_policy(self.executable,slow,'angry-birds',
                               budget=EpisodeBudget(timeout_seconds=.05),require_sandbox=False)
        self.assertEqual(report['aggregate']['wall_timeouts'],2)

    def test_random_policy_reset_and_shared_policy_reset(self):
        policy=RandomPolicy('getting-over-it',7)
        one=policy({},{});policy.reset();self.assertEqual(one,policy({},{}))

    @unittest.skipUnless(importlib.util.find_spec('gymnasium'),'optional Gymnasium not installed')
    def test_optional_gymnasium_contract(self):
        from research.environment import make_gymnasium
        from gymnasium.utils.env_checker import check_env
        with make_gymnasium(self.executable,'angry-birds',[dict(type='wait',ticks=15)]) as env:
            check_env(env,skip_render_check=True)

if __name__=='__main__':unittest.main()
