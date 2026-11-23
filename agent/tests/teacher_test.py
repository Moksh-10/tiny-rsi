"""Planner contract tests use a deterministic fake oracle, never host rollouts."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research import teacher


class FakeBirdEnvironment:
    instances = []

    def __init__(self, executable, game, level=0):
        self.closed = False
        self.requests = []
        self.instances.append(self)

    def reset(self):
        self.requests.append(("reset",))
        self.state = dict(ok=True, observation=dict(phase="aiming", next_bird="red",
                          ability_ready=False, pigs_left=2, score=0, entities=[]),
                          info=dict(success=False), terminated=False, truncated=False)
        return copy.deepcopy(self.state["observation"]), self.state["info"]

    def act(self, action):
        self.requests.append(("act", copy.deepcopy(action)))
        o = self.state["observation"]
        if action["type"] == "launch":
            self.pull = action["x"], action["y"]
            o["phase"] = "flying"
        else:
            exact = self.pull == (-85, 0)
            o["score"] = 1000 - abs(self.pull[0] + 85) * 2 - abs(self.pull[1])
            o["pigs_left"] = 0 if exact else 1
            o["phase"] = "won" if exact else "aiming"
            self.state["terminated"] = exact
            self.state["info"]["success"] = exact
        return copy.deepcopy(self.state)

    def close(self):
        self.closed = True


class TeacherTest(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(teacher, "require_worker")
        self.environment = patch.object(teacher, "GameEnvironment", FakeBirdEnvironment)
        self.guard.start()
        self.environment.start()
        self.addCleanup(self.guard.stop)
        self.addCleanup(self.environment.stop)

    def make(self, **kwargs):
        policy = teacher.TeacherPolicy("unused", "angry-birds", **kwargs)
        self.addCleanup(policy.close)
        return policy

    def test_search_finds_best_legal_shot_and_queues_real_controls(self):
        policy = self.make()
        observation = dict(phase="aiming", next_bird="red")
        original = copy.deepcopy(observation)
        action = policy(observation)
        self.assertEqual(action, dict(type="launch", x=-85, y=0, ticks=30))
        self.assertEqual(observation, original)
        self.assertEqual(policy(dict(phase="flying")), dict(type="wait", ticks=120))
        self.assertGreater(policy.stats["candidate_rollouts"], 1)
        # The oracle has only reset + public action calls, never injected state.
        self.assertTrue(all(q[0] in ("reset", "act") for q in policy.oracle.requests))

    def test_requested_ticks_including_reset_cannot_exceed_budget(self):
        policy = self.make(tick_budget=120)
        action = policy(dict(phase="aiming", next_bird="red"))
        self.assertIn(action, teacher.action_vocabulary("angry-birds"))
        self.assertLessEqual(policy.stats["oracle_ticks"], 120)
        self.assertTrue(policy.stats["budget_exhausted"])
        self.assertEqual(policy.stats["oracle_reset_ticks"], 60)

    def test_candidate_limit_counts_attempted_sequences(self):
        policy = self.make(candidate_budget=1)
        policy(dict(phase="aiming", next_bird="red"))
        self.assertEqual(policy.stats["candidate_rollouts"], 1)
        self.assertTrue(policy.stats["budget_exhausted"])

    def test_vocabulary_is_finite_distinct_and_in_engine_range(self):
        for game in ("angry-birds", "getting-over-it"):
            actions = teacher.action_vocabulary(game)
            self.assertEqual(len(actions), len({str(sorted(a.items())) for a in actions}))
            for action in actions:
                self.assertTrue(1 <= action["ticks"] <= 120)
                if action["type"] == "launch":
                    self.assertTrue(8 <= math.hypot(action["x"], action["y"]) <= 95)
                if action["type"] == "hammer":
                    self.assertTrue(abs(action["x"]) <= 3.15 and abs(action["y"]) <= 3.15)
                    self.assertIsInstance(action["hold"], bool)

    def test_reset_clears_episode_history_and_compute_counts(self):
        policy = self.make(candidate_budget=1)
        policy(dict(phase="aiming", next_bird="red"))
        policy.reset()
        self.assertEqual(policy.history, [])
        self.assertEqual(policy.queue, [])
        self.assertEqual(policy.stats["oracle_ticks"], 0)

    def test_ascent_target_uses_nearest_higher_observed_ledge(self):
        observation = dict(position=[-5, .55], nearby_terrain=[
            [[-30, -5], [13, -5], [13, 0], [-30, 0]],
            [[-.5, .2], [2.5, .2], [2, 1.1], [0, 1.2]],
            [[1, 1], [4, 1], [4, 4], [2, 4]],
        ])
        x, y = teacher.TeacherPolicy._ascent_target(observation)
        self.assertAlmostEqual(x, 1)
        self.assertAlmostEqual(y, 1.75)


if __name__ == "__main__":
    unittest.main()
