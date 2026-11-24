"""Shared compact public-state prompts for Ollama inference and response distillation."""
import json
import math

PROMPT_VERSION = 'compact-state-v1'


def compact_system(game):
    if game == 'angry-birds':
        return ('Remove all pigs. Pixels: x right, y down. Pull x<0 shoots right; y>0 shoots up. '
                'Pull length 8..95. JSON actions: launch(x,y,ticks), wait(ticks), ability(ticks). '
                'Wait during flight. ticks:15,30,60,120. Return one JSON object.')
    if game == 'getting-over-it':
        return ('Climb to the summit. Meters: x right,y up. Hammer x,y is shoulder-relative aim, '
                'reach<=3.15. hold=true grips terrain; change aim while anchored to push/pull. '
                'JSON: type=hammer,x,y,hold,ticks. ticks:15,30,60,120. Return one JSON object.')
    raise ValueError('Unsupported game')


def _pair(value, digits=2):
    return [round(float(value[0]), digits), round(float(value[1]), digits)]


def compact_observation(game, state):
    o = state.get('observation', state)
    if game == 'angry-birds':
        entities = o.get('entities', [])
        pigs = sorted((e for e in entities if e.get('kind') == 'pig'), key=lambda e:e['position'][0])
        result = {'phase':o['phase'], 'flock':[o['next_bird'],o['birds_left']],
                  'pigs':[_pair(e['position'],0) for e in pigs[:3]], 'ability':o['ability_ready']}
        if o['phase'] == 'aiming':
            structures = sorted((e for e in entities if e.get('kind') not in ('pig','bird')),
                                key=lambda e:e['position'][0])
            result['targets'] = [[e['kind'], *_pair(e['position'],0), *_pair(e['size'],0)] for e in structures[:3]]
        else:
            birds = [e for e in entities if e.get('kind') == 'bird']
            if birds:
                result['bird'] = _pair(birds[-1]['position'],0) + _pair(birds[-1]['velocity'],0)
        return result
    if game != 'getting-over-it':
        raise ValueError('Unsupported game')
    x,y=o['position'];ledges=[]
    for polygon in o.get('nearby_terrain', []):
        top=max(p[1] for p in polygon)
        upper=[p for p in polygon if p[1]>=top-.2]
        left,right=min(p[0] for p in upper),max(p[0] for p in upper)
        distance=math.hypot(max(left-x,0,x-right),top-y)
        ledges.append((distance,[round(left,2),round(right,2),round(top,2)]))
    return {'p':_pair(o['position']), 'v':_pair(o['velocity']), 'tip':_pair(o['tip']),
            'aim':_pair(o['aim']), 'grip':bool(o['gripping']),
            'ledges':[ledge for _,ledge in sorted(ledges)[:3]]}


def messages_for_state(game,state):
    return [{'role':'system','content':compact_system(game)},
            {'role':'user','content':json.dumps(compact_observation(game,state),separators=(',',':'),allow_nan=False)}]
