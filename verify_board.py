#!/usr/bin/env python3
"""
verify_board.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Checks the classifier firmware against the Python pipeline, on the board.
Needs emi_classify/ flashed (NOT the collection firmware).

    python verify_board.py              stratified sample, 15 captures per label
    python verify_board.py --per 40     more per label

For each stored capture it sends `v`, the integer resting reference and the
2000 samples, and reads back the board's 15 features, its logits, its class,
and how long feature extraction and inference took (micros()). The Python
reference is features.py on the same samples and the same rest_ref, run
through the model rebuilt from emi_classify/emi_model.h, the file the board
was compiled with.

Writes analysis/board_check.md and analysis/board_check.json.
"""

import argparse
import json
import re
import time
from collections import Counter, defaultdict

import numpy as np
import serial

import capture       # for the port lookup only
import dataset
import features

HEADER = "emi_classify/emi_model.h"
FEAT_TOL_ABS, FEAT_TOL_REL = 1e-4, 1e-4   # the board prints 6 decimals


def load_header(path=HEADER):
    text = open(path, encoding="utf-8").read()

    def nums(name, cast=float):
        m = re.search(name + r"(?:\[[^\]]*\])*\s*=\s*\{([^;]*)\};", text)
        return np.array([cast(x.strip().rstrip("f")) for x in m.group(1).split(",")])

    def scalar(name):
        return float(re.search(name + r"\s*=\s*([-0-9.eE+]+)f;", text).group(1))

    classes = re.findall(r'"([^"]+)"', re.search(r"EMI_CLASSES\[[^\]]*\]\s*=\s*\{([^}]*)\}",
                                                  text).group(1))
    nf = int(re.search(r"#define EMI_N_FEATURES (\d+)", text).group(1))
    nh = int(re.search(r"#define EMI_N_HIDDEN (\d+)", text).group(1))
    return {
        "classes": classes,
        "log1p": nums("EMI_LOG1P", int).astype(bool),
        "mean": nums("EMI_MEAN"), "scale": nums("EMI_SCALE"),
        "w1": nums("EMI_W1", int).reshape(nf, nh), "s1": scalar("EMI_W1_SCALE"),
        "b1": nums("EMI_B1"),
        "w2": nums("EMI_W2", int).reshape(nh, len(classes)), "s2": scalar("EMI_W2_SCALE"),
        "b2": nums("EMI_B2"),
    }


def reference(m, f):
    x = np.array(f, dtype=np.float64)
    x[m["log1p"]] = np.log1p(np.maximum(x[m["log1p"]], 0))
    z = (x - m["mean"]) / m["scale"]
    h = np.maximum(z @ (m["w1"] * m["s1"]) + m["b1"], 0)
    logits = h @ (m["w2"] * m["s2"]) + m["b2"]
    return logits, m["classes"][int(np.argmax(logits))]


def ask(port, rest_ref, values, timeout=15):
    port.reset_input_buffer()
    port.write(b"v" + f"{rest_ref}\n".encode())
    # Small chunks with pauses: the ESP32's 256-byte serial RX buffer overflows
    # if 100 values (~500 bytes) arrive at once, and the board then waits for
    # numbers that were lost. 20 values per 10 ms works.
    for i in range(0, len(values), 20):
        port.write(("\n".join(str(int(v)) for v in values[i:i + 20]) + "\n").encode())
        port.flush()
        time.sleep(0.01)
    got, t0, seen = {}, time.time(), []
    while time.time() - t0 < timeout:
        line = port.readline().decode(errors="replace").strip()
        if line:
            seen.append(line[:120])
        if line.startswith("VERIFY"):
            got["head"] = dict(kv.split("=", 1) for kv in line.split()[1:])
        elif line.startswith("FEAT") and "head" in got:
            got["feat"] = [float(x) for x in line.split()[1:]]
        elif line.startswith("LOGITS") and "feat" in got:
            got["logits"] = [float(x) for x in line.split()[1:]]
            return got
    raise TimeoutError("no complete VERIFY reply; the board sent: " + repr(seen[-5:]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--per", type=int, default=15, help="captures per label")
    ap.add_argument("--port", default=None)
    args = ap.parse_args()

    model = load_header()
    names = features.FEATURE_NAMES
    if len(model["mean"]) != len(names):
        raise SystemExit(f"{HEADER} has {len(model['mean'])} features, features.py "
                         f"{len(names)}: retrain")
    recs = dataset.load()
    rng = np.random.default_rng(0)
    by_label = defaultdict(list)
    for r in recs:
        by_label[r["label"]].append(r)
    pick = [by_label[lab][i] for lab in sorted(by_label)
            for i in rng.permutation(len(by_label[lab]))[:args.per]]

    port_name = args.port or capture.resolve_port(None)[0]
    port = serial.Serial(port_name, 921600, timeout=1)
    t0 = time.time()
    while time.time() - t0 < 10:                  # opening the port resets the board
        line = port.readline().decode(errors="replace").strip()
        if line.startswith("READY classify"):
            print(line)
            break
    else:
        raise SystemExit("no READY classify line: is emi_classify flashed?")
    time.sleep(0.5)                               # let the board settle in loop()

    rows, feat_bad, class_bad = [], Counter(), 0
    max_diff = np.zeros(len(names))
    logit_diff = 0.0
    for k, r in enumerate(pick):
        rest_ref = int(round(r["rest_ref"]))
        f_py = features.compute(r["values"], rest_ref)
        lg_py, c_py = reference(model, f_py)
        try:
            got = ask(port, rest_ref, r["values"])
        except TimeoutError as exc:               # one retry; the parse resyncs on 'v'
            print(f"  retry {r['path']}: {exc}", flush=True)
            time.sleep(4)                         # outlast the board's 3 s parseInt timeout
            got = ask(port, rest_ref, r["values"])
        f_c = np.array(got["feat"])
        diff = np.abs(f_c - np.array(f_py))
        max_diff = np.maximum(max_diff, diff)
        bad = diff > np.maximum(FEAT_TOL_ABS, FEAT_TOL_REL * np.abs(f_py))
        for j in np.flatnonzero(bad):
            feat_bad[names[j]] += 1
        c_c = got["head"]["class"]
        class_bad += c_c != c_py
        logit_diff = max(logit_diff, float(np.max(np.abs(np.array(got["logits"]) - lg_py))))
        rows.append({"path": r["path"], "label": r["label"],
                     "class_board": c_c, "class_python": c_py,
                     "features_us": int(got["head"]["features_us"]),
                     "model_us": int(got["head"]["model_us"]),
                     "features_off": [names[j] for j in np.flatnonzero(bad)]})
        if (k + 1) % 25 == 0:
            print(f"  {k + 1}/{len(pick)} checked", flush=True)
    port.close()

    fu = np.array([x["features_us"] for x in rows])
    mu = np.array([x["model_us"] for x in rows])
    tot = fu + mu
    summary = {
        "captures": len(rows), "labels": len(by_label),
        "class_agreement": 1 - class_bad / len(rows),
        "features_outside_tolerance": dict(feat_bad),
        "max_abs_feature_diff": dict(zip(names, max_diff.round(6).tolist())),
        "max_abs_logit_diff": logit_diff,
        "features_us": {"median": float(np.median(fu)), "p95": float(np.percentile(fu, 95)),
                        "max": int(fu.max())},
        "model_us": {"median": float(np.median(mu)), "p95": float(np.percentile(mu, 95)),
                     "max": int(mu.max())},
        "total_us": {"median": float(np.median(tot)), "p95": float(np.percentile(tot, 95)),
                     "max": int(tot.max())},
        "rows": rows,
    }
    with open("analysis/board_check.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    per_label = defaultdict(list)
    for x in rows:
        per_label[x["label"]].append(x["features_us"] + x["model_us"])
    out = [
        "# Board check: emi_classify against the Python pipeline", "",
        f"{len(rows)} stored captures ({args.per} per label, {len(by_label)} labels), "
        f"sent over serial with `v`; reference = features.py + the model rebuilt "
        f"from `{HEADER}`.", "",
        f"- **Class agreement: {summary['class_agreement'] * 100:.1f}%** "
        f"({class_bad} disagreements)",
        f"- Features outside tolerance (abs {FEAT_TOL_ABS}, rel {FEAT_TOL_REL}): "
        + (", ".join(f"{k} {v}" for k, v in feat_bad.items()) or "none"),
        f"- Largest logit difference: {logit_diff:.2e}", "",
        "| time on the ESP32 (µs) | median | 95th pct | max |", "|---|---|---|---|",
        f"| features | {np.median(fu):.0f} | {np.percentile(fu, 95):.0f} | {fu.max()} |",
        f"| model | {np.median(mu):.0f} | {np.percentile(mu, 95):.0f} | {mu.max()} |",
        f"| total | {np.median(tot):.0f} | {np.percentile(tot, 95):.0f} | {tot.max()} |", "",
        "Per label, total µs (median): " + ", ".join(
            f"{k} {np.median(v):.0f}" for k, v in sorted(per_label.items())), "",
        "Largest absolute difference per feature: " + ", ".join(
            f"{n} {d:.2g}" for n, d in zip(names, max_diff)), "",
    ]
    with open("analysis/board_check.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
