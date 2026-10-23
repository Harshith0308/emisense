#!/usr/bin/env python3
"""
attribution.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Joins the two halves of the paper's argument: of the captures on which the
amplitude threshold alarms (analyze.py's T, the 95th percentile of ambient
A = rest_ref - min), how many does the classifier attribute to their real
source class? Uses train.py's model and its three splits, over five seeds.

    python attribution.py

Writes analysis/attribution.json:
    T, the number of benign source, ambient and attack (emp) captures above
    it, and per test (blocks, rooms, models held out) one value per seed of
      sources_correct                 alarmed benign source captures given their class
      sources_called_ambient          alarmed benign source captures called ambient
      sources_called_emp              alarmed benign source captures called the attack
      ambient_alarms_called_ambient   alarmed ambient captures called ambient
      emp_alarms_called_emp           alarmed attack captures called the attack
    Attack captures are never held out by room (one place) or model (one
    emitter), so the last two exist only where they can be tested.
"""

import json

import numpy as np

import dataset
import features
import train

SEEDS = range(5)


def main():
    everything = dataset.load()
    amp = {id(r): (r["rest_ref"] or float(np.median(r["values"]))) - int(r["values"].min())
           for r in everything}
    T = float(np.percentile([amp[id(r)] for r in everything if r["label"] == "ambient"], 95))

    recs = [r for r in everything if dataset.mechanism(r)]
    y = np.array([dataset.mechanism(r) for r in recs])
    alarm = np.array([amp[id(r)] for r in recs]) > T
    X = train.transform([features.compute(r["values"], r.get("rest_ref")) for r in recs],
                        features.FEATURE_NAMES)
    blocks = np.array([r["block"] for r in recs])
    rooms = np.array([r["room"] for r in recs])
    models = np.array([dataset.model_of(r) for r in recs])
    # Benign sources only: an alarm on the attack (emp) is a true alarm, not a
    # false one. The attack is one emitter, so it always trains by model.
    amb, emp = y == "ambient", y == "emp"
    src = ~amb & ~emp

    out = {"T": T, "n_alarm_sources": int((alarm & src).sum()), "n_sources": int(src.sum()),
           "n_alarm_ambient": int((alarm & amb).sum()), "n_ambient": int(amb.sum()),
           "n_alarm_emp": int((alarm & emp).sum()), "n_emp": int(emp.sum()),
           "tests": {}}
    for name in ("blocks", "rooms", "models"):
        res = {"sources_correct": [], "sources_called_ambient": [],
               "sources_called_emp": [], "ambient_alarms_called_ambient": [],
               "emp_alarms_called_emp": []}
        for s in SEEDS:
            if name == "blocks":
                p = train.hold_out(X, y, train.block_folds(y, blocks, s), s)
            elif name == "rooms":
                p = train.hold_out(X, y, rooms, s)
            else:
                p = train.hold_out(X, y, models, s, test=~amb & ~emp)
            tested = np.array([q is not None for q in p])
            m = alarm & src & tested
            res["sources_correct"].append(float(np.mean(p[m] == y[m])))
            res["sources_called_ambient"].append(float(np.mean(p[m] == "ambient")))
            res["sources_called_emp"].append(float(np.mean(p[m] == "emp")))
            if name != "models":          # ambient and emp are never held out as a model
                a = alarm & amb & tested
                if a.any():
                    res["ambient_alarms_called_ambient"].append(float(np.mean(p[a] == "ambient")))
                e = alarm & emp & tested
                if e.any():               # emp is never tested by room: one place
                    res["emp_alarms_called_emp"].append(float(np.mean(p[e] == "emp")))
            print(f"  {name} seed {s}: " + ", ".join(
                f"{k} {v[-1]:.3f}" for k, v in res.items() if v), flush=True)
        out["tests"][name] = res
    with open("analysis/attribution.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"T = {T:.0f}; {out['n_alarm_sources']} of {out['n_sources']} source captures, "
          f"{out['n_alarm_ambient']} of {out['n_ambient']} ambient captures and "
          f"{out['n_alarm_emp']} of {out['n_emp']} emp captures alarm")
    for k, v in out["tests"].items():
        print(f"{k}: " + ", ".join(f"{m} {np.mean(x):.3f} ± {np.std(x):.3f}"
                                    for m, x in v.items() if x))


if __name__ == "__main__":
    main()
