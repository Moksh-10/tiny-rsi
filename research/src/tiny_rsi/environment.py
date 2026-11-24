"""Bounded JSONL game interface and optional Gymnasium adapter.

C++ subprocesses within a vector share their guest kernel. This module does not
pretend that process isolation is VM isolation. Production experiments call
require_worker(); low-level wrappers remain usable by development unit tests.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import stat
import string
import subprocess
import threading
import time
from typing import Any, Sequence

MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 1 << 20


class EnvironmentError(RuntimeError):
    """A game subprocess failed, timed out, or violated the transport contract."""


class InvalidAction(ValueError):
    """A rejected request; the engine has not advanced the simulation."""


def require_worker() -> None:
    """Fail closed outside the provisioned, sealed, unprivileged Linux VM.

    Root-owned markers attest trusted provisioning, not resistance to a malicious
    administrator. The privileged launcher separately verifies the firewall.
    """
    if platform.system() != 'Linux' or os.geteuid() == 0:
        raise RuntimeError('Research execution requires an unprivileged Linux VM worker')
    for filename, expected in (
        ('/etc/game-research/worker', 'game-research-lima-v1\n'),
        ('/run/game-research/sealed', 'sealed-v1\n'),
    ):
        path = Path(filename)
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError('Worker marker must be a root-owned, protected regular file')
            if path.read_text() != expected:
                raise RuntimeError('Worker marker is invalid')
            parent = path.parent.stat()
            if parent.st_uid != 0 or parent.st_mode & 0o022:
                raise RuntimeError('Worker marker directory is not protected')
        except OSError as exc:
            raise RuntimeError('Provision and seal the Linux VM before research execution') from exc
    result = subprocess.run(
        ['/usr/bin/systemd-detect-virt', '--vm'], capture_output=True,
        timeout=3, check=False, text=True,
    )
    if result.returncode != 0 or result.stdout.strip() in ('', 'none'):
        raise RuntimeError('Hardware VM virtualization was not detected')
    for line in Path('/proc/mounts').read_text().splitlines():
        parts = line.split()
        if len(parts) > 2 and (parts[2] in ('virtiofs', '9p') or 'sshfs' in parts[2]):
            raise RuntimeError('Host-sharing filesystem detected')


# Training/evaluation callers can use either name without duplicating the guard.
require_guest = require_worker


class GameEnvironment:
    """One persistent C++ simulator with explicit reset and bounded I/O.

    Executable is trusted operator input and never comes from a model response.
    Calls on the same instance serialize; use VectorEnvironment for concurrency.
    """
    def __init__(self, executable: str | Path, game: str, level: int = 0,
                 *, timeout: float = 10.0, command: Sequence[str] | None = None):
        if game not in ('angry-birds', 'getting-over-it'):
            raise ValueError('Unsupported game')
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level < (12 if game == 'angry-birds' else 1):
            raise ValueError('Invalid level')
        if not 0 < timeout <= 300:
            raise ValueError('Transport timeout must be in (0,300] seconds')
        self.executable = str(executable)
        self.game, self.level, self.timeout = game, level, timeout
        self.state: dict[str, Any] | None = None
        self._lock = threading.RLock()
        self._buffer = bytearray()
        self._closed = False
        # command is used by transport unit tests, never exposed to model tools.
        self.process = subprocess.Popen(
            list(command) if command is not None else [self.executable],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True, bufsize=0,
        )
        assert self.process.stdin is not None and self.process.stdout is not None
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def _abort(self) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self._closed = True
        self.process.stdin.close()
        self.process.stdout.close()

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(request, separators=(',', ':'), allow_nan=False).encode() + b'\n'
        if len(payload) - 1 > MAX_REQUEST_BYTES:
            raise ValueError('Request exceeds engine byte limit')
        with self._lock:
            if self._closed:
                raise EnvironmentError('Environment is closed')
            deadline = time.monotonic() + self.timeout
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdin, selectors.EVENT_WRITE)
                    written = 0
                    while written < len(payload):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise EnvironmentError('Environment write timed out')
                        try:
                            written += os.write(self.process.stdin.fileno(), payload[written:])
                        except BlockingIOError:
                            continue
                    selector.unregister(self.process.stdin)
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    while b'\n' not in self._buffer:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise EnvironmentError('Environment response timed out')
                        try:
                            chunk = os.read(self.process.stdout.fileno(), 8192)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            raise EnvironmentError('Environment exited before responding')
                        self._buffer.extend(chunk)
                        if len(self._buffer) > MAX_RESPONSE_BYTES:
                            raise EnvironmentError('Environment response exceeds byte limit')
                line, _, tail = self._buffer.partition(b'\n')
                self._buffer = bytearray(tail)
                def reject_constant(value):
                    raise ValueError(f'Nonfinite JSON value: {value}')
                response = json.loads(line, parse_constant=reject_constant)
                if not isinstance(response, dict) or not isinstance(response.get('ok'), bool):
                    raise EnvironmentError('Malformed engine response')
                if response['ok'] and response.get('protocol') != 1:
                    raise EnvironmentError('Unsupported engine protocol version')
                return response
            except TimeoutError:
                # Preserve an enclosing evaluator deadline instead of relabeling
                # it as a protocol failure (TimeoutError is also an OSError).
                self._abort()
                raise
            except (OSError, ValueError, RecursionError, EnvironmentError) as exc:
                self._abort()
                if isinstance(exc, EnvironmentError):
                    raise
                raise EnvironmentError('Environment transport failure') from exc

    @staticmethod
    def _accepted(response: dict[str, Any]) -> dict[str, Any]:
        if not response['ok']:
            raise InvalidAction(response.get('error', 'Engine rejected request'))
        return response

    def reset(self, *, seed: int | None = None,
              options: dict[str, Any] | None = None) -> tuple[dict, dict]:
        if seed is not None and (type(seed) is not int or seed != 0):
            raise ValueError('Current games have fixed layouts; only seed=None or 0 is supported')
        options = {} if options is None else options
        if not isinstance(options, dict) or set(options) - {'level'}:
            raise ValueError('Reset options support only level')
        level = options.get('level', self.level)
        with self._lock:
            response = self._accepted(self.request({'op': 'reset', 'game': self.game, 'level': level}))
            self.level = level
            self.state = response
            info = dict(response['info'], game=self.game, level=self.level, seed=None,
                        layout_randomized=False)
            return copy.deepcopy(response['observation']), info

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.state is None:
                raise RuntimeError('Reset required before acting')
            try:
                response = self._accepted(self.request({'op': 'act', 'action': action}))
            except ValueError as exc:
                raise InvalidAction(str(exc)) from exc
            self.state = response
            return copy.deepcopy(response)

    def step(self, action: dict[str, Any]) -> tuple[dict, float, bool, bool, dict]:
        response = self.act(action)
        info = dict(response['info'], game=self.game, level=self.level)
        return (response['observation'], response['reward'], response['terminated'],
                response['truncated'], info)

    def observe(self) -> dict[str, Any]:
        return copy.deepcopy(self._accepted(self.request({'op': 'observe'})))

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._abort()

    def __enter__(self) -> 'GameEnvironment':
        return self

    def __exit__(self, *args) -> None:
        self.close()


class VectorEnvironment:
    """Bounded concurrent simulators within a single guest, no auto-reset.

    This is process-level simulation parallelism, not independent VM isolation.
    All worker calls complete before returning; an error closes the whole batch.
    """
    def __init__(self, executable: str | Path, games: Sequence[tuple[str, int]],
                 *, max_workers: int = 4, timeout: float = 10.0):
        if not games or len(games) > 16 or not 1 <= max_workers <= 4:
            raise ValueError('Vector size 1..16 and worker concurrency 1..4 required')
        self.envs: list[GameEnvironment] = []
        self._closed = False
        self._lock = threading.Lock()
        try:
            for game, level in games:
                self.envs.append(GameEnvironment(executable, game, level, timeout=timeout))
        except Exception:
            for env in self.envs:
                env.close()
            raise
        self._pool = ThreadPoolExecutor(max_workers=min(max_workers, len(games)))

    def _map(self, function, values):
        if self._closed:
            raise EnvironmentError('Vector environment is closed')
        futures = [self._pool.submit(function, env, value) for env, value in zip(self.envs, values)]
        try:
            return [future.result() for future in futures]
        except Exception:
            self.close()
            raise

    def reset(self):
        with self._lock:
            return self._map(lambda env, _: env.reset(), [None] * len(self.envs))

    def step(self, actions: Sequence[dict]):
        if len(actions) != len(self.envs):
            raise ValueError('One action per environment required')
        with self._lock:
            return self._map(lambda env, action: env.step(action), actions)

    def close(self):
        if not self._closed:
            self._closed = True
            for env in self.envs:
                env.close()
            self._pool.shutdown(wait=True, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def make_gymnasium(executable: str | Path, game: str, actions: Sequence[dict],
                    *, level: int = 0):
    """Optional real Gymnasium Env with lossless JSON text and a finite catalog.

    JSON Text avoids silently truncating ragged entity/terrain observations.
    Tensor policies can install an ObservationWrapper for their feature encoder.
    Gym seeds initialize its RNG only; they do not change the fixed game layout.
    Invalid catalog actions yield unchanged state, zero reward and an info error;
    action masks or an external invalid-action budget prevent endless retries.
    """
    import gymnasium as gym
    from gymnasium import spaces
    if not actions:
        raise ValueError('Nonempty finite action catalog required')
    catalog = copy.deepcopy(list(actions))

    class JSONGameEnv(gym.Env):
        metadata = {'render_modes': []}

        def __init__(self):
            self.engine = GameEnvironment(executable, game, level)
            self.action_space = spaces.Discrete(len(catalog))
            self.observation_space = spaces.Text(
                max_length=MAX_RESPONSE_BYTES, min_length=2, charset=string.printable)

        def reset(self, *, seed=None, options=None):
            # Gym's RNG supports normal seeding; the deterministic engine has no
            # stochastic reset and explicitly reports layout_randomized=False.
            super().reset(seed=seed)
            obs, info = self.engine.reset(seed=0, options=options)
            return json.dumps(obs, separators=(',', ':'), ensure_ascii=True), info

        def step(self, action):
            if not self.action_space.contains(action):
                raise ValueError('Action index outside catalog')
            try:
                obs, reward, term, trunc, info = self.engine.step(catalog[int(action)])
            except InvalidAction as exc:
                if self.engine.state is None:
                    raise RuntimeError('Reset required before stepping') from exc
                state = self.engine.state
                obs, reward, term, trunc = state['observation'], 0.0, state['terminated'], state['truncated']
                info = dict(state['info'], invalid_action=True, error=str(exc))
            return json.dumps(obs, separators=(',', ':'), ensure_ascii=True), reward, term, trunc, info

        def close(self):
            self.engine.close()

    return JSONGameEnv()
