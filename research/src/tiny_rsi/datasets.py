"""Extract canonical language labels from linked, successful Ollama teacher traces.

This validates recorded provenance/acceptance links, not cryptographic remote
attestation. It never executes model text, starts a simulator, calls a model,
changes a split, or turns planner-only demonstrations into model responses.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

from .actor import action_from
from .distillation import validate_row
from .environment import require_worker
from .model_teacher import SOURCE
from .prompts import PROMPT_VERSION, messages_for_state

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_DATA_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_ROWS = 4096
MAX_PATHS = 64
SHA = re.compile(r'[0-9a-f]{64}')


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key in teacher trace')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON value in teacher trace: ' + value)
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid or excessively nested teacher trace JSON') from exc
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Nonfinite teacher trace number')
        if isinstance(value, dict):
            for item in value.values(): finite(item)
        elif isinstance(value, list):
            for item in value: finite(item)
    finite(result)
    if not isinstance(result, dict):
        raise ValueError('Teacher trace record must be an object')
    return result


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _digest(value, label):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError('Invalid full SHA256: ' + label)
    return value


def _identity(value, expected=None):
    if not isinstance(value, dict) or value.get('runtime') != 'ollama' or value.get('role') != 'teacher':
        raise ValueError('Actual Ollama teacher identity is required')
    model = value.get('model')
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        raise ValueError('Invalid teacher model identity')
    result = dict(runtime='ollama', role='teacher', model=model,
                  digest=_digest(value.get('digest'), 'teacher model'))
    if expected is not None and result != expected:
        raise ValueError('Teacher identity differs between metadata and response')
    return result


def _scope(value, metadata=None):
    game, level = value.get('game'), value.get('level')
    if game not in ('angry-birds', 'getting-over-it') or type(level) is not int:
        raise ValueError('Explicit game and integer level required')
    if value.get('split') != 'train' or not 0 <= level < (6 if game == 'angry-birds' else 1):
        raise ValueError('Validation/heldout labels cannot enter training extraction')
    if metadata and (game, level) != (metadata['game'], metadata['level']):
        raise ValueError('Step game/level differs from trace metadata')
    return game, level


def _native(state, game):
    if not isinstance(state, dict) or state.get('ok') is not True or state.get('game') != game:
        raise ValueError('Recorded native acceptance is missing or belongs to another game')
    if not isinstance(state.get('observation'), dict) or not isinstance(state.get('info'), dict):
        raise ValueError('Incomplete recorded native state')
    if type(state.get('terminated')) is not bool or type(state.get('truncated')) is not bool:
        raise ValueError('Native termination/truncation must be booleans')
    info = state['info']
    if type(info.get('ticks')) is not int or not 0 <= info['ticks'] <= 18000:
        raise ValueError('Invalid native simulation tick counter')
    if type(info.get('success')) is not bool:
        raise ValueError('Native success must be boolean')
    return state


def _read_trace(filename, require_success, remaining_bytes=MAX_DATA_BYTES):
    path = Path(filename)
    initial = path.stat()
    if not stat.S_ISREG(initial.st_mode) or not 0 < initial.st_size <= min(MAX_FILE_BYTES, remaining_bytes):
        raise ValueError('Teacher trace must be a nonempty regular file within file/total byte budgets')
    digest, total, metadata, identity, current = hashlib.sha256(), 0, None, None, None
    requests, responses, tools, consumed, rows = {}, {}, {}, set(), []
    summary = None
    accepted = rejected = tokens = 0
    with path.open('rb') as source:
        for line_number in range(1, 100000):
            line = source.readline(MAX_RECORD_BYTES + 1)
            if not line:
                break
            total += len(line)
            if total > min(MAX_FILE_BYTES, remaining_bytes) or len(line) > MAX_RECORD_BYTES or not line.strip():
                raise ValueError('Blank, oversized or excessive teacher trace record')
            digest.update(line)
            event = _json(line)
            kind = event.get('event')
            if summary is not None:
                raise ValueError('Teacher trace has records after its final summary')
            if metadata is None:
                if kind != 'metadata' or line_number != 1:
                    raise ValueError('Teacher trace must begin with metadata')
                metadata = event
                _scope(metadata)
                if metadata.get('protocol') != 1:
                    raise ValueError('Unsupported teacher trace protocol')
                if metadata.get('source') != SOURCE or metadata.get('runtime') != 'ollama' or metadata.get('role') != 'teacher':
                    raise ValueError('Planner-only or nonteacher traces are not language labels')
                if metadata.get('prompt_version') != PROMPT_VERSION:
                    raise ValueError('Teacher prompt version is not the current shared public prompt')
                for field in ('engine_sha256', 'collector_sha256', 'planner_source_sha256', 'digest'):
                    _digest(metadata.get(field), field)
                episode = metadata.get('episode_id')
                if not isinstance(episode, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', episode):
                    raise ValueError('Invalid teacher episode identity')
                identity = _identity({'runtime': 'ollama', 'role': 'teacher',
                                      'model': metadata.get('resolved_model'), 'digest': metadata['digest']})
                continue
            if kind == 'metadata':
                raise ValueError('Duplicate teacher metadata')
            if kind == 'reset':
                if current is not None or requests or rows:
                    raise ValueError('Duplicate or out-of-order teacher reset')
                if event.get('request') != {'op': 'reset', 'game': metadata['game'], 'level': metadata['level']}:
                    raise ValueError('Teacher reset differs from the declared training task')
                current = copy.deepcopy(_native(event.get('response'), metadata['game']))
                if current['info']['ticks'] != 0:
                    raise ValueError('Teacher reset must start at simulation tick zero')
                continue
            if current is None:
                raise ValueError('Teacher reset must precede all gameplay events')
            if kind == 'planner_tool':
                step = event.get('step')
                if type(step) is not int or step != len(requests) or step in tools or event.get('tool') != 'plan_action':
                    raise ValueError('Duplicate or out-of-order planning tool event')
                if not isinstance(event.get('recommendation'), dict) or not isinstance(event.get('cost'), dict):
                    raise ValueError('Malformed recorded planner assistance')
                for value in event['cost'].values():
                    if type(value) not in (int, float) or not 0 <= value <= 1e12:
                        raise ValueError('Invalid charged planning cost')
                tools[step] = (event, line_number)
                continue
            if kind == 'model_request':
                rid = event.get('response_id')
                expected = f"{metadata['episode_id']}:{len(requests)}"
                if rid != expected or rid in requests or len(requests) not in tools or event.get('role') != 'teacher':
                    raise ValueError('Teacher request is missing linked tool assistance or unique response ID')
                request = event.get('request')
                if not isinstance(request, dict) or request.get('model') != metadata.get('model') or request.get('stream') is not False:
                    raise ValueError('Teacher request does not identify the declared actual model')
                # This is the exact canonicalization used by the collecting runtime.
                request_digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
                if event.get('request_sha256') != request_digest:
                    raise ValueError('Teacher request SHA256 mismatch')
                requests[rid] = (event, line_number)
                if len(requests) > MAX_ROWS + 5:
                    raise ValueError("Teacher model-request budget exceeded")
                continue
            if kind == 'model_response':
                rid = event.get('response_id')
                if rid not in requests or rid in responses or len(responses) + 1 != len(requests):
                    raise ValueError('Teacher response lacks a unique preceding model request')
                _identity(event.get('teacher'), identity)
                if not isinstance(event.get('content'), str) or len(event['content'].encode()) > 16384:
                    raise ValueError('Actual teacher response content is missing or oversized')
                for field in ('prompt_tokens', 'completion_tokens'):
                    value = event.get(field)
                    if type(value) is not int or not 0 <= value <= 1000000000:
                        raise ValueError('Teacher response lacks valid model token charges')
                    tokens += value
                responses[rid] = (event, line_number)
                continue
            if kind in ('step', 'rejected_action'):
                step, rid = event.get('step'), event.get('response_id')
                if type(step) is not int or rid != f"{metadata['episode_id']}:{step}" or rid not in responses or rid in consumed:
                    raise ValueError('Native action lacks a unique actual model response')
                if step != len(consumed):
                    raise ValueError('Native action response order is inconsistent')
                consumed.add(rid)
                response_event, response_line = responses[rid]
                if kind == 'rejected_action':
                    rejected += 1
                    if rejected > 5:
                        raise ValueError("Teacher invalid-action limit was exceeded")
                    # Rejection records are audited but never become labels or advance current.
                    if event.get('response') is not None and event['response'].get('ok') is not False:
                        raise ValueError('Rejected action carries an accepted native response')
                    continue
                _scope(event, metadata)
                if event.get('source') != SOURCE or event.get('episode_id') != metadata['episode_id']:
                    raise ValueError('Accepted step lacks matching teacher collection provenance')
                if event.get('prompt_version') != metadata['prompt_version']:
                    raise ValueError('Step prompt version differs from metadata')
                if event.get('teacher_response') != response_event['content']:
                    raise ValueError('Training label differs from the actual Ollama response')
                _identity(event.get('teacher'), identity)
                if event.get('observation') != current['observation'] or event.get('info') != current['info']:
                    raise ValueError('Accepted label is not aligned with its pre-action public state')
                if event.get('student_prompt') != messages_for_state(metadata['game'], current):
                    raise ValueError('Student prompt differs from public inference input or leaks tool assistance')
                request_event, request_line = requests[rid]
                if event.get('teacher_prompt') != request_event['request'].get('messages'):
                    raise ValueError('Recorded teacher prompt differs from the actual model request')
                tool, tool_line = tools[step]
                if event.get('planner_recommendation') != tool['recommendation']:
                    raise ValueError('Planning recommendation differs between tool and accepted step')
                action = action_from(event['teacher_response'])
                if action != event.get('action'):
                    raise ValueError('Executed action differs from the actual teacher JSON action')
                proof = event.get('verification')
                if not isinstance(proof, dict) or proof.get('action_valid') is not True or proof.get('engine_sha256') != metadata['engine_sha256']:
                    raise ValueError('Missing matching native acceptance/engine proof')
                after = _native(event.get('response'), metadata['game'])
                advance = after['info']['ticks'] - current['info']['ticks']
                if not 1 <= advance <= action.get('ticks', 0):
                    raise ValueError('Native action did not advance the declared bounded simulation time')
                canonical = {'game': metadata['game'], 'level': metadata['level'], 'split': 'train',
                             'student_prompt': copy.deepcopy(event['student_prompt']),
                             'teacher_response': event['teacher_response'], 'teacher': identity.copy(),
                             'verification': copy.deepcopy(proof), 'source': SOURCE,
                             'prompt_version': metadata['prompt_version'], 'episode_id': metadata['episode_id']}
                validate_row(canonical)  # Trainer's exact canonical action/prompt contract.
                rows.append((canonical, {'step': step, 'step_line': line_number,
                                        'model_request_line': request_line, 'model_response_line': response_line,
                                        'tool_line': tool_line, 'response_id': rid,
                                        'model_request_sha256': request_event['request_sha256'],
                                        'teacher_response_sha256': hashlib.sha256(event['teacher_response'].encode()).hexdigest(),
                                        'native_response_sha256': _sha(after)}))
                if len(rows) > MAX_ROWS:
                    raise ValueError('Teacher dataset row limit exceeded')
                current = copy.deepcopy(after)
                accepted += 1
                continue
            if kind == 'summary':
                summary = event
                if event.get('status') != 'ok' or event.get('source') != SOURCE or event.get('runtime') != 'ollama' or event.get('role') != 'teacher':
                    raise ValueError('Teacher trace did not complete successfully as an Ollama collection')
                if any(type(event.get(field)) is not int for field in ('executed_actions', 'invalid_actions', 'decisions', 'tokens')):
                    raise ValueError('Teacher summary counters must be integers')
                if event.get('final') != current or event.get('executed_actions') != accepted or event.get('invalid_actions') != rejected:
                    raise ValueError('Teacher summary disagrees with recorded native actions')
                if event.get('decisions') != len(responses) or event.get('tokens') != tokens or len(consumed) != len(responses) or len(requests) != len(responses):
                    raise ValueError('Teacher summary/model-response accounting is incomplete')
                summary_line = line_number
                continue
            raise ValueError('Unknown or error event in teacher training trace: ' + str(kind))
        else:
            raise ValueError('Teacher trace event limit exceeded')
        final_stat = os.fstat(source.fileno())
    if total != initial.st_size or final_stat.st_size != initial.st_size or final_stat.st_mtime_ns != initial.st_mtime_ns:
        raise ValueError('Teacher trace changed while extracting')
    if metadata is None or summary is None or not rows:
        raise ValueError('A complete teacher summary and at least one accepted model action are required')
    success = current['info']['success']
    if success and (not current['terminated'] or current['truncated']):
        raise ValueError('Native success must be terminal and nontruncated')
    if success and metadata['game'] == 'angry-birds':
        if current['observation'].get('phase') != 'won' or current['observation'].get('pigs_left') != 0:
            raise ValueError('Native bird success disagrees with phase or remaining pigs')
    if success and metadata['game'] == 'getting-over-it':
        position = current['observation'].get('position')
        threshold = current['observation'].get('winning_body_height', 65.75)
        if (not isinstance(position, list) or len(position) != 2 or
                type(position[1]) not in (int, float) or type(threshold) not in (int, float) or
                not position[1] > threshold):
            raise ValueError('Native ascent success disagrees with the recorded summit height')
    progress_only = False
    if not success:
        if metadata['game'] != 'getting-over-it' or require_success:
            raise ValueError('Native success is required; failed bird episodes are never training labels')
        height = current['observation'].get('best_height')
        if type(height) not in (int, float) or not math.isfinite(height) or height < 1.0:
            raise ValueError('Explicit ascent progress extraction requires at least 1m best height')
        progress_only = True
    trace_digest = digest.hexdigest()
    for row, lineage in rows:
        lineage.update(trace_sha256=trace_digest, trace_file=path.name, summary_line=summary_line,
                       engine_sha256=metadata['engine_sha256'], collector_sha256=metadata['collector_sha256'],
                       planner_source_sha256=metadata['planner_source_sha256'])
        row['lineage'] = lineage
        row['verification'].update(episode_success=success, ascent_progress_only=progress_only,
                                   source_trace_sha256=trace_digest)
    source_manifest = {'file': path.name, 'bytes': total, 'sha256': trace_digest,
                       'game': metadata['game'], 'level': metadata['level'],
                       'episode_id': metadata['episode_id'], 'engine_sha256': metadata['engine_sha256'],
                       'teacher': identity, 'prompt_version': metadata['prompt_version'],
                       'rows': accepted, 'native_success': success, 'ascent_progress_only': progress_only,
                       'summary_line': summary_line}
    return [row for row, _ in rows], source_manifest


def _remove_ours(path, created):
    try:
        current = path.lstat()
        if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
            path.unlink()
    except FileNotFoundError:
        pass


def extract_teacher_rows(paths, output, require_success=True):
    """Validate full traces, then exclusively write canonical JSONL and its manifest.

    Default quality is native success for both games. require_success=False only
    permits explicit ascent progress traces (>=1m); bird losses remain forbidden.
    Invalid input aborts the whole extraction, not a silent skip. Model/engine
    evidence is a linked audit trail, not resistance to a malicious administrator.
    """
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_PATHS or type(require_success) is not bool:
        raise ValueError('Invalid teacher extraction input/quality budget')
    require_worker()  # Before reading real research data or creating output.
    target = Path(output)
    manifest_path = Path(str(output) + '.manifest.json')
    if target.exists() or target.is_symlink() or manifest_path.exists() or manifest_path.is_symlink():
        raise FileExistsError('Teacher dataset or manifest already exists')
    all_rows, sources, seen_traces, seen_episodes, total = [], [], set(), set(), 0
    engine = None
    for filename in paths:
        rows, source = _read_trace(filename, require_success, MAX_DATA_BYTES - total)
        total += source['bytes']
        if total > MAX_DATA_BYTES:
            raise ValueError('Teacher trace total byte budget exceeded')
        if source['sha256'] in seen_traces or source['episode_id'] in seen_episodes:
            raise ValueError('Duplicate teacher trace or episode would reweight training data')
        seen_traces.add(source['sha256']); seen_episodes.add(source['episode_id'])
        if engine is not None and source['engine_sha256'] != engine:
            raise ValueError('Different engine revisions cannot be mixed in one teacher dataset')
        engine = source['engine_sha256']
        all_rows.extend(rows)
        if len(all_rows) > MAX_ROWS:
            raise ValueError('Teacher dataset row budget exceeded')
        sources.append(source)
    encoded, row_lineage, size = [], [], 0
    for number, row in enumerate(all_rows, 1):
        line = json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
        size += len(line)
        if len(line) > MAX_RECORD_BYTES or size > MAX_OUTPUT_BYTES:
            raise ValueError('Canonical dataset record/output byte budget exceeded')
        encoded.append(line)
        row_lineage.append({'line': number, 'sha256': hashlib.sha256(line).hexdigest(),
                            'trace_sha256': row['lineage']['trace_sha256'],
                            'step_line': row['lineage']['step_line'], 'response_id': row['lineage']['response_id']})
    data = b''.join(encoded)
    manifest = {'format': 'tiny-rsi-teacher-dataset-v1', 'source': 'validated-ollama-teacher-traces',
                'dataset_file': target.name, 'dataset_sha256': hashlib.sha256(data).hexdigest(),
                'dataset_bytes': len(data), 'rows': len(all_rows), 'engine_sha256': engine,
                'prompt_version': PROMPT_VERSION, 'require_success': require_success,
                'sources': sources, 'row_lineage': row_lineage}
    manifest_data = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    created = []
    try:
        for filename, payload in ((target, data), (manifest_path, manifest_data)):
            descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append((filename, os.fstat(descriptor)))
            with os.fdopen(descriptor, 'wb') as destination:
                destination.write(payload); destination.flush(); os.fsync(destination.fileno())
    except BaseException:
        for filename, info in reversed(created):
            _remove_ours(filename, info)
        raise
    return dict(manifest, manifest_file=manifest_path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', action='append', required=True, help='Repeat for each complete actual-model trace')
    parser.add_argument('--output', required=True, help='New canonical JSONL; companion .manifest.json is exclusive')
    parser.add_argument('--allow-progress', action='store_true', help='Explicitly permit >=1m nonwinning ascent traces only')
    args = parser.parse_args()
    try:
        result = extract_teacher_rows(args.trace, args.output, require_success=not args.allow_progress)
    except Exception as exc:
        print(f'Teacher extraction error: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
