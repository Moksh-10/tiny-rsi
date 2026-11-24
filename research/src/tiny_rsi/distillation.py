"""Bounded CPU LoRA response distillation for an actual Qwen2.5-0.5B Ollama student.

Heavy dependencies are imported only inside train(). This module never downloads,
executes dataset text, loads pickle weights, launches a model on macOS, or judges
its own gameplay. Standalone merged Safetensors output is for a separately trusted
GGUF conversion/quantization/import pipeline; Ollama 0.40.16 rejects ADAPTER.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

FORMAT = 'tiny-rsi-ollama-distillation-v1'
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_ROWS = 4096
MAX_DATA_BYTES = 64 * 1024 * 1024
QWEN_CONFIG = {'model_type': 'qwen2', 'hidden_size': 896, 'intermediate_size': 4864,
               'num_hidden_layers': 24, 'num_attention_heads': 14,
               'num_key_value_heads': 2, 'vocab_size': 151936,
               'tie_word_embeddings': True}
PROPOSED_DEPENDENCIES = {'torch': '2.11.0+cpu', 'transformers': '5.24.0',
                         'peft': '0.22.0', 'accelerate': '1.16.0', 'safetensors': '0.8.0'}


class DistillationDeadline(TimeoutError):
    pass


class TrainingDeadline(TimeoutError):
    pass


def strict_json(text):
    def reject(value):
        raise ValueError(f'Nonfinite JSON constant forbidden: {value}')
    return json.loads(text, parse_constant=reject)


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x') as output:
        json.dump(value, output, sort_keys=True, indent=2, allow_nan=False)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


@contextmanager
def deadline(seconds, exception_type=DistillationDeadline):
    """Preserve an earlier deadline; nested work cannot renew the outer timer."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Run distillation in a dedicated main-thread process')
    if not math.isfinite(seconds) or seconds <= 0:
        raise exception_type('Distillation time budget exhausted')
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    use_old = bool(old_timer[0] and old_timer[0] <= seconds)
    def expired(signum, frame):
        if use_old and callable(old_handler):
            old_handler(signum, frame)
        raise exception_type('Distillation time budget exhausted')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, old_timer[0]) if old_timer[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,
                             max(0.000001, old_timer[0] - (time.monotonic() - started)), old_timer[1])


def require_worker():
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise RuntimeError('Training requires an unprivileged sealed Linux VM')
    for name, expected in (('/etc/game-research/worker', 'game-research-lima-v1\n'),
                           ('/run/game-research/sealed', 'sealed-v1\n')):
        path = Path(name)
        st = path.stat()
        if path.read_text() != expected or st.st_uid != 0 or st.st_mode & 0o022:
            raise RuntimeError('Missing root-owned worker seal')
    result = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True,
                            text=True, check=False, timeout=5)
    if result.returncode or result.stdout.strip() in ('', 'none'):
        raise RuntimeError('A virtual machine is required')
    for line in Path('/proc/mounts').read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and (fields[2] in ('virtiofs', '9p') or 'sshfs' in fields[2]):
            raise RuntimeError('Host-sharing filesystem detected')


def require_ollama_unloaded():
    """The model daemon may stay up, but its weights must not compete with training."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise RuntimeError('Inference redirects forbidden')
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with client.open('http://127.0.0.1:11434/api/ps', timeout=2) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise RuntimeError('Unexpected Ollama process response size')
        state = strict_json(raw)
        if not isinstance(state, dict) or not isinstance(state.get('models'), list):
            raise RuntimeError('Invalid Ollama process response')
        if state['models']:
            raise RuntimeError('Unload all Ollama models before CPU training')
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ConnectionRefusedError):
            raise RuntimeError('Cannot confirm Ollama is unloaded') from exc


def motor_action(game, text):
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise ValueError('A bounded teacher JSON action response is required')
    action = strict_json(text)
    if not isinstance(action, dict):
        raise ValueError('Teacher response must be an action object')
    kind, ticks = action.get('type'), action.get('ticks')
    if type(ticks) is not int or not 1 <= ticks <= 120:
        raise ValueError('Teacher ticks must be an integer in [1,120]')
    allowed = {'type', 'ticks'}
    if game == 'angry-birds' and kind in ('wait', 'ability'):
        pass
    elif (game == 'angry-birds' and kind == 'launch') or (game == 'getting-over-it' and kind == 'hammer'):
        allowed |= {'x', 'y'}
        limit = 95 if game == 'angry-birds' else 3.15
        for key in ('x', 'y'):
            number = action.get(key)
            if type(number) not in (int, float) or not math.isfinite(number) or not -limit <= number <= limit:
                raise ValueError('Teacher action contains an invalid aim')
        if game == 'angry-birds' and not 8 <= math.hypot(action['x'], action['y']) <= 95.001:
            raise ValueError('Teacher launch pull is invalid')
        if game == 'getting-over-it':
            allowed.add('hold')
            if type(action.get('hold')) is not bool:
                raise ValueError('Teacher hold must be boolean')
    else:
        raise ValueError('Teacher action does not belong to this game')
    if action.keys() != allowed:
        raise ValueError('Teacher action contains unknown or missing fields')
    return json.dumps(action, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate_row(row):
    if not isinstance(row, dict):
        raise ValueError('Teacher dataset record must be an object')
    game, level = row.get('game'), row.get('level')
    if game not in ('angry-birds', 'getting-over-it') or type(level) is not int:
        raise ValueError('Explicit game and integer level required')
    if row.get('split') != 'train' or (game == 'angry-birds' and not 0 <= level <= 5) or (game == 'getting-over-it' and level != 0):
        raise ValueError('Validation/heldout labels cannot enter student training')
    teacher = row.get('teacher')
    if not isinstance(teacher, dict) or teacher.get('runtime') != 'ollama' or teacher.get('role') != 'teacher':
        raise ValueError('Actual Ollama teacher provenance required; planner-only labels are forbidden')
    model, digest = teacher.get('model'), teacher.get('digest')
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or not isinstance(digest, str) or not re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', digest):
        raise ValueError('Teacher model name and full model digest required')
    proof = row.get('verification')
    if not isinstance(proof, dict) or proof.get('action_valid') is not True:
        raise ValueError('Teacher action must have been accepted by the game engine')
    prompt = row.get('student_prompt')
    if isinstance(prompt, str):
        messages = []
        system = row.get('student_system')
        if system is not None:
            if not isinstance(system, str) or not system.strip() or len(system) > 8192:
                raise ValueError('Invalid student system prompt')
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
    elif isinstance(prompt, list) and 1 <= len(prompt) <= 8:
        messages = prompt
    else:
        raise ValueError('student_prompt must be text or a bounded system/user message list')
    for i, message in enumerate(messages):
        if not isinstance(message, dict) or message.keys() != {'role', 'content'} or message['role'] not in ('system', 'user') or (message['role'] == 'system' and i != 0):
            raise ValueError('Only system/user prompt messages are allowed')
        if not isinstance(message['content'], str) or not message['content'].strip() or len(message['content']) > 8192:
            raise ValueError('Prompt message is blank or oversized')
    if messages[-1]['role'] != 'user' or sum(len(m['content']) for m in messages) > 16384:
        raise ValueError('Prompt must end in a bounded user observation')
    target = motor_action(game, row.get('teacher_response'))
    return {'game': game, 'level': level, 'messages': [dict(m) for m in messages], 'target': target,
            'teacher': {'runtime': 'ollama', 'role': 'teacher', 'model': model, 'digest': digest.removeprefix('sha256:')}}


def load_rows(paths, max_rows=MAX_ROWS):
    if not 1 <= len(paths) <= 64 or type(max_rows) is not int or not 1 <= max_rows <= MAX_ROWS:
        raise ValueError('Dataset budget exceeded')
    rows, sources, total = [], [], 0
    for filename in paths:
        path = Path(filename)
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_DATA_BYTES:
            raise ValueError('Dataset file/total byte budget exceeded')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            while line := source.readline(MAX_RECORD_BYTES + 1):
                if len(line) > MAX_RECORD_BYTES or not line.strip():
                    raise ValueError('Blank or oversized teacher dataset record')
                digest.update(line)
                rows.append(validate_row(strict_json(line)))
                if len(rows) > max_rows:
                    raise ValueError('Teacher dataset row budget exceeded')
        sources.append({'file': path.name, 'bytes': size, 'sha256': digest.hexdigest()})
    if not rows:
        raise ValueError('Teacher dataset is empty')
    return rows, sources


def tokenize_rows(tokenizer, rows, sequence_length=256):
    """Mask the exact original chat prompt; never truncate target action tokens."""
    encoded = []
    for index, row in enumerate(rows):
        prefix = tokenizer.apply_chat_template(row['messages'], tokenize=True, add_generation_prompt=True)
        complete = tokenizer.apply_chat_template(row['messages'] + [{'role': 'assistant', 'content': row['target']}],
                                                 tokenize=True, add_generation_prompt=False)
        if hasattr(prefix, 'tolist'):
            prefix = prefix.tolist()
        if hasattr(complete, 'tolist'):
            complete = complete.tolist()
        if not isinstance(prefix, list) or not isinstance(complete, list) or any(type(x) is not int or x < 0 for x in complete + prefix):
            raise ValueError('Tokenizer returned invalid token IDs')
        if complete[:len(prefix)] != prefix or len(complete) <= len(prefix):
            raise ValueError('Chat template does not have a matching assistant prefix')
        if len(complete) > sequence_length:
            raise ValueError(f'Teacher record {index} needs {len(complete)} tokens, exceeds {sequence_length}; do not silently truncate')
        encoded.append({'input_ids': complete, 'labels': [-100] * len(prefix) + complete[len(prefix):],
                        'prompt_tokens': len(prefix), 'target_tokens': len(complete) - len(prefix)})
    return encoded


def validate_base(base):
    base = Path(base).resolve(strict=True)
    if not base.is_dir():
        raise ValueError('Base must be a local Safetensors model directory')
    config_path = base / 'config.json'
    if not config_path.is_file() or config_path.stat().st_size > 1024 * 1024:
        raise ValueError('Missing/bounded base config required')
    config = strict_json(config_path.read_text())
    if not isinstance(config, dict) or any(config.get(k) != v for k, v in QWEN_CONFIG.items()):
        raise ValueError('Only the resource-bounded Qwen2.5-0.5B architecture is allowed')
    if config.get('architectures') != ['Qwen2ForCausalLM'] or config.get('quantization_config') or config.get('auto_map'):
        raise ValueError('Quantized or remote-code model configurations are forbidden')
    forbidden = ('.bin', '.pt', '.pth', '.pkl', '.pickle')
    if any(path.suffix.lower() in forbidden for path in base.iterdir() if path.is_file()):
        raise ValueError('Pickle-style model files are forbidden')
    if not (base / 'tokenizer.json').is_file() or not (base / 'tokenizer_config.json').is_file():
        raise ValueError('Local tokenizer files required')
    weights = sorted(base.glob('*.safetensors'))
    if not weights or len(weights) > 8 or sum(path.stat().st_size for path in weights) > 1300 * 1024 * 1024:
        raise ValueError('Missing or oversized 0.5B Safetensors weights')
    index = base / 'model.safetensors.index.json'
    if index.exists():
        mapping = strict_json(index.read_text()).get('weight_map', {})
        names = {path.name for path in weights}
        if not mapping or any(not isinstance(name, str) or name not in names for name in mapping.values()):
            raise ValueError('Invalid Safetensors shard index')
    return base, config, weights


def artifact_manifest(directory):
    result = []
    for path in sorted(Path(directory).rglob('*')):
        if path.is_file():
            result.append({'file': str(path.relative_to(directory)), 'bytes': path.stat().st_size,
                           'sha256': sha256_file(path)})
    return result


def _adapter_digest(named_parameters):
    digest = hashlib.sha256()
    for name, parameter in named_parameters:
        digest.update(name.encode())
        digest.update(parameter.detach().to('cpu').contiguous().numpy().tobytes())
    return digest.hexdigest()


def _dependency_versions():
    return {name: importlib.metadata.version(name) for name in PROPOSED_DEPENDENCIES}


def train(base, data, output, *, steps=2, max_seconds=180, sequence_length=256,
          rank=4, learning_rate=0.0002, seed=0, gradient_accumulation=1,
          max_rows=MAX_ROWS, min_free_gib=4, gradient_checkpointing=False):
    """Train a real LM adapter and emit a standalone merged F16 model, never a game score."""
    require_worker()
    if type(steps) is not int or not 2 <= steps <= 20:
        raise ValueError('steps must be an integer in [2,20]')
    if type(max_seconds) is not int or not 60 <= max_seconds <= 3600:
        raise ValueError('max_seconds must be an integer in [60,3600]')
    if type(sequence_length) is not int or not 64 <= sequence_length <= 256:
        raise ValueError('sequence_length must be an integer in [64,256]')
    if type(rank) is not int or rank not in (4, 8) or type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError('Invalid rank/seed')
    if type(gradient_accumulation) is not int or not 1 <= gradient_accumulation <= 4:
        raise ValueError('gradient_accumulation must be in [1,4]')
    if type(learning_rate) not in (int, float) or not math.isfinite(learning_rate) or not 1e-6 <= learning_rate <= 1e-3:
        raise ValueError('Invalid learning rate')
    if type(min_free_gib) is not int or not 1 <= min_free_gib <= 16 or type(gradient_checkpointing) is not bool:
        raise ValueError('Invalid storage/checkpointing budget')
    require_ollama_unloaded()
    base, config, weights = validate_base(base)
    rows, sources = load_rows(data, max_rows)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    # Guest free space cannot prove physical host free space for a sparse VM disk;
    # the host launcher must independently enforce its host reserve.
    disk = shutil.disk_usage(out)
    if disk.free < (min_free_gib + 1.2) * 1024**3:
        raise RuntimeError('Insufficient guest storage for merged model plus reserve')
    started = time.monotonic()
    report = {'format': FORMAT, 'status': 'initializing', 'completed': False,
              'scope': 'Actual 0.5B LM response distillation; gameplay evaluation is external',
              'base': {'directory': str(base), 'config_sha256': sha256_file(base / 'config.json'),
                       'weights': [{'file': path.name, 'bytes': path.stat().st_size} for path in weights]},
              'datasets': sources, 'rows': len(rows),
              'teacher_models': [strict_json(s) for s in sorted({json.dumps(row['teacher'], sort_keys=True) for row in rows})],
              'config': {'steps': steps, 'max_seconds': max_seconds, 'sequence_length': sequence_length,
                         'rank': rank, 'learning_rate': learning_rate, 'seed': seed,
                         'batch_size': 1, 'gradient_accumulation': gradient_accumulation,
                         'target_modules': ['q_proj', 'v_proj'], 'dtype': 'float32',
                         'gradient_checkpointing': gradient_checkpointing},
              'provenance_caveat': 'Teacher identity and accepted-action flags are trusted harness records, not cryptographic attestations.',
              'steps': [], 'optimization_steps_completed': 0,
              'guest_free_bytes_before': disk.free}
    write_json(out / 'progress.json', report)
    try:
        with deadline(max_seconds - (time.monotonic() - started)):
            for path, record in zip(weights, report['base']['weights']):
                record['sha256'] = sha256_file(path)
            os.environ['HF_HUB_OFFLINE'] = '1'
            os.environ['TRANSFORMERS_OFFLINE'] = '1'
            os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
            os.environ['TOKENIZERS_PARALLELISM'] = 'false'
            os.environ['CUDA_VISIBLE_DEVICES'] = ''
            # Deliberately lazy: mock/validation tests do not import these packages.
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            from peft import LoraConfig, TaskType, get_peft_model
            report['dependencies'] = _dependency_versions()
            torch.set_num_threads(min(2, os.cpu_count() or 1))
            torch.set_num_interop_threads(1)
            torch.manual_seed(seed)
            torch.use_deterministic_algorithms(True)
            randomizer = random.Random(seed)
            tokenizer = AutoTokenizer.from_pretrained(str(base), local_files_only=True, trust_remote_code=False)
            examples = tokenize_rows(tokenizer, rows, sequence_length)
            report['tokens'] = {'prompt': sum(e['prompt_tokens'] for e in examples),
                                'target': sum(e['target_tokens'] for e in examples),
                                'max_sequence': max(len(e['input_ids']) for e in examples)}
            model = AutoModelForCausalLM.from_pretrained(str(base), local_files_only=True,
                    trust_remote_code=False, use_safetensors=True, dtype=torch.float32,
                    attn_implementation='sdpa', low_cpu_mem_usage=True)
            model.to('cpu')
            model.config.use_cache = False
            for parameter in model.parameters():
                parameter.requires_grad_(False)
            lora = LoraConfig(task_type=TaskType.CAUSAL_LM, r=rank, lora_alpha=2 * rank,
                              lora_dropout=0.0, target_modules=['q_proj', 'v_proj'], bias='none')
            model = get_peft_model(model, lora)
            named = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
            count = sum(p.numel() for _, p in named)
            if count != 67584 * rank or any('lora_A' not in name and 'lora_B' not in name for name, _ in named):
                raise RuntimeError('Unexpected trainable parameters; refusing a larger training job')
            if sum(p.numel() for p in model.parameters()) > 600_000_000:
                raise RuntimeError('Base model exceeds resource bound')
            report['trainable_parameters'] = count
            report['trainable_sha256_before'] = _adapter_digest(named)
            initial = {name: p.detach().clone() for name, p in named}
            last_committed = ({name: p.detach().clone() for name, p in named}, 0, [])
            model.save_pretrained(out / 'initial-adapter', safe_serialization=True, save_embedding_layers=False)
            if gradient_checkpointing:
                model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
                model.enable_input_require_grads()
            optimizer = torch.optim.AdamW([p for _, p in named], lr=learning_rate,
                                           betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0)
            model.train()
            order = list(range(len(examples)))
            randomizer.shuffle(order)
            cursor = 0
            export_reserve = min(30, max_seconds / 4)
            training_stop = started + max_seconds - export_reserve
            stopped_for_budget = False
            try:
                with deadline(max(0.000001, training_stop - time.monotonic()), TrainingDeadline):
                    for step in range(steps):
                        step_started = time.monotonic()
                        optimizer.zero_grad(set_to_none=True)
                        losses, target_tokens = [], 0
                        for _ in range(gradient_accumulation):
                            if cursor == len(order):
                                cursor = 0
                                randomizer.shuffle(order)
                            example = examples[order[cursor]]
                            cursor += 1
                            ids = torch.tensor([example['input_ids']], dtype=torch.long, device='cpu')
                            labels = torch.tensor([example['labels']], dtype=torch.long, device='cpu')
                            result = model(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels, use_cache=False)
                            loss = result.loss
                            value = float(loss.detach())
                            if not math.isfinite(value):
                                raise RuntimeError('Nonfinite training loss')
                            (loss / gradient_accumulation).backward()
                            losses.append(value)
                            target_tokens += example['target_tokens']
                            del result, loss, ids, labels
                        norm = float(torch.nn.utils.clip_grad_norm_([p for _, p in named], 1.0, error_if_nonfinite=True))
                        optimizer.step()
                        # A deadline during an optimizer update must never export partially updated weights.
                        record = {'step': step + 1, 'mean_loss': sum(losses) / len(losses),
                                  'target_tokens': target_tokens, 'gradient_norm': norm,
                                  'seconds': time.monotonic() - step_started}
                        # One Python assignment commits weights and their matching metrics together.
                        last_committed = ({name: p.detach().clone() for name, p in named},
                                          step + 1, report['steps'] + [record])
                        report['optimization_steps_completed'] = last_committed[1]
                        report['steps'] = list(last_committed[2])
                        report['status'] = 'training'
                        report['elapsed_seconds'] = time.monotonic() - started
                        write_json(out / 'progress.json', report)
            except TrainingDeadline:
                stopped_for_budget = True
                with torch.no_grad():
                    for name, parameter in named:
                        parameter.copy_(last_committed[0][name])
                report['optimization_steps_completed'] = last_committed[1]
                report['steps'] = list(last_committed[2])
                optimizer.zero_grad(set_to_none=True)
            if report['optimization_steps_completed'] == 0:
                raise RuntimeError('No optimization step completed inside budget')
            report['trainable_sha256_after'] = _adapter_digest(named)
            report['trainable_weights_changed'] = report['trainable_sha256_before'] != report['trainable_sha256_after']
            report['adapter_delta_l2'] = math.sqrt(sum(float(((p.detach() - initial[name])**2).sum()) for name, p in named))
            if not report['trainable_weights_changed'] or not math.isfinite(report['adapter_delta_l2']):
                raise RuntimeError('No finite student-weight change was observed')
            model.eval()
            if gradient_checkpointing:
                model.gradient_checkpointing_disable()
            model.save_pretrained(out / 'adapter', safe_serialization=True, save_embedding_layers=False)
            del optimizer, initial, last_committed
            merged = model.merge_and_unload(safe_merge=True)
            merged.to(dtype=torch.float16)
            merged.config.use_cache = True
            if any(not bool(torch.isfinite(parameter).all()) for parameter in merged.parameters()):
                raise RuntimeError('Merged F16 model contains nonfinite weights')
            merged.save_pretrained(out / 'merged-hf-f16', safe_serialization=True, max_shard_size='1GB')
            tokenizer.save_pretrained(out / 'merged-hf-f16')
            report['artifacts'] = {name: artifact_manifest(out / name)
                                   for name in ('initial-adapter', 'adapter', 'merged-hf-f16')}
            if not any(item['file'].endswith('.safetensors') for item in report['artifacts']['merged-hf-f16']):
                raise RuntimeError('Standalone Safetensors export missing')
            report['status'] = 'completed_at_training_time_limit' if stopped_for_budget else 'completed'
            report['completed'] = True
            report['merged_model_directory'] = str(out / 'merged-hf-f16')
            report['adapter_directory'] = str(out / 'adapter')
    except BaseException as exc:
        report['status'] = 'failed'
        report['completed'] = False
        report['error'] = f'{type(exc).__name__}: {exc}'[:1024]
        raise
    finally:
        report['elapsed_seconds'] = time.monotonic() - started
        # Linux ru_maxrss is KiB. This process is deliberately guest-only.
        report['peak_process_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['guest_free_bytes_after'] = shutil.disk_usage(out).free
        report['claim'] = 'Weights were updated and exported' if report['completed'] else 'Incomplete training; do not import/promote artifacts'
        report['limitations'] = ['No gameplay improvement is asserted by this trainer.',
                                 'Response distillation uses model outputs, not full teacher-logit KL.',
                                 'Matched Ollama base/trained gameplay evaluation is required separately.']
        write_json(out / 'metrics.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='Offline local Qwen2.5-0.5B-Instruct Safetensors directory')
    parser.add_argument('--data', nargs='+', required=True)
    parser.add_argument('--output', required=True, help='New output directory')
    parser.add_argument('--steps', type=int, default=2)
    parser.add_argument('--max-seconds', type=int, default=180)
    parser.add_argument('--sequence-length', type=int, default=256)
    parser.add_argument('--rank', type=int, choices=(4, 8), default=4)
    parser.add_argument('--learning-rate', type=float, default=0.0002)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--gradient-accumulation', type=int, default=1)
    parser.add_argument('--max-rows', type=int, default=MAX_ROWS)
    parser.add_argument('--min-free-gib', type=int, default=4)
    parser.add_argument('--gradient-checkpointing', action='store_true')
    args = vars(parser.parse_args())
    result = train(**args)
    print(json.dumps({'status': result['status'], 'optimization_steps_completed': result['optimization_steps_completed'],
                      'trainable_parameters': result['trainable_parameters'], 'adapter_delta_l2': result['adapter_delta_l2'],
                      'peak_process_rss_kib': result['peak_process_rss_kib'], 'elapsed_seconds': result['elapsed_seconds'],
                      'merged_model_directory': result['merged_model_directory']}, allow_nan=False))


if __name__ == '__main__':
    main()
