#!/usr/bin/env python3
"""
make_demo.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Writes dashboard/demo.json: stored captures for the dashboard's demo mode,
each with the features (features.py) and logits of the model in
emi_classify/emi_model.h, computed exactly as the board computes them.

These captures were in the final model's training data, so the demo shows
how the detector behaves, not how accurate it is. Accuracy is in
analysis/train_summary.md.

    python dashboard/make_demo.py
"""

import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dataset          # noqa: E402
import features         # noqa: E402
import verify_board     # noqa: E402

PER_CLASS = 6
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.json")


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model = verify_board.load_header()
    rng = np.random.default_rng(0)
    by_class = defaultdict(lambda: defaultdict(list))
    for r in dataset.load():
        c = dataset.mechanism(r)
        if c:
            by_class[c][r["device"]].append(r)
    picked = []
    for c in model["classes"]:
        devices = by_class[c]
        # spread the picks over devices: one capture per device, round robin
        order = sorted(devices)
        i = 0
        while len([p for p in picked if p[0] == c]) < PER_CLASS and order:
            dev = order[i % len(order)]
            pool = devices[dev]
            if pool:
                picked.append((c, pool.pop(int(rng.integers(len(pool))))))
            else:
                order.remove(dev)
                continue
            i += 1
    rng.shuffle(picked)
    out = []
    for c, r in picked:
        rest = int(round(r["rest_ref"]))
        f = features.compute(r["values"], rest)
        logits, cls = verify_board.reference(model, f)
        out.append({
            "true": c, "device": r["device"], "distance_cm": r["distance_cm"],
            "mode": r["mode"], "rest_ref": rest,
            "values": [int(v) for v in r["values"]],
            "feat": [round(float(x), 6) for x in f],
            "logits": [round(float(x), 4) for x in logits], "cls": cls,
        })
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"classes": model["classes"], "captures": out}, fh, separators=(",", ":"))
    ok = sum(o["cls"] == o["true"] for o in out)
    print(f"wrote {OUT}: {len(out)} captures, {ok} given their own class")


if __name__ == "__main__":
    main()
