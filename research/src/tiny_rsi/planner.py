"""Budgeted simulator-query teachers; no state injection or OS tools.

A teacher has a separate oracle using the same public reset/act API. Every
hypothetical rollout resets and replays the actual action prefix. This is an
explicit privileged-*compute* planning track, not a zero-query policy: record
``stats`` alongside any comparison to a distilled student.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
from pathlib import Path
from typing import Any

try:
    from .environment import GameEnvironment, require_worker
except ImportError:
    from environment import GameEnvironment, require_worker

Action = dict[str, Any]
PULL_X = (-95, -85, -75, -65, -55, -45)
PULL_Y = (-15, -5, 0, 5, 15, 25, 35, 45, 55)


def action_vocabulary(game: str) -> list[Action]:
    """Finite control vocabulary, shared by planning and student labels."""
    if game == "angry-birds":
        launches = [dict(type="launch", x=x, y=y, ticks=30)
                    for x in PULL_X for y in PULL_Y if 8 <= math.hypot(x, y) <= 95]
        return launches + [dict(type="wait", ticks=t) for t in (30, 60, 90, 120)] + [
            dict(type="ability", ticks=30)]
    if game == "getting-over-it":
        # Rounded vectors retain a fixed vocabulary while the native engine
        # performs its own reach clamp. A stationary control is deliberately absent.
        return [dict(type="hammer", x=round(3.1 * math.cos(i * math.tau / 16), 5),
                     y=round(3.1 * math.sin(i * math.tau / 16), 5), hold=hold, ticks=ticks)
                for i in range(16) for hold in (True, False) for ticks in (15, 30)]
    raise ValueError(f"unsupported game: {game}")


def _terminal(state: dict) -> bool:
    return bool(state.get("terminated") or state.get("truncated"))


class OracleBudgetExhausted(RuntimeError):
    pass


class PlanningPolicy:
    """Callable public-observation policy with a bounded reset/replay oracle.

    Create/reset one policy per episode. ``candidate_budget`` limits attempted
    candidate sequences, while ``tick_budget`` includes prefix replay and is a
    hard cap on requested physics ticks. Truncated budget trials are discarded.
    ``close`` must be called to terminate the oracle subprocess.
    """
    def __init__(self, executable: str, game: str, level: int = 0, seed: int = 0,
                 candidate_budget: int = 1200, tick_budget: int = 2_000_000,
                 samples: int = 24, horizon: int = 3):
        if candidate_budget < 1 or tick_budget < 120 or not 1 <= samples <= 256 or not 1 <= horizon <= 8:
            raise ValueError("invalid teacher planning budget")
        require_worker()
        self.game, self.level = game, level
        self.oracle = GameEnvironment(executable, game, level=level)
        self.random = random.Random(seed)
        self.candidate_budget, self.tick_budget = candidate_budget, tick_budget
        self.samples, self.horizon = samples, horizon
        self.vocabulary = action_vocabulary(game)
        self.reset()

    def reset(self):
        self.history: list[Action] = []
        self.queue: list[Action] = []
        self.warm: list[Action] = []
        self._last_label: Action | None = None
        self._expected_observation: dict | None = None
        self._expected_tick: int | None = None
        self.stats = dict(candidate_rollouts=0, oracle_actions=0, oracle_ticks=0,
                          oracle_resets=0, oracle_reset_ticks=0, budget_exhausted=False)

    def close(self):
        self.oracle.close()

    def _act(self, action: Action) -> dict:
        ticks = action["ticks"]
        if self.stats["oracle_ticks"] + ticks > self.tick_budget:
            raise OracleBudgetExhausted
        state = self.oracle.act(action)
        self.stats["oracle_actions"] += 1
        # Requested ticks are an upper bound when a game terminates mid-action.
        self.stats["oracle_ticks"] += ticks
        if not state.get("ok", True):
            raise RuntimeError(f"teacher generated invalid oracle action: {state}")
        return state

    def _trial(self, suffix: list[Action]) -> dict:
        if self.stats["candidate_rollouts"] >= self.candidate_budget:
            raise OracleBudgetExhausted
        reset_ticks = 60 if self.game == "angry-birds" else 0
        if self.stats["oracle_ticks"] + reset_ticks > self.tick_budget:
            raise OracleBudgetExhausted
        self.stats["candidate_rollouts"] += 1
        self.stats["oracle_ticks"] += reset_ticks
        self.stats["oracle_reset_ticks"] += reset_ticks
        self.oracle.reset()
        self.stats["oracle_resets"] += 1
        for action in self.history:
            if _terminal(self.oracle.state):
                raise RuntimeError("actual prefix ended before teacher decision")
            self._act(action)
        if self._expected_observation is not None:
            actual = self.oracle.state["observation"]
            if any(actual.get(key) != value for key, value in self._expected_observation.items()):
                raise RuntimeError("planning oracle prefix differs from the actual public observation")
        if self._expected_tick is not None and self.oracle.state["info"].get("ticks") != self._expected_tick:
            raise RuntimeError("planning oracle prefix has different simulation time")
        for action in suffix:
            if _terminal(self.oracle.state):
                break
            self._act(action)
        return self.oracle.state

    def label(self, observation: dict, info: dict | None = None) -> Action:
        """Suggest a public action without claiming it was executed.

        After the caller validates and executes its chosen action, it must call
        observe_action with that ACTUAL accepted action. Rejected actions never
        advance history. This is required for tool-assisted actors and DAgger.
        """
        if not isinstance(observation, dict):
            raise ValueError("public observation object required")
        if self._last_label is not None:
            # An unexecuted/rejected recommendation must not retain its continuation.
            self.queue.clear()
            self.warm.clear()
        self._expected_observation = copy.deepcopy(observation)
        self._expected_tick = info.get("ticks") if isinstance(info, dict) else None
        if self.game == "angry-birds":
            action = self._birds(observation)
        else:
            action = self._ascent(observation)
        self._last_label = copy.deepcopy(action)
        return copy.deepcopy(action)

    def observe_action(self, action: Action) -> None:
        """Record one already engine-accepted action, never a hypothetical label."""
        if not isinstance(action, dict):
            raise ValueError("accepted action object required")
        if action != self._last_label:
            # Cached continuations were computed for another first action.
            self.queue.clear()
            self.warm.clear()
        self.history.append(copy.deepcopy(action))
        self._last_label = None
        self._expected_observation = None
        self._expected_tick = None

    def __call__(self, observation: dict, info: dict | None = None) -> Action:
        """Legacy direct-planning policy; caller promises to execute this action."""
        action = self.label(observation, info)
        self.observe_action(action)
        return action

    @staticmethod
    def _bird_value(state: dict) -> tuple:
        o = state["observation"]
        # Success, killed pigs and score dominate incidental structural damage.
        health = sum(max(0, e["health"]) for e in o["entities"] if e["kind"] != "platform")
        return (bool(state.get("info", {}).get("success")), -o["pigs_left"],
                o["score"], -health)

    def _shot_trial(self, launch: Action, ability_delay: int | None) -> tuple[dict, list[Action]]:
        # Trial starts with the exact public action prefix, then runs one flight.
        state = self._trial([launch])
        sequence = [launch]
        elapsed = launch["ticks"]
        used = False
        while not _terminal(state) and state["observation"]["phase"] == "flying":
            ready = state["observation"]["ability_ready"]
            if ability_delay is not None and not used and ready and elapsed >= ability_delay:
                action = dict(type="ability", ticks=30)
                used = True
            else:
                # Preserve the selected activation time as an exact vocabulary wait.
                wait = min(120, ability_delay - elapsed) if ability_delay is not None and not used and elapsed < ability_delay else 120
                action = dict(type="wait", ticks=max(30, wait))
            state = self._act(action)
            sequence.append(action)
            elapsed += action["ticks"]
            if elapsed >= 720:
                break
        return state, sequence

    def _birds(self, observation: dict) -> Action:
        if self.queue:
            return self.queue.pop(0)
        if observation["phase"] != "aiming":
            return dict(type="wait", ticks=120)
        best, best_sequence = None, None
        launches = [a for a in self.vocabulary if a["type"] == "launch"]
        # Rotate ties between levels/episodes without touching evaluation state.
        self.random.shuffle(launches)
        delays = (None,) if observation["next_bird"] == "red" else (None, 30, 60, 90)
        try:
            for launch in launches:
                for delay in delays:
                    state, sequence = self._shot_trial(launch, delay)
                    value = self._bird_value(state)
                    if best is None or value > best:
                        best, best_sequence = value, sequence
                    if value[0]:
                        break
                if best and best[0]:
                    break
        except OracleBudgetExhausted:
            self.stats["budget_exhausted"] = True
        if best_sequence:
            self.queue = copy.deepcopy(best_sequence[1:])
            return best_sequence[0]
        # A finite safe fallback, also part of the distillation vocabulary.
        return dict(type="launch", x=-85, y=0, ticks=30)

    @staticmethod
    def _ascent_target(observation: dict) -> tuple[float, float]:
        """Nearest higher exposed ledge from *observed* nearby terrain only."""
        x, y = observation["position"]
        candidates = []
        for polygon in observation["nearby_terrain"]:
            top = max(p[1] for p in polygon)
            if top < y - .45:
                continue
            upper = [p for p in polygon if p[1] >= top - .2]
            tx = sum(p[0] for p in upper) / len(upper)
            # Prefer the next ledge, not the highest currently visible one.
            cost = abs(tx - x) + 1.5 * max(0, top - y)
            candidates.append((cost, tx, top + .55))
        if not candidates:
            return x, y + 2
        _, tx, ty = min(candidates)
        return tx, ty

    @staticmethod
    def _ascent_value(state: dict, target: tuple[float, float], initial: dict) -> float:
        o = state["observation"]
        if o["falls"] > initial["falls"]:
            return -1000.0
        x, y = o["position"]
        tx, ty = target
        # Receding-horizon potential: sustained height + route proximity + a
        # small velocity term. Run-best alone rewards an unrecoverable jump.
        return (3.0 * y + 1.5 * o["best_height"]
                - .7 * math.hypot(x - tx, y - ty)
                + .1 * o["velocity"][1] + .05 * bool(o["gripping"]))

    def _ascent(self, observation: dict) -> Action:
        target = self._ascent_target(observation)
        actions = self.vocabulary
        candidates: list[list[Action]] = []
        if self.warm:
            candidates.append(self.warm + [self.random.choice(actions)])
        # Include all reach directions as the first move, with randomized
        # continuations so the planner can discover anchor/extension/release.
        for i in range(self.samples):
            if i < 16:
                first = actions[i * 4]  # 16 directions, hold true, 15 ticks
            else:
                first = self.random.choice(actions)
            seq = [first] + [self.random.choice(actions) for _ in range(self.horizon - 1)]
            candidates.append(seq)
        best, sequence = -math.inf, None
        try:
            for candidate in candidates:
                state = self._trial(candidate)
                value = self._ascent_value(state, target, observation)
                if value > best:
                    best, sequence = value, candidate
        except OracleBudgetExhausted:
            self.stats["budget_exhausted"] = True
        if sequence:
            self.warm = copy.deepcopy(sequence[1:])
            return sequence[0]
        # No more oracle compute. Reach under the observed body and alternate
        # extension/release controls to remain a bounded valid policy.
        i = len(self.history) % 3
        return actions[(12 if i == 0 else 10 if i == 1 else 0) * 4 + (0 if i != 2 else 1)]


def collect(executable: str, game: str, level: int, output: str, steps: int = 300,
            seed: int = 0, candidate_budget: int = 1200,
            tick_budget: int = 2_000_000, samples: int = 24, horizon: int = 3) -> dict:
    """Write a replayable planner episode and pre-action demonstration rows."""
    require_worker()
    if not 1 <= steps <= 10000:
        raise ValueError("steps must be in [1,10000]")
    if game == "angry-birds" and level >= 8:
        split = "heldout"
    elif game == "angry-birds" and level >= 6:
        split = "validation"
    else:
        split = "train"
    env = GameEnvironment(executable, game, level=level)
    policy = PlanningPolicy(executable, game, level, seed, candidate_budget,
                           tick_budget, samples, horizon)
    episode_id = f"planner-{game}-{level}-{seed}"
    try:
        with Path(output).open("x") as target:
            def write(record):
                target.write(json.dumps(record, separators=(",", ":")) + "\n")
                target.flush()
            observation, info = env.reset()
            write(dict(event="metadata", policy="simulator-query-planner-v1", game=game,
                       level=level, split=split, episode_id=episode_id, seed=seed,
                       planner_seed=seed, environment_seed=None, layout_randomized=False,
                       candidate_budget=candidate_budget, tick_budget=tick_budget,
                       planning_samples=samples, planning_horizon=horizon))
            write(dict(event="reset", request=dict(op="reset", game=game, level=level), response=env.state))
            for step in range(steps):
                if _terminal(env.state):
                    break
                before = copy.deepcopy(observation)
                before_info = copy.deepcopy(info)
                action = policy(observation, info)
                observation, reward, terminated, truncated, info = env.step(action)
                write(dict(event="step", step=step, observation=before, action=action,
                           response=env.state, game=game, level=level, split=split,
                           episode_id=episode_id, info=before_info))
            summary = dict(event="summary", final=env.state, stats=policy.stats,
                           executed_actions=len(policy.history), episode_id=episode_id)
            write(summary)
            return summary
    finally:
        policy.close()
        env.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    parser.add_argument("--game", choices=("angry-birds", "getting-over-it"), required=True)
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--candidate-budget", type=int, default=1200)
    parser.add_argument("--tick-budget", type=int, default=2_000_000)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--horizon", type=int, default=3)
    args = vars(parser.parse_args())
    args["executable"] = args.pop("env")
    summary = collect(**args)
    print(json.dumps(summary, separators=(",", ":")))


if __name__ == "__main__":
    main()
