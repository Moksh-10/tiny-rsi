#!/usr/bin/env python3
"""Small, genuinely trained state policies: CART and a tanh/softmax neural student.

No package download, pickle, model-generated code, environment state injection, or
Ollama inference is used here. Real training entry points require the Linux VM.
Only the pure numerical learner functions are exposed for tiny synthetic tests.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any

GAMES = ("angry-birds", "getting-over-it")
MAX_CLASSES = 128
MAX_ROWS = 10000
MAX_FILE = 32 * 1024 * 1024
MAX_RECORD = 1024 * 1024
CHECKPOINT_LIMIT = 2 * 1024 * 1024
FEATURE_VERSION = 1


def require_worker() -> None:
    """Operational boundary shared with the provisioned worker, never an env flag."""
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("policy training requires an unprivileged Linux VM worker")
    for path, expected in (("/etc/game-research/worker", "game-research-lima-v1\n"),
                           ("/run/game-research/sealed", "sealed-v1\n")):
        p = Path(path)
        st = p.stat()
        if p.read_text() != expected or st.st_uid != 0 or st.st_mode & 0o022:
            raise RuntimeError("worker must have root-owned provisioned/sealed markers")
    detected = subprocess.run(["systemd-detect-virt", "--vm"], capture_output=True,
                              text=True, timeout=5, check=False)
    if detected.returncode or detected.stdout.strip() in ("", "none"):
        raise RuntimeError("a virtual machine is required")
    for line in Path("/proc/mounts").read_text().splitlines():
        fields = line.split()
        if len(fields) > 2 and (fields[2] in ("9p", "virtiofs") or "sshfs" in fields[2]):
            raise RuntimeError("host-sharing mount detected")


def finite(value: Any, scale: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return 0.0
    return max(-4.0, min(4.0, value / scale))


def pair(value: Any, sx: float, sy: float) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return [0.0, 0.0]
    return [finite(value[0], sx), finite(value[1], sy)]


def features(game: str, observation: dict, info: dict | None = None) -> list[float]:
    """Fixed public-state feature map; no level identity or evaluator labels."""
    if game not in GAMES or not isinstance(observation, dict):
        raise ValueError("game and observation are required")
    info = info or {}
    if game == "angry-birds":
        phase = observation.get("phase")
        bird = observation.get("next_bird")
        x = [float(phase == p) for p in ("aiming", "flying", "won", "lost")]
        x += [float(bool(observation.get("ability_ready"))),
              finite(observation.get("birds_left"), 3), finite(observation.get("pigs_left"), 10),
              finite(observation.get("score"), 10000)]
        x += [float(bird == kind) for kind in ("red", "dash", "bomb")]
        entities = [e for e in observation.get("entities", []) if isinstance(e, dict)][:128]
        entities.sort(key=lambda e: tuple(pair(e.get("position"), 1500, 800)))
        pigs = [e for e in entities if e.get("kind") == "pig"]
        for i in range(3):
            x += pair(pigs[i].get("position"), 1500, 800) if i < len(pigs) else [0.0, 0.0]
        kinds = ("wood", "stone", "glass", "tnt", "platform", "pig")
        x += [sum(e.get("kind") == k for e in entities) / 30 for k in kinds]
        structures = [e for e in entities if e.get("kind") not in ("bird", "pig")]
        for i in range(4):
            if i >= len(structures):
                x += [0.0] * 6
            else:
                e = structures[i]
                x += pair(e.get("position"), 1500, 800) + pair(e.get("size"), 200, 200)
                x += [(kinds.index(e["kind"]) + 1) / 6 if e.get("kind") in kinds else 0.0,
                      finite(e.get("health"), 20)]
        moving = [e for e in entities if e.get("kind") == "bird"]
        if moving:
            x += pair(moving[-1].get("position"), 1500, 800)
            x += pair(moving[-1].get("velocity"), 1000, 1000)
        else:
            x += [0.0] * 4
    else:
        position = observation.get("position", [0, 0])
        px, py = pair(position, 1, 1)  # Use un-clipped values below for relative geometry.
        if isinstance(position, (list, tuple)) and len(position) == 2:
            px = float(position[0]) if isinstance(position[0], (int, float)) and math.isfinite(position[0]) else 0
            py = float(position[1]) if isinstance(position[1], (int, float)) and math.isfinite(position[1]) else 0
        x = pair(position, 30, 66) + pair(observation.get("velocity"), 20, 20)
        tip = observation.get("tip", [px, py])
        x += [finite(tip[0] - px, 3.3), finite(tip[1] - py, 3.3)] if isinstance(tip, list) and len(tip) == 2 else [0.0, 0.0]
        x += pair(observation.get("aim"), 3.15, 3.15)
        x += [float(bool(observation.get("gripping"))), float(bool(observation.get("grounded"))),
              finite(observation.get("best_height"), 66), finite(observation.get("falls"), 100)]
        points = []
        for polygon in observation.get("nearby_terrain", [])[:128]:
            for point in polygon[:128] if isinstance(polygon, list) else []:
                if isinstance(point, list) and len(point) == 2 and all(isinstance(v, (float, int)) and math.isfinite(v) for v in point):
                    points.append((point[0] - px, point[1] - py - 0.55))
        points.sort(key=lambda point: point[0] ** 2 + point[1] ** 2)
        for i in range(8):
            x += [finite(v, 8) for v in points[i]] if i < len(points) else [0.0, 0.0]
    x.append(finite(info.get("ticks"), 18000))
    return x


def action_key(game: str, action: dict) -> str:
    if not isinstance(action, dict):
        raise ValueError("action object required")
    kind, ticks = action.get("type"), action.get("ticks")
    if isinstance(ticks, bool) or not isinstance(ticks, int) or not 1 <= ticks <= 120:
        raise ValueError("invalid teacher ticks")
    fields = {"type", "ticks"}
    if game == "angry-birds" and kind in ("wait", "ability"):
        pass
    elif (game == "angry-birds" and kind == "launch") or (game == "getting-over-it" and kind == "hammer"):
        fields |= {"x", "y"}
        limit = 95 if game == "angry-birds" else 3.15
        for key in ("x", "y"):
            value = action.get(key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) > limit:
                raise ValueError("invalid teacher aim")
        if game == "angry-birds" and not 8 <= math.hypot(action["x"], action["y"]) <= 95.001:
            raise ValueError("invalid teacher pull")
        if game == "getting-over-it":
            fields.add("hold")
            if not isinstance(action.get("hold"), bool):
                raise ValueError("hold boolean required")
    else:
        raise ValueError("invalid teacher action")
    if action.keys() != fields:
        raise ValueError("unknown/missing teacher action fields")
    return json.dumps(action, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_examples(paths: list[str], game: str, max_rows: int = MAX_ROWS) -> tuple[list[dict], dict]:
    """Accept demo rows or metadata/reset/step/summary trajectories. Never accept holdout labels."""
    if not 1 <= max_rows <= MAX_ROWS or not 1 <= len(paths) <= 128:
        raise ValueError("dataset budget exceeded")
    rows = []
    sources = []
    quality = collections.Counter()
    for filename in paths:
        path = Path(filename)
        if path.stat().st_size > MAX_FILE:
            raise ValueError("dataset file exceeds 32 MiB")
        digest = hashlib.sha256()
        meta, previous, episode = {}, None, 0
        pending = []
        with path.open("rb") as source:
            while line := source.readline(MAX_RECORD + 1):
                if len(line) > MAX_RECORD:
                    raise ValueError("dataset record exceeds 1 MiB")
                digest.update(line)
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("dataset row must be an object")
                kind = event.get("event")
                if kind == "metadata":
                    meta = event
                    continue
                if kind == "reset":
                    if pending:
                        quality["incomplete_episodes_rejected"] += 1
                    pending = []
                    previous = event.get("response")
                    episode += 1
                    continue
                if kind == "summary":
                    final = event.get("final", {})
                    final_obs = final.get("observation", {})
                    accepted = bool(final.get("info", {}).get("success")) if game == "angry-birds" else finite(final_obs.get("best_height"), 1) >= 1.0
                    if pending and accepted:
                        # Remove a climbing teacher's stalled tail after its last new height.
                        if game == "getting-over-it":
                            best, cut = 0.0, len(pending)
                            for i, row in enumerate(pending):
                                if row["_height"] > best + 1e-6:
                                    best, cut = row["_height"], i + 1
                            pending = pending[:cut]
                        for row in pending:
                            row.pop("_height", None)
                        rows.extend(pending)
                        quality["accepted_teacher_episodes"] += 1
                    elif pending:
                        quality["unsuccessful_teacher_episodes_rejected"] += 1
                    pending = []
                    continue
                if kind == "error":
                    continue
                row_game = event.get("game", meta.get("game"))
                if row_game != game:
                    continue
                level = event.get("level", meta.get("level", 0))
                split = event.get("split", meta.get("split", "train"))
                if split != "train" or (game == "angry-birds" and (not isinstance(level, int) or not 0 <= level <= 5)):
                    raise ValueError("held-out labels are forbidden in student training")
                if kind == "step":
                    response = event.get("response")
                    observation = event.get("observation") or ((previous or {}).get("observation"))
                    info = event.get("info") or ((previous or {}).get("info")) or {}
                    previous = response if isinstance(response, dict) and response.get("ok") else previous
                    if not isinstance(response, dict) or not response.get("ok"):
                        continue
                else:
                    observation = event.get("observation")
                    info = event.get("info", {})
                if not isinstance(observation, dict) or "action" not in event:
                    continue
                key = action_key(game, event["action"])
                group = f"level:{level}" if game == "angry-birds" else str(event.get("episode_id", meta.get("episode_id", f"{path.name}:{episode}")))
                row = {"x": features(game, observation, info), "label": key, "group": group}
                if kind == "step":
                    row["_height"] = finite((response.get("observation") or {}).get("best_height"), 66) * 66
                    pending.append(row)
                else:
                    rows.append(row)
                    quality["direct_correction_rows"] += 1
                if len(rows) + len(pending) > max_rows:
                    raise ValueError("dataset exceeds configured row budget; explicitly subsample before training")
        if pending:
            quality["incomplete_episodes_rejected"] += 1
        sources.append({"file": path.name, "sha256": digest.hexdigest()})
    if not rows:
        raise ValueError("no valid training demonstrations")
    if len({r["label"] for r in rows}) > MAX_CLASSES:
        raise ValueError("action vocabulary exceeds 128 classes")
    return rows, {"sources": sources, "rows": len(rows), "groups": sorted({r["group"] for r in rows}), "quality":dict(quality),
                  "quality_rules":{"birds":"successful teacher episodes only", "ascent":"best_height >= 1m; drop trailing stalled actions", "direct_rows":"caller-supplied teacher corrections; not inferred successes"}}


def counts(labels: list[int], classes: int) -> list[int]:
    result = [0] * classes
    for label in labels:
        result[label] += 1
    return result


def tree_fit(xs: list[list[float]], ys: list[int], classes: int, *, depth: int = 4,
             min_leaf: int = 1, deadline: float = math.inf) -> dict:
    """CART impurity minimization learns all thresholds and leaves from data."""
    dimensions = len(xs[0])
    nodes = 0
    def build(indices: list[int], remaining: int) -> dict:
        nonlocal nodes
        if time.monotonic() > deadline:
            raise TimeoutError("training wall budget exhausted")
        nodes += 1
        histogram = counts([ys[i] for i in indices], classes)
        prediction = max(range(classes), key=lambda k: (histogram[k], -k))
        leaf = {"class": prediction, "counts": histogram}
        if remaining == 0 or len(indices) < 2 * min_leaf or histogram[prediction] == len(indices) or nodes >= 4096:
            return leaf
        best = None
        base = len(indices) - sum(v * v for v in histogram) / len(indices)
        for feature in range(dimensions):
            ordered = sorted(indices, key=lambda i: xs[i][feature])
            if time.monotonic() > deadline:
                raise TimeoutError("training wall budget exhausted")
            left, right = [0] * classes, histogram.copy()
            left_sq, right_sq = 0, sum(v*v for v in right)
            for position in range(len(ordered) - 1):
                index = ordered[position]
                label = ys[index]
                left_sq += 2 * left[label] + 1
                right_sq += -2 * right[label] + 1
                left[label] += 1
                right[label] -= 1
                nl, nr = position + 1, len(ordered) - position - 1
                if nl < min_leaf or nr < min_leaf or xs[index][feature] == xs[ordered[position + 1]][feature]:
                    continue
                # Limit large datasets to ~64 quantile candidates per feature.
                if len(ordered) > 256 and position % max(1, len(ordered) // 64):
                    continue
                impurity = nl - left_sq / nl + nr - right_sq / nr
                if impurity < base - 1e-10 and (best is None or impurity < best[0] - 1e-10):
                    best = (impurity, feature, (xs[index][feature] + xs[ordered[position + 1]][feature]) / 2, ordered, nl)
        if best is None:
            return leaf
        _, feature, threshold, ordered, cut = best
        left_indices, right_indices = ordered[:cut], ordered[cut:]
        return {"feature": feature, "threshold": threshold,
                "left": build(left_indices, remaining - 1), "right": build(right_indices, remaining - 1)}
    return {"architecture": "tree", "dimensions": dimensions, "classes": classes, "root": build(list(range(len(xs))), depth)}


def tree_predict(model: dict, x: list[float]) -> int:
    node = model["root"]
    for _ in range(32):
        if "class" in node:
            return node["class"]
        node = node["left"] if x[node["feature"]] <= node["threshold"] else node["right"]
    raise ValueError("tree depth exceeds limit")


def softmax(values: list[float]) -> list[float]:
    peak = max(values)
    values = [math.exp(v - peak) for v in values]
    total = sum(values)
    return [v / total for v in values]


def neural_forward(model: dict, x: list[float]) -> tuple[list[float], list[float]]:
    hidden = [math.tanh(sum(w * value for w, value in zip(row, x)) + bias)
              for row, bias in zip(model["w1"], model["b1"])]
    output = [sum(w * value for w, value in zip(row, hidden)) + bias
              for row, bias in zip(model["w2"], model["b2"])]
    return hidden, softmax(output)


def neural_fit(xs: list[list[float]], ys: list[int], classes: int, *, hidden: int = 16,
               epochs: int = 30, learning_rate: float = 0.03, seed: int = 0,
               deadline: float = math.inf) -> dict:
    """Actual tanh neural network: online SGD through cross-entropy and both layers."""
    rng = random.Random(seed)
    dimensions = len(xs[0])
    radius1, radius2 = math.sqrt(6 / (dimensions + hidden)), math.sqrt(6 / (hidden + classes))
    model = {"architecture": "mlp", "dimensions": dimensions, "classes": classes,
             "w1": [[rng.uniform(-radius1, radius1) for _ in range(dimensions)] for _ in range(hidden)],
             "b1": [0.0] * hidden,
             "w2": [[rng.uniform(-radius2, radius2) for _ in range(hidden)] for _ in range(classes)],
             "b2": [0.0] * classes}
    histogram = counts(ys, classes)
    class_weights = [min(4.0, len(ys) / (classes * max(1, n))) for n in histogram]
    losses = []
    for epoch in range(epochs):
        if time.monotonic() > deadline:
            raise TimeoutError("training wall budget exhausted")
        order = list(range(len(xs)))
        rng.shuffle(order)
        order = order[:2048]
        loss = 0.0
        rate = learning_rate / (1 + 0.02 * epoch)
        for position, index in enumerate(order):
            if position % 32 == 0 and time.monotonic() > deadline:
                raise TimeoutError("training wall budget exhausted")
            x, target = xs[index], ys[index]
            h, probabilities = neural_forward(model, x)
            loss -= math.log(max(1e-12, probabilities[target]))
            delta = probabilities.copy()
            delta[target] -= 1
            delta = [v * class_weights[target] for v in delta]
            hidden_delta = [(1 - value * value) * sum(model["w2"][k][j] * delta[k] for k in range(classes))
                            for j, value in enumerate(h)]
            for k in range(classes):
                change = rate * delta[k]
                model["b2"][k] -= change
                for j in range(hidden):
                    model["w2"][k][j] -= change * h[j]
            for j in range(hidden):
                change = rate * hidden_delta[j]
                model["b1"][j] -= change
                for feature in range(dimensions):
                    model["w1"][j][feature] -= change * x[feature]
        losses.append(loss / len(order))
    model["training_loss"] = losses
    return model


def predict_index(model: dict, x: list[float]) -> int:
    if model["architecture"] == "tree":
        return tree_predict(model, x)
    _, p = neural_forward(model, x)
    return max(range(len(p)), key=lambda i: (p[i], -i))


def metrics(model: dict, xs: list[list[float]], ys: list[int]) -> dict:
    if not ys:
        return {"accuracy": None, "balanced_accuracy": None, "rows": 0}
    correct, totals = collections.Counter(), collections.Counter(ys)
    for x, target in zip(xs, ys):
        correct[target] += predict_index(model, x) == target
    return {"accuracy": sum(correct.values()) / len(ys),
            "balanced_accuracy": sum(correct[k] / n for k, n in totals.items()) / len(totals), "rows": len(ys)}


def model_parameters(model: dict) -> int:
    if model["architecture"] == "mlp":
        return sum(len(row) for key in ("w1", "w2") for row in model[key]) + len(model["b1"]) + len(model["b2"])
    def size(node: dict) -> int:
        return len(node["counts"]) if "class" in node else 2 + size(node["left"]) + size(node["right"])
    return size(model["root"])


class PolicyBaseline:
    def __init__(self, checkpoint: dict):
        self.checkpoint = checkpoint
        self.game = checkpoint["game"]
        self.model = checkpoint["model"]
        self.actions = checkpoint["actions"]
    @classmethod
    def load(cls, filename: str | Path) -> "PolicyBaseline":
        path = Path(filename)
        if path.stat().st_size > CHECKPOINT_LIMIT:
            raise ValueError("checkpoint exceeds 2 MiB")
        checkpoint = json.loads(path.read_text())
        if checkpoint.get("format") != "game-student-v1" or checkpoint.get("feature_version") != FEATURE_VERSION or checkpoint.get("game") not in GAMES:
            raise ValueError("unsupported student checkpoint")
        actions, model = checkpoint.get("actions"), checkpoint.get("model")
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_CLASSES:
            raise ValueError("invalid vocabulary")
        for action in actions:
            action_key(checkpoint["game"], action)
        dimensions = len(features(checkpoint["game"], {}))
        if model.get("dimensions") != dimensions or model.get("classes") != len(actions):
            raise ValueError("checkpoint dimensions mismatch")
        if model.get("architecture") == "tree":
            def validate(node: dict, depth: int = 0) -> None:
                if depth > 16:
                    raise ValueError("oversized tree")
                if "class" in node:
                    if not isinstance(node["class"], int) or not 0 <= node["class"] < len(actions):
                        raise ValueError("invalid leaf")
                    return
                if not isinstance(node.get("feature"), int) or not 0 <= node["feature"] < dimensions or not math.isfinite(node.get("threshold", math.nan)):
                    raise ValueError("invalid split")
                validate(node["left"], depth + 1)
                validate(node["right"], depth + 1)
            validate(model["root"])
        elif model.get("architecture") == "mlp":
            hidden = len(model["b1"])
            if not 1 <= hidden <= 32 or len(model["w1"]) != hidden or len(model["w2"]) != len(actions) or len(model["b2"]) != len(actions):
                raise ValueError("invalid neural dimensions")
            for rows, width in ((model["w1"], dimensions), (model["w2"], hidden)):
                for row in rows:
                    if len(row) != width or not all(isinstance(v, (float, int)) and math.isfinite(v) and abs(v) < 1e6 for v in row):
                        raise ValueError("invalid neural weights")
            if not all(isinstance(v, (float, int)) and math.isfinite(v) and abs(v) < 1e6 for key in ("b1", "b2") for v in model[key]):
                raise ValueError("invalid neural biases")
        else:
            raise ValueError("unsupported architecture")
        return cls(checkpoint)
    def predict(self, observation: dict, info: dict | None = None) -> dict:
        index = predict_index(self.model, features(self.game, observation, info))
        action = dict(self.actions[index])
        # Legality projection is a shared interface constraint, not a planner.
        if self.game == "angry-birds":
            if action["type"] == "launch" and observation.get("phase") != "aiming":
                return {"type": "wait", "ticks": 120}
            if action["type"] == "ability" and not observation.get("ability_ready"):
                return {"type": "wait", "ticks": 120}
        return action
    __call__ = predict


def _config(config: dict | None) -> dict:
    c = {"architecture": "both", "depths": [2, 4, 8], "min_leaves": [1],
         "hidden_sizes": [8, 16], "epochs": [30], "learning_rates": [0.03],
         "seed": 0, "max_rows": MAX_ROWS, "max_candidates": 12, "max_seconds": 120}
    if config:
        if not isinstance(config, dict) or set(config) - set(c):
            raise ValueError("unknown training configuration fields")
        c.update(config)
    if c["architecture"] not in ("tree", "mlp", "both"):
        raise ValueError("unsupported training architecture")
    bounds = {"depths": (1, 16), "min_leaves": (1, 32), "hidden_sizes": (1, 32),
              "epochs": (1, 100), "learning_rates": (0.0001, 0.3)}
    for key, (low, high) in bounds.items():
        values = c[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            raise ValueError(f"invalid {key}")
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"out of bounds: {key}")
            if key != "learning_rates" and not isinstance(value, int):
                raise ValueError(f"integer required: {key}")
    for key, low, high in (("seed", 0, 2**31 - 1), ("max_rows", 1, MAX_ROWS), ("max_candidates", 1, 12), ("max_seconds", 1, 600)):
        if isinstance(c[key], bool) or not isinstance(c[key], int) or not low <= c[key] <= high:
            raise ValueError(f"invalid {key}")
    return c


def train_candidates(data_paths: list[str], output_dir: str, game: str,
                     config: dict | None = None) -> dict:
    """Train, internally validate, select, then refit; sealed gameplay eval stays external."""
    require_worker()
    if game not in GAMES:
        raise ValueError("unsupported game")
    c = _config(config)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + c["max_seconds"]
    rows, dataset = load_examples(data_paths, game, c["max_rows"])
    labels = sorted({row["label"] for row in rows})
    vocabulary = [json.loads(label) for label in labels]
    lookup = {label: index for index, label in enumerate(labels)}
    groups = sorted({row["group"] for row in rows})
    # Validation is independent by training level/episode, never an arbitrary row split.
    hold_groups = set(groups[-max(1, len(groups) // 4):]) if len(groups) >= 2 else set()
    train = [r for r in rows if r["group"] not in hold_groups]
    validation = [r for r in rows if r["group"] in hold_groups]
    validation_kind = "training-level/episode-group validation" if validation else "no independent validation: single training group"
    xs = [row["x"] for row in train]
    ys = [lookup[row["label"]] for row in train]
    vx = [row["x"] for row in validation]
    vy = [lookup[row["label"]] for row in validation]
    specifications = []
    if c["architecture"] in ("tree", "both"):
        specifications += [{"architecture": "tree", "depth": d, "min_leaf": m} for d in c["depths"] for m in c["min_leaves"]]
    if c["architecture"] in ("mlp", "both"):
        specifications += [{"architecture": "mlp", "hidden": h, "epochs": e, "learning_rate": rate}
                           for h in c["hidden_sizes"] for e in c["epochs"] for rate in c["learning_rates"]]
    specifications = specifications[:c["max_candidates"]]
    def fit(spec: dict, x: list, y: list) -> dict:
        params = {k: v for k, v in spec.items() if k != "architecture"}
        if spec["architecture"] == "tree":
            return tree_fit(x, y, len(labels), deadline=deadline, **params)
        return neural_fit(x, y, len(labels), seed=c["seed"], deadline=deadline, **params)
    def save(model: dict, filename: str, specification: dict, trained: bool = True) -> tuple[str, int, str]:
        checkpoint = {"format": "game-student-v1", "feature_version": FEATURE_VERSION,
                      "game": game, "actions": vocabulary, "model": model, "specification": specification,
                      "dataset": dataset, "seed": c["seed"], "training_split": "train only",
                      "training_state": "trained" if trained else "untrained"}
        content = json.dumps(checkpoint, separators=(",", ":"), allow_nan=False).encode()
        if len(content) > CHECKPOINT_LIMIT:
            raise ValueError("checkpoint exceeds size budget")
        path = output / filename
        with path.open("xb") as target:
            target.write(content)
        return str(path), len(content), hashlib.sha256(content).hexdigest()
    candidates = []
    for index, specification in enumerate(specifications):
        now = time.monotonic()
        if specification["architecture"] == "mlp":
            initial = neural_fit(xs, ys, len(labels), hidden=specification["hidden"], epochs=0,
                                 learning_rate=specification["learning_rate"], seed=c["seed"])
        else:
            initial = {"architecture":"tree", "dimensions":len(xs[0]), "classes":len(labels),
                       "root":{"class":random.Random(c["seed"]).randrange(len(labels)), "counts":[0]*len(labels)}}
        untrained_path, _, _ = save(initial, f"candidate-{index:03d}-untrained.json", specification, trained=False)
        initial_metrics = metrics(initial, vx, vy) if validation else metrics(initial, xs, ys)
        try:
            model = fit(specification, xs, ys)
        except TimeoutError:
            break
        training = metrics(model, xs, ys)
        valid = metrics(model, vx, vy) if validation else training.copy()
        checkpoint, size, digest = save(model, f"candidate-{index:03d}.json", specification)
        candidates.append({"id": index, "specification": specification, "training": training,
                           "validation": valid, "checkpoint": checkpoint, "checkpoint_bytes": size,
                           "sha256": digest, "parameters": model_parameters(model),
                           "training_seconds": time.monotonic() - now, "untrained_checkpoint":untrained_path,
                           "untrained_validation":initial_metrics})
    if not candidates:
        raise TimeoutError("no candidate completed inside training budget")
    selected = max(candidates, key=lambda item: (item["validation"]["balanced_accuracy"],
                    item["validation"]["accuracy"], -item["checkpoint_bytes"], -item["id"]))
    refitted = False
    checkpoint = selected["checkpoint"]
    try:
        final = fit(selected["specification"], [r["x"] for r in rows], [lookup[r["label"]] for r in rows])
        checkpoint, size, digest = save(final, "policy.json", selected["specification"])
        refitted = True
    except TimeoutError:
        final = PolicyBaseline.load(checkpoint).model
        size, digest = selected["checkpoint_bytes"], selected["sha256"]
    all_training = metrics(final, [r["x"] for r in rows], [lookup[r["label"]] for r in rows])
    report = {"format": "small-policy-baseline-training-v1", "game": game, "config": c,
              "dataset": dataset, "validation_kind": validation_kind,
              "internal_validation_groups": sorted(hold_groups), "checkpoint": checkpoint,
              "checkpoint_bytes": size, "sha256": digest, "parameters": model_parameters(final),
              "architecture": selected["specification"]["architecture"], "selected_candidate": selected["id"],
              "untrained_checkpoint":selected["untrained_checkpoint"],
              "untrained_validation":selected["untrained_validation"],
              "validation_accuracy": selected["validation"]["accuracy"],
              "validation_balanced_accuracy": selected["validation"]["balanced_accuracy"],
              "train_accuracy": all_training["accuracy"], "refitted_on_all_training": refitted,
              "training_seconds": time.monotonic() - started, "candidates": candidates,
              "limitations": ["This trains a small structured-state policy, not an LLM checkpoint.",
                              "Validation action agreement is not gameplay performance.",
                              "Sealed held-out gameplay evaluation must run separately."]}
    with (output / "training-report.json").open("x") as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--game", choices=GAMES, required=True)
    parser.add_argument("--config", help="bounded JSON configuration file, never Python code")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text()) if args.config else None
    print(json.dumps(train_candidates(args.data, args.output, args.game, config), allow_nan=False))


if __name__ == "__main__":
    main()
