#!/usr/bin/env python3
"""
train.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Trains the on-device classifier and writes everything the ESP32 needs.

    python train.py                  the paper's classifier: mechanism classes
    python train.py --classes label  one class per appliance label instead
    python train.py --seeds 1        one seed instead of five (quick check)
    python train.py --drop a,b       leave features out (feature ablation)

Classes. By default each capture's class is the physical mechanism of its
source (dataset.mechanism): ambient, spark, switching supply, display,
sparking motor, mains hum, and the attack (emp). Sources that are weak or the only device of their
kind stay out of training; the summary reports what the final model calls
them. --classes label uses the per-appliance labels instead.

Model: log1p on the count-like features, standardisation, then a small MLP
(features -> 32 -> classes, ReLU). Its weights are quantised to int8
(symmetric, one scale per layer); every reported score is the QUANTISED
model's, since that is what runs on the board.

Evaluation never puts captures of one collection block on both sides of a
split: a block of 20 captures taken seconds apart are near-duplicates.

  blocks held out   five folds of whole blocks (the main score)
  rooms held out    each room in turn: the model has never seen that room
  models held out   each source model in turn, every unit of the model
                    together (dataset.model_of); ambient always trains
  ablation          magnitude-only and temporal-only features, blocks held
                    out and at a held-out distance

Each evaluation is repeated over --seeds seeds (fold assignment and network
initialisation); the summary gives the mean and standard deviation.

Outputs:
    analysis/train_summary.md   the tables
    analysis/results.json       the same numbers, for the paper
    emi_classify/emi_model.h    constants for the firmware (seed 0, all data)
"""

import argparse
import json
import os
import warnings
from collections import Counter

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.neural_network import MLPClassifier

import dataset
import features

HIDDEN = 32      # 16 until the attack class; 32 won every test over 3 seeds (23 Oct)
LOG1P = {"max_dip", "mean_dip", "rough", "n_events", "width_med",
         "interval_med", "ac_lag_ms", "lag_fine_ms"}
SEED = 0
FOLDS = 5
HEADER_PATH = "emi_classify/emi_model.h"   # read by the firmware sketch


def transform(X, names):
    X = np.array(X, dtype=np.float64)
    for j, n in enumerate(names):
        if n in LOG1P:
            X[:, j] = np.log1p(np.maximum(X[:, j], 0))
    return X


class QuantisedMLP:
    """Float-trained MLP with int8 weights, run exactly as the C code does."""

    def __init__(self, mean, scale, mlp):
        self.mean, self.scale = mean, scale
        w1, w2 = mlp.coefs_
        b1, b2 = mlp.intercepts_
        self.s1 = float(np.abs(w1).max() / 127) or 1.0
        self.s2 = float(np.abs(w2).max() / 127) or 1.0
        self.q1 = np.clip(np.round(w1 / self.s1), -127, 127).astype(np.int8)
        self.q2 = np.clip(np.round(w2 / self.s2), -127, 127).astype(np.int8)
        self.b1, self.b2 = b1.astype(np.float32), b2.astype(np.float32)
        self.classes = list(mlp.classes_)

    def logits(self, Xt):
        z = (Xt - self.mean) / self.scale
        h = np.maximum(z @ (self.q1.astype(np.float64) * self.s1) + self.b1, 0)
        return h @ (self.q2.astype(np.float64) * self.s2) + self.b2

    def predict(self, Xt):
        return np.array(self.classes)[np.argmax(self.logits(Xt), axis=1)]


def fit(Xt, y, seed=SEED):
    mean = Xt.mean(axis=0)
    scale = Xt.std(axis=0)
    scale[scale == 0] = 1.0
    mlp = MLPClassifier(hidden_layer_sizes=(HIDDEN,), activation="relu",
                        alpha=1e-3, max_iter=4000, random_state=seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        mlp.fit((Xt - mean) / scale, y)
    return QuantisedMLP(mean, scale, mlp)


def block_folds(y, blocks, seed):
    """Fold number per capture: FOLDS folds of whole blocks, stratified."""
    fold = np.empty(len(y), dtype=int)
    split = StratifiedGroupKFold(n_splits=FOLDS, shuffle=True, random_state=seed)
    for k, (_, te) in enumerate(split.split(np.zeros(len(y)), y, blocks)):
        fold[te] = k
    return fold


def hold_out(Xt, y, groups, seed, test=None):
    """Hold each group out in turn and predict it from all the others.
    test: optional mask; only those captures are ever held out (the rest
    always train). Returns predictions, None where never tested."""
    preds = np.full(len(y), None, dtype=object)
    for g in sorted(set(groups)):
        te = groups == g
        if test is not None:
            te &= test
        if not te.any() or len(set(y[~te])) < len(set(y)):
            continue
        preds[te] = fit(Xt[~te], y[~te], seed).predict(Xt[te])
    return preds


def held_out_distance(Xt, y, distances, seed):
    """Train with one distance removed, test on that distance only.

    Only classes recorded at two or more distances take part as test data;
    everything else stays in training. Magnitude changes with distance; if
    identity lives in timing, the temporal features should hold up here.
    Returns (n_test, accuracy, {class: [correct, n]}) pooled over every
    held-out distance.
    """
    multi = {c for c in set(y) if c != "ambient"
             and len({d for d, l in zip(distances, y) if l == c and d}) >= 2}
    correct = total = 0
    per = {}
    for dist in sorted({d for d, l in zip(distances, y) if l in multi and d}, key=float):
        test = np.array([l in multi and d == dist for d, l in zip(distances, y)])
        if not test.any() or len(set(y[~test])) < len(set(y)):
            continue                      # removing it would drop a class
        pred = fit(Xt[~test], y[~test], seed).predict(Xt[test])
        correct += int(np.sum(pred == y[test]))
        total += int(test.sum())
        for c in set(y[test]):
            m = y[test] == c
            k = per.setdefault(str(c), [0, 0])
            k[0] += int(np.sum(pred[m] == c))
            k[1] += int(m.sum())
    return total, (correct / total if total else float("nan")), per


def scores(y, preds, classes):
    ok = np.array([p is not None for p in preds])
    yt, yp = y[ok], preds[ok].astype(str)
    recall = {c: float(np.mean(yp[yt == c] == c)) for c in classes if np.any(yt == c)}
    return {
        "n": int(ok.sum()),
        "accuracy": float(np.mean(yp == yt)),
        "macro_f1": float(f1_score(yt, yp, labels=sorted(set(yt)), average="macro")),
        "balanced_accuracy": float(np.mean(list(recall.values()))),
        "recall": recall,
    }


def write_header(model, names, path, source):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f_ = len(names)
    k = len(model.classes)

    def floats(a):
        return ", ".join(f"{x:.8g}f" for x in np.ravel(a))

    def ints(a):
        return ", ".join(str(int(x)) for x in np.ravel(a))

    lines = [
        "// Generated by train.py. Do not edit; retrain instead.",
        f"// Trained on: {source}",
        "#pragma once",
        "#include <stdint.h>",
        f"#define EMI_N_FEATURES {f_}",
        f"#define EMI_N_HIDDEN {HIDDEN}",
        f"#define EMI_N_CLASSES {k}",
        "static const char *const EMI_CLASSES[EMI_N_CLASSES] = {"
        + ", ".join(f'"{c}"' for c in model.classes) + "};",
        "// 1 = apply log1p before standardising",
        "static const uint8_t EMI_LOG1P[EMI_N_FEATURES] = {"
        + ints([n in LOG1P for n in names]) + "};",
        f"static const float EMI_MEAN[EMI_N_FEATURES] = {{{floats(model.mean)}}};",
        f"static const float EMI_SCALE[EMI_N_FEATURES] = {{{floats(model.scale)}}};",
        "// layer 1: hidden[j] = relu(sum_i x[i] * W1[i][j] * W1_SCALE + B1[j])",
        f"static const float EMI_W1_SCALE = {model.s1:.8g}f;",
        f"static const int8_t EMI_W1[EMI_N_FEATURES][EMI_N_HIDDEN] = {{{ints(model.q1)}}};",
        f"static const float EMI_B1[EMI_N_HIDDEN] = {{{floats(model.b1)}}};",
        f"static const float EMI_W2_SCALE = {model.s2:.8g}f;",
        f"static const int8_t EMI_W2[EMI_N_HIDDEN][EMI_N_CLASSES] = {{{ints(model.q2)}}};",
        f"static const float EMI_B2[EMI_N_CLASSES] = {{{floats(model.b2)}}};",
    ]
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def table(rows, head):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def ms(values, digits=3):
    """'mean ± sd' over seeds (just the value for one seed)."""
    a = np.array([v for v in values if v is not None], dtype=float)
    if len(a) == 0:
        return "—"
    if len(a) == 1:
        return f"{a[0]:.{digits}f}"
    return f"{a.mean():.{digits}f} ± {a.std():.{digits}f}"


def main():
    global HIDDEN
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--classes", choices=("mechanism", "label"), default="mechanism",
                    help="class definition (default: mechanism)")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--drop", default="", help="comma-separated features to leave out")
    ap.add_argument("--out", default="analysis",
                    help="folder for train_summary.md and results.json")
    ap.add_argument("--no-header", action="store_true",
                    help="do not write emi_classify/emi_model.h")
    ap.add_argument("--hidden", type=int, default=None,
                    help=f"hidden units (default {HIDDEN}); for comparisons only")
    args = ap.parse_args()
    if args.hidden:
        HIDDEN = args.hidden
    by = args.classes
    drop = [d for d in args.drop.split(",") if d]
    unknown = set(drop) - set(features.FEATURE_NAMES)
    if unknown:
        raise SystemExit(f"unknown feature(s): {', '.join(sorted(unknown))}")

    everything = dataset.load()
    if not everything:
        raise SystemExit("no captures found")
    cls = dataset.mechanism if by == "mechanism" else (lambda r: r["label"])
    records = [r for r in everything if cls(r)]
    others = [r for r in everything if not cls(r)]

    keep = [j for j, n in enumerate(features.FEATURE_NAMES) if n not in drop]
    names = [features.FEATURE_NAMES[j] for j in keep]
    magnitude = [n for n in features.MAGNITUDE if n in names]
    temporal = [n for n in features.TEMPORAL if n in names]

    def feats(rs):
        X = np.array([features.compute(r["values"], r.get("rest_ref")) for r in rs])
        return transform(X[:, keep], names)

    Xt = feats(records)
    y = np.array([cls(r) for r in records])
    classes = [c for c in dataset.MECHANISMS if c in set(y)] if by == "mechanism" \
        else sorted(set(y))
    blocks = np.array([r["block"] for r in records])
    rooms = np.array([r["room"] for r in records])
    models = np.array([dataset.model_of(r) for r in records])
    distances = [r["distance_cm"].strip() for r in records]
    devices = np.array([r["device"] for r in records])
    seeds = list(range(args.seeds))
    # Classes with nothing to hold out by model: ambient, and the attack (one
    # emitter). They always train in the held-out-model test.
    always = np.isin(y, ["ambient", "emp"])

    # Attack detection. The threshold baseline is analyze.py's: T is the 95th
    # percentile of A = rest_ref - min over ambient. The classifier alarms when
    # it predicts emp.
    attack = "emp" in classes
    amp = np.array([(r.get("rest_ref") or float(np.median(r["values"])))
                    - float(r["values"].min()) for r in records])
    T = float(np.percentile(amp[y == "ambient"], 95))
    benign_src = (y != "emp") & (y != "ambient")
    emp_dists = sorted({d for d, l in zip(distances, y) if l == "emp"}, key=float)
    det = []
    # The emitter after its burnt coil lead was moved to another hole (23 Oct
    # evening): in the emp class, and also tested as a state never trained on.
    unseen = (y == "emp") & (devices == "emp_a_repaired")
    unseen_dists = sorted(set(np.array(distances)[unseen]), key=float)
    det_unseen = []

    runs = {"blocks": [], "rooms": [], "models": []}
    ablation = {t: {"blocks": [], "distance": []} for t in
                ("all features", "magnitude only", "temporal only")}
    per_model = {}
    cm_sum = np.zeros((len(classes), len(classes)), dtype=int)
    for s in seeds:
        folds = block_folds(y, blocks, s)
        p = hold_out(Xt, y, folds, s)
        runs["blocks"].append(scores(y, p, classes))
        cm_sum += confusion_matrix(y, p.astype(str), labels=classes)
        ablation["all features"]["blocks"].append(runs["blocks"][-1])
        if attack:
            ok = np.array([q is not None for q in p])
            called = (p == "emp") & ok
            det.append({
                "detection": float(called[(y == "emp") & ok].mean()),
                "false_alarm_sources": float(called[benign_src & ok].mean()),
                "false_alarm_ambient": float(called[(y == "ambient") & ok].mean()),
                "per_class": {c: float(called[(y == c) & ok].mean())
                              for c in classes if c != "emp"},
                "by_distance": {d: float(called[(y == "emp") & ok & (np.array(distances) == d)].mean())
                                for d in emp_dists},
            })
        if attack and unseen.any():
            pu = fit(Xt[~unseen], y[~unseen], s).predict(Xt[unseen])
            du = np.array(distances)[unseen]
            det_unseen.append({"detection": float(np.mean(pu == "emp")),
                               "by_distance": {d: float(np.mean(pu[du == d] == "emp"))
                                               for d in unseen_dists}})
        runs["rooms"].append(scores(y, hold_out(Xt, y, rooms, s), classes))
        p = hold_out(Xt, y, models, s, test=~always)
        runs["models"].append(scores(y, p, classes))
        for mdl in sorted(set(models[~always])):
            m = models == mdl
            per_model.setdefault(mdl, {"class": str(y[m][0]), "n": int(m.sum()),
                                       "acc": [], "pred": Counter()})
            per_model[mdl]["acc"].append(float(np.mean(p[m] == y[m])))
            per_model[mdl]["pred"].update(p[m].astype(str))
        for title, subset in (("all features", names),
                              ("magnitude only", magnitude),
                              ("temporal only", temporal)):
            idx = [names.index(n) for n in subset]
            if title != "all features":
                pa = hold_out(Xt[:, idx], y, folds, s)
                ablation[title]["blocks"].append(scores(y, pa, classes))
            ablation[title]["distance"].append(
                held_out_distance(Xt[:, idx], y, distances, s))
        print(f"  seed {s}: blocks {runs['blocks'][-1]['accuracy']:.3f}, "
              f"rooms {runs['rooms'][-1]['accuracy']:.3f}, "
              f"models {runs['models'][-1]['accuracy']:.3f}", flush=True)

    final = fit(Xt, y, SEED)
    src = f"{len(y)} dataset captures, {by} classes"
    if not args.no_header:
        write_header(final, names, HEADER_PATH, src)
    other_pred = {}
    if others:
        po = final.predict(feats(others))
        for r, c in zip(others, po):
            key = r["device"] if r["device"] == "emp_a_damaged" else r["label"]
            other_pred.setdefault(key, Counter())[str(c)] += 1

    thr = {}
    if attack:
        thr = {"T": T,
               "detection": float(np.mean(amp[y == "emp"] > T)),
               "false_alarm_sources": float(np.mean(amp[benign_src] > T)),
               "false_alarm_ambient": float(np.mean(amp[y == "ambient"] > T)),
               "per_class": {c: float(np.mean(amp[y == c] > T)) for c in classes if c != "emp"},
               "by_distance": {d: float(np.mean(amp[(y == "emp") & (np.array(distances) == d)] > T))
                               for d in emp_dists},
               "emitter_unseen": float(np.mean(amp[unseen] > T)) if unseen.any() else None}
    emp_unseen = [d[2].get("emp", [0, 0]) for d in ablation["all features"]["distance"]]

    def col(key, metric):
        return ms([r[metric] for r in runs[key]])

    per_class = {c: {"n": int(np.sum(y == c)),
                     "devices": sorted({r["device"] for r, l in zip(records, y) if l == c}),
                     "models": sorted({dataset.model_of(r) for r, l in zip(records, y) if l == c}),
                     "rooms": len({r["room"] for r, l in zip(records, y) if l == c})}
                 for c in classes}
    results = {
        "captures": len(y), "classes_by": by, "features": names, "seeds": len(seeds),
        "per_class": per_class,
        "evaluations": {k: {m: [r[m] for r in v] for m in
                            ("n", "accuracy", "macro_f1", "balanced_accuracy")}
                        | {"recall": {c: [r["recall"].get(c) for r in v] for c in classes}}
                        for k, v in runs.items()},
        "per_model": {k: {"class": v["class"], "n": v["n"], "acc": v["acc"],
                          "pred": dict(v["pred"])} for k, v in per_model.items()},
        "ablation": {t: {"count": len(names) if t == "all features" else
                         len(magnitude) if t == "magnitude only" else len(temporal),
                         "blocks_accuracy": [r["accuracy"] for r in v["blocks"]],
                         "blocks_macro_f1": [r["macro_f1"] for r in v["blocks"]],
                         "distance_accuracy": [d[1] for d in v["distance"]],
                         "distance_n": v["distance"][0][0]}
                     for t, v in ablation.items()},
        "confusion_blocks_summed_over_seeds": {"labels": classes, "matrix": cm_sum.tolist()},
        "unused_sources_as_classified": {k: dict(v) for k, v in other_pred.items()},
        "attack": ({"threshold": thr, "classifier_blocks": det,
                    "classifier_emp_unseen_distance": [
                        (c / n if n else None) for c, n in emp_unseen],
                    "emp_unseen_distance_n": emp_unseen[0][1] if emp_unseen else 0,
                    "classifier_emitter_unseen": det_unseen,
                    "emitter_unseen_n": int(unseen.sum())}
                   if attack else None),
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)

    seed_note = (f"mean ± standard deviation over {len(seeds)} seeds"
                 if len(seeds) > 1 else "one seed")
    out = [
        "# Classifier summary",
        "",
        f"Captures: {len(y)} in {len(classes)} {by} classes"
        + (f"; {len(others)} more from sources that are not classifier targets."
           if others else "."),
        "",
        table([(c, per_class[c]["n"],
                len(per_class[c]["devices"]) if c != "ambient" else "—",
                len(per_class[c]["models"]) if c != "ambient" else "—",
                per_class[c]["rooms"]) for c in classes],
              ["class", "captures", "devices", "models", "rooms"]),
        "",
        f"Model: {len(names)} features -> {HIDDEN} hidden (ReLU) -> {len(classes)}, "
        f"int8 weights. Scores are the quantised model's, {seed_note}."
        + (f" Features left out: {', '.join(drop)}." if drop else ""),
        "",
        "## Generalisation",
        "",
        table([("blocks held out (5 folds)", col("blocks", "n"), col("blocks", "accuracy"),
                col("blocks", "macro_f1"), col("blocks", "balanced_accuracy")),
               ("rooms held out", col("rooms", "n"), col("rooms", "accuracy"),
                col("rooms", "macro_f1"), col("rooms", "balanced_accuracy")),
               ("models held out (ambient and emp train)", col("models", "n"),
                col("models", "accuracy"), col("models", "macro_f1"),
                col("models", "balanced_accuracy"))],
              ["test", "n", "accuracy", "macro F1", "balanced accuracy"]),
        "",
        "## Recall per class",
        "",
        table([(c, ms([r["recall"].get(c) for r in runs["blocks"]], 2),
                ms([r["recall"].get(c) for r in runs["rooms"]], 2),
                ms([r["recall"].get(c) for r in runs["models"]], 2)
                if c not in ("ambient", "emp") else "—")
               for c in classes],
              ["class", "blocks held out", "rooms held out", "models held out"]),
        "",
        "## Each source model held out",
        "",
        table([(k, v["class"], v["n"], ms(v["acc"], 2),
                ", ".join(f"{c} {n}" for c, n in v["pred"].most_common(3)))
               for k, v in sorted(per_model.items(), key=lambda kv: (kv[1]["class"], kv[0]))],
              ["model", "class", "n", "accuracy", f"predicted (summed over {len(seeds)} seeds)"]),
        "",
        "## Ablation: magnitude against timing",
        "",
        table([(t, results["ablation"][t]["count"],
                ms([r["accuracy"] for r in v["blocks"]]),
                ms([r["macro_f1"] for r in v["blocks"]]),
                ms([d[1] for d in v["distance"]]) + f" (n={v['distance'][0][0]})")
               for t, v in ablation.items()],
              ["features", "count", "accuracy, blocks held out", "macro F1",
               "accuracy at a held-out distance"]),
        "",
        "Magnitude: " + ", ".join(magnitude) + ". Temporal: " + ", ".join(temporal) + ". "
        "The last column trains with one distance removed and tests only on "
        "that distance, for every class recorded at two or more distances.",
        "",
    ]
    if attack:
        pct = lambda v: ms([x * 100 for x in v], 1) + "%"      # noqa: E731
        out += [
            "## Attack detection",
            "",
            f"Amplitude threshold T = {T:.0f} counts (95th percentile of A = rest_ref - min "
            "over ambient, as in analyze.py); the classifier alarms when it predicts emp. "
            "The attack is one emitter recorded in one place, so emp is never held out by "
            "room or by model; its distance can be held out.",
            "",
            table([("amplitude threshold", f"{thr['detection'] * 100:.1f}%",
                    f"{thr['false_alarm_sources'] * 100:.1f}%",
                    f"{thr['false_alarm_ambient'] * 100:.1f}%"),
                   ("classifier, blocks held out", pct([d["detection"] for d in det]),
                    pct([d["false_alarm_sources"] for d in det]),
                    pct([d["false_alarm_ambient"] for d in det])),
                   ("classifier, emp at an unseen distance",
                    pct([c / n for c, n in emp_unseen if n]) +
                    f" (n={emp_unseen[0][1] if emp_unseen else 0})", "—", "—")]
                  + ([("classifier, re-seated emitter never trained on",
                       pct([d["detection"] for d in det_unseen]) + f" (n={int(unseen.sum())})",
                       "—", "—"),
                      ("amplitude threshold, re-seated emitter",
                       f"{thr['emitter_unseen'] * 100:.1f}%", "—", "—")]
                     if det_unseen else []),
                  ["method", "detects the attack", "false alarms, benign sources",
                   "false alarms, ambient"]),
            "",
            table([(d + " cm", int(np.sum((y == "emp") & (np.array(distances) == d))),
                    f"{thr['by_distance'][d] * 100:.1f}%",
                    pct([x["by_distance"][d] for x in det]))
                   for d in emp_dists],
                  ["emp distance", "n", "threshold detects", "classifier detects (blocks)"]),
            "",
        ]
        if det_unseen:
            out += [table([(d + " cm", int(np.sum(unseen & (np.array(distances) == d))),
                            pct([x["by_distance"][d] for x in det_unseen]))
                           for d in unseen_dists],
                          ["re-seated emitter, distance", "n",
                           "classifier detects (never trained on it)"]), ""]
        out += [
            table([(c, f"{thr['per_class'][c] * 100:.1f}%",
                    pct([x["per_class"][c] for x in det]))
                   for c in classes if c != "emp"],
                  ["class", "threshold alarms", "classifier calls it emp (blocks)"]),
            "",
        ]
        if other_pred:
            out += [table([(k, sum(v.values()),
                            f"{100 * v.get('emp', 0) / sum(v.values()):.1f}%")
                           for k, v in sorted(other_pred.items())],
                          ["never trained on (final model)", "n", "called emp"]), ""]
    out += [
        "## Confusion matrix, blocks held out "
        f"(rows true, columns predicted; summed over {len(seeds)} seeds)",
        "",
        table([[c] + list(r) for c, r in zip(classes, cm_sum)], ["true \\ pred"] + classes),
        "",
    ]
    if other_pred:
        out += ["## Sources outside the classes, as the final model calls them", "",
                table([(k, sum(v.values()), ", ".join(f"{c} {n}" for c, n in v.most_common(3)))
                       for k, v in sorted(other_pred.items())],
                      ["label", "n", "predicted"]), ""]
    with open(os.path.join(args.out, "train_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("\n".join(out))
    print(f"wrote {args.out}/train_summary.md and results.json"
          + ("" if args.no_header else " and emi_classify/emi_model.h"))


if __name__ == "__main__":
    main()
