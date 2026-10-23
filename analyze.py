#!/usr/bin/env python3
"""
analyze.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

The amplitude-threshold baseline and the dataset checks.

    python analyze.py

Per capture: depth[i] = rest_ref - value[i], where rest_ref is the resting
level of nearby ambient captures (dataset.py), and A = max depth. T is the
95th percentile of A over
ambient captures, fixed on ambient alone and applied unchanged to every
class. The fraction of a benign class above T is the threshold's false-alarm
rate on that class; no attack class is needed for it. T is also swept.

Writes analysis/summary.md and three figures:
    analysis/amplitude_by_class.png   A per class, with T
    analysis/threshold_sweep.png      alarm rate per class as T moves
    analysis/envelopes_by_class.png   every capture faint; the mean bold if
                                      triggered, else one example
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import dataset  # noqa: E402

OUT = "analysis"
PERCENTILE = 95
SAMPLE_MS = 0.05

# Fixed class -> colour (validated categorical order, light mode). A class
# keeps its colour whatever else is plotted; new classes take the next slot.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
         "#6250d6", "#e34948"]
# Figures group captures by mechanism class (dataset.mechanism), with every
# non-target source as "other": seven groups, so no two share a colour. The
# summary table still lists every appliance label.
CLASS_ORDER = dataset.MECHANISMS + ["other"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def colour(c):
    order = CLASS_ORDER + sorted(set(_seen) - set(CLASS_ORDER))
    return SLOTS[order.index(c) % len(SLOTS)]


_seen = set()


def style(ax):
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
        ax.spines[s].set_linewidth(0.6)
    ax.tick_params(colors=MUTED, labelsize=8, width=0.6)


def per_capture(r):
    # Depth below the circuit's resting level, not below this capture's own
    # median: SecureTrack thresholds the absolute reading, and a source that
    # lowers the whole window (a charger at contact) has no dip below its own
    # median. rest_ref comes from nearby ambient captures (dataset.py).
    v = r["values"].astype(float)
    rest = r.get("rest_ref") or float(np.median(v))
    depth = rest - v
    a = float(depth.max())
    return {
        "A": a,
        "t_max_ms": float(np.argmax(depth)) * SAMPLE_MS,
        "n_cross": int(np.count_nonzero(np.diff((depth > a / 2).astype(int)) == 1)),
        "energy": float(np.sum(np.maximum(depth, 0) ** 2)),
    }


def confounds(records):
    """Lines warning about any condition that one class alone holds."""
    warn, rows = [], []
    labels = sorted({r["label"] for r in records})
    for field in ("power", "room", "device", "distance_cm", "mode"):
        per = {c: Counter(r[field] or "-" for r in records if r["label"] == c)
               for c in labels}
        rows.append((field, per))
        for c in labels:
            vals = set(per[c])
            others = set().union(*(set(per[o]) for o in labels if o != c)) if len(labels) > 1 else set()
            if len(vals) == 1 and field in ("power", "room") and vals.isdisjoint(others):
                warn.append(f"**{c}**: every capture has {field} = `{next(iter(vals))}`, "
                            f"and no other class does. That is a block confound.")
    return warn, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.parse_args()

    records = dataset.load()
    if not records:
        raise SystemExit("no captures found")
    stats = [per_capture(r) for r in records]
    def group(r):
        return dataset.mechanism(r) or "other"
    for r in records:
        # the emitter after its coil burnt: its own table rows only
        r["group"] = "emp_damaged" if r["device"] == "emp_a_damaged" else group(r)
    by_class = defaultdict(list)          # figures: mechanism groups
    by_label = defaultdict(list)          # table: every appliance label
    for r, s in zip(records, stats):
        if r["group"] != "emp_damaged":
            by_class[r["group"]].append(s["A"])
        by_label[r["label"]].append(s["A"])
    _seen.update(by_class)
    classes = [c for c in CLASS_ORDER if c in by_class] + \
        sorted(set(by_class) - set(CLASS_ORDER))
    groups_of = defaultdict(set)           # tv: its back is mains hum, its screen other
    for r in records:
        groups_of[r["label"]].add(r["group"])
    label_group = {l: " / ".join(sorted(g, key=lambda x: CLASS_ORDER.index(x)
                                        if x in CLASS_ORDER else 99))
                   for l, g in groups_of.items()}
    labels = sorted(by_label, key=lambda l: (min(
        CLASS_ORDER.index(g) if g in CLASS_ORDER else 99 for g in groups_of[l]), l))
    if "ambient" not in by_class:
        raise SystemExit("no ambient captures: the threshold is defined on ambient")

    T = float(np.percentile(by_class["ambient"], PERCENTILE))
    alarm = {c: float(np.mean(np.array(by_class[c]) > T)) for c in classes}
    alarm_label = {l: float(np.mean(np.array(by_label[l]) > T)) for l in labels}

    os.makedirs(OUT, exist_ok=True)

    # 1. amplitude by class, threshold drawn across
    fig, ax = plt.subplots(figsize=(6.4, 3.0), dpi=200)
    rng = np.random.default_rng(0)
    for i, c in enumerate(classes):
        a = np.array(by_class[c])
        ax.scatter(i + rng.uniform(-0.18, 0.18, len(a)), a, s=9, color=colour(c),
                   alpha=0.6, linewidths=0, zorder=3)
        ax.plot([i - 0.28, i + 0.28], [np.median(a)] * 2, color=INK, lw=1.4, zorder=4)
    ax.axhline(T, color=INK, lw=0.9, ls=(0, (4, 3)), zorder=2)
    ax.text(-0.45, T, f"T = {T:.0f}", va="bottom", ha="left",
            fontsize=7.5, color=INK)
    ax.set_xticks(range(len(classes)), [c.replace("_", " ") for c in classes], fontsize=8)
    ax.set_ylabel("amplitude A (counts)", fontsize=8, color=MUTED)
    style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "amplitude_by_class.png"))
    plt.close(fig)

    # 2. alarm rate per class as T moves; one shared axis. Six or more
    #    series: a legend, no direct labels (they collide); summary.md is the
    #    table view the low-contrast slots need.
    all_a = np.concatenate([by_class[c] for c in classes])
    sweep = np.linspace(0, np.percentile(all_a, 99.5), 200)
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=200)
    for c in classes:
        a = np.array(by_class[c])
        rate = [(a > t).mean() * 100 for t in sweep]
        ax.plot(sweep, rate, color=colour(c), lw=1.6)
    ax.axvline(T, color=INK, lw=0.9, ls=(0, (4, 3)))
    ax.text(T, 103, f" T = {T:.0f}", fontsize=7.5, color=INK, ha="left", va="bottom")
    ax.set_xlabel("threshold (counts)", fontsize=8, color=MUTED)
    ax.set_ylabel("alarms raised (% of captures)", fontsize=8, color=MUTED)
    ax.set_ylim(0, 112)
    ax.legend(handles=[plt.Line2D([], [], color=colour(c), lw=1.6, label=c.replace("_", " "))
                       for c in classes], fontsize=7, frameon=False,
              loc="upper left", bbox_to_anchor=(1.01, 1.0))
    style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "threshold_sweep.png"))
    plt.close(fig)

    # 3. envelopes by class: small multiples, inverted so a dip is a peak
    n = len(classes)
    fig, axes = plt.subplots(n, 1, figsize=(6.4, 1.05 * n), dpi=200, sharex=True)
    t_ms = np.arange(dataset.N_SAMPLES) * SAMPLE_MS
    for ax, c in zip(np.atleast_1d(axes), classes):
        mine = [r for r in records if r["group"] == c]
        traces = [np.median(r["values"]) - r["values"] for r in mine]
        for tr in traces[:40]:
            ax.plot(t_ms, tr, color=colour(c), lw=0.4, alpha=0.18)
        # A mean only means something when captures are aligned (triggered,
        # event at sample 400); free-running bursts fall anywhere, so their
        # mean is a flat smear. Show one real capture instead.
        aligned = all(r["mode"] == "triggered" for r in mine)
        ax.plot(t_ms, np.mean(traces, axis=0) if aligned else traces[0],
                color=INK, lw=0.8)
        ax.text(1.0, 0.92, f"{c.replace('_', ' ')}  (n={len(traces)}, "
                f"{'mean' if aligned else 'one example'} in black)",
                transform=ax.transAxes, ha="right", va="top", fontsize=7.5, color=INK)
        style(ax)
        ax.tick_params(labelsize=7)
    np.atleast_1d(axes)[-1].set_xlabel("time (ms)", fontsize=8, color=MUTED)
    fig.supylabel("depth below rest (counts)", fontsize=8, color=MUTED)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "envelopes_by_class.png"))
    plt.close(fig)

    warn, rows = confounds(records)
    lines = [
        "# Threshold baseline and dataset checks",
        "",
        f"Captures: {len(records)}.",
        "",
        f"**Threshold T = {T:.0f} counts**: the {PERCENTILE}th percentile of the "
        f"amplitude A = rest_ref − min over {len(by_class['ambient'])} ambient captures, "
        "fixed on ambient alone.",
        "",
        "| class | n | median A | alarm rate at T |",
        "|---|---|---|---|",
    ]
    for c in classes:
        lines.append(f"| {c} | {len(by_class[c])} | {np.median(by_class[c]):.0f} | "
                     f"{alarm[c] * 100:.1f}% |")
    lines += ["", "By appliance label (the class each label maps to in brackets; "
              "\"other\" = recorded but not a classifier target):", "",
              "| label | n | median A | alarm rate at T |", "|---|---|---|---|"]
    for l in labels:
        lines.append(f"| {l} ({label_group[l]}) | {len(by_label[l])} | "
                     f"{np.median(by_label[l]):.0f} | {alarm_label[l] * 100:.1f}% |")
    emp = [(r, s) for r, s in zip(records, stats) if r["label"] == "emp"]
    if emp:
        lines += ["", "Attack captures (the SecureTrack emitter) by device and distance; "
                  "`emp_a_damaged` is the same unit after its coil end burnt, "
                  "`emp_a_repaired` after its coil lead was moved to another hole "
                  "(battery 3.9 V, against 3.3 V for `emp_a`):", "",
                  "| device | distance (cm) | n | median A | alarm rate at T |",
                  "|---|---|---|---|---|"]
        for dev, dist in sorted({(r["device"], r["distance_cm"]) for r, _ in emp},
                                key=lambda k: (k[0], float(k[1] or 0))):
            a = np.array([s["A"] for r, s in emp
                          if (r["device"], r["distance_cm"]) == (dev, dist)])
            lines.append(f"| {dev} | {dist} | {len(a)} | {np.median(a):.0f} | "
                         f"{np.mean(a > T) * 100:.1f}% |")
    lines += [
        "",
        "Every benign class's alarm rate is the amplitude threshold's false-alarm "
        "rate on that class, and the emp rate its detection rate. Ambient sits near "
        f"{100 - PERCENTILE}% by construction.",
        "",
        "## Block-confound check",
        "",
    ]
    lines += [f"- ⚠️ {w}" for w in warn] or ["- No label holds a power or room value alone."]
    lines += [""]
    for field, per in rows:
        lines += [f"### {field}", "", "| label | values |", "|---|---|"]
        for c in labels:
            lines.append(f"| {c} | " + ", ".join(f"{k} ({n})" for k, n in per[c].most_common()) + " |")
        lines.append("")
    lines += ["Figures: `amplitude_by_class.png`, `threshold_sweep.png`, "
              "`envelopes_by_class.png`.", ""]
    with open(os.path.join(OUT, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    sys.stdout.reconfigure(errors="replace")    # cp1252 consoles lack − and —
    print("\n".join(lines[:16 + len(classes) + len(labels)]))
    print(f"wrote {OUT}/summary.md and 3 figures")


if __name__ == "__main__":
    main()
