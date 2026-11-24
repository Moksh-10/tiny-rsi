#!/usr/bin/env python3
"""Verify a trajectory against a trusted game-env executable; never executes model text."""
import argparse
import json
import math
import subprocess


def equal(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5)
    return a == b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trajectory')
    parser.add_argument('--env', required=True)
    args = parser.parse_args()
    count = 0
    with subprocess.Popen([args.env], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
        try:
            with open(args.trajectory) as source:
                for line in source:
                    event = json.loads(line)
                    if event['event'] == 'reset':
                        request = event['request']
                    elif event['event'] == 'step' and event.get('response') is not None:
                        request = dict(op='act', action=event['action'])
                    else:
                        continue
                    process.stdin.write(json.dumps(request) + '\n')
                    process.stdin.flush()
                    actual = json.loads(process.stdout.readline())
                    if not equal(actual, event['response']):
                        raise RuntimeError(f"Replay diverged at record {count}: {actual}")
                    count += 1
        finally:
            process.stdin.close()
            process.wait(timeout=5)
    if count < 2:
        raise RuntimeError('Trajectory contains no replayable actions')
    print(f'Verified {count} reset/action responses')


if __name__ == '__main__':
    main()
