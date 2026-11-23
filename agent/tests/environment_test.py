"""Protocol contracts, invalid-action atomicity, termination and deterministic replays."""
import json
import subprocess
import sys
import unittest

EXE = sys.argv.pop()

class Protocol(unittest.TestCase):
    def setUp(self):
        self.p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def tearDown(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)
        self.p.stdout.close()
    def q(self, request):
        self.p.stdin.write(json.dumps(request) + '\n')
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
    def reset(self, game, level=0):
        return self.q(dict(op='reset', game=game, level=level))
    def act(self, **action):
        return self.q(dict(op='act', action=action))
    def test_validation_is_atomic(self):
        for game in ['angry-birds', 'getting-over-it']:
            before = self.reset(game)
            bad = [dict(type='launch',x=-90,y=90,ticks=1), dict(type='wait', ticks=121),
                   dict(type='hammer',x=1,y=2,hold='yes',ticks=10), dict(type='shell',ticks=1),
                   dict(type='wait',ticks=1,extra='no'), dict(type='wait',ticks=1.2), dict(type='wait',ticks=1.0000000001)]
            for a in bad:
                self.assertFalse(self.q(dict(op='act',action=a))['ok'])
                self.assertEqual(before,self.q(dict(op='observe')))
    def test_replay_and_all_levels(self):
        for level in range(12):
            first=self.reset('angry-birds',level)
            self.assertTrue(first['ok'])
            actions=[dict(type='launch',x=-75,y=45,ticks=120)]+[dict(type='wait',ticks=120)]*4
            one=[self.q(dict(op='act',action=a)) for a in actions]
            self.assertEqual(first,self.reset('angry-birds',level))
            two=[self.q(dict(op='act',action=a)) for a in actions]
            self.assertEqual(one,two)
            self.assertTrue(one[0]['ok'])
        self.assertFalse(self.reset('angry-birds',12)['ok'])
    def test_ascent_and_truncation(self):
        initial=self.reset('getting-over-it')
        actions=[dict(type='hammer',x=3,y=-1,hold=True,ticks=120),dict(type='hammer',x=-2,y=-1,hold=True,ticks=120)]
        one=[self.q(dict(op='act',action=a)) for a in actions]
        self.assertNotEqual(initial['observation'],one[-1]['observation'])
        self.reset('getting-over-it')
        self.assertEqual(one,[self.q(dict(op='act',action=a)) for a in actions])
        for _ in range(148):
            r=self.act(type='hammer',x=0,y=2,hold=False,ticks=120)
        self.assertTrue(r['truncated'])
        self.assertEqual(r['info']['ticks'],18000)
        self.assertFalse(self.act(type='hammer',x=0,y=2,hold=False,ticks=1)['ok'])
    def test_oversized_and_malformed_records(self):
        self.p.stdin.write('x'*70000+'\n{bad\n');self.p.stdin.flush()
        for _ in range(2):self.assertFalse(json.loads(self.p.stdout.readline())['ok'])
        self.assertTrue(self.q(dict(op='describe'))['ok'])

if __name__ == '__main__': unittest.main()
