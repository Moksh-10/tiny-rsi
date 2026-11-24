"""Unified entry point; command names are trusted operator input, never model code."""
import importlib
import sys

COMMANDS = {'play': 'actor', 'plan': 'planner', 'policy-train': 'policy',
            'evaluate': 'evaluation', 'policy-experiment': 'policy_experiments', 'replay': 'replay', 'teacher-collect': 'model_teacher',
            'distill': 'distillation', 'model-evaluate': 'model_evaluation', 'dataset': 'datasets'}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print('Usage: tiny-rsi {' + ','.join(COMMANDS) + '} [options]')
        return
    command = sys.argv.pop(1)
    if command not in COMMANDS:
        raise SystemExit('Unknown command: ' + command)
    return importlib.import_module('.' + COMMANDS[command], __package__).main()


if __name__ == '__main__':
    raise SystemExit(main())
