"""
dataset.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Loads captures written by capture.py. Dataset captures are every file whose
label does not start with a diagnostic prefix.
"""

import csv
import glob
import os
from datetime import datetime

import numpy as np

DIAG_PREFIXES = ("diag_", "diag2_", "check11_", "noRB_", "test_", "windowtest_")
N_SAMPLES = 2000


# Classifier classes are the physical mechanism behind a source (decided
# 19 Oct, after collection). Files keep their per-appliance labels; this maps
# them. A source is a classifier target only if its mechanism has two or more
# devices that showed the signature clearly in their sessions (see
# docs/DATASET.md), so every class can be tested on a device it never saw.
MECHANISM = {
    "ambient": "ambient",
    "lighter": "spark",                # piezo igniters: one isolated spike
    "charger": "switching_supply",     # level drop plus kHz ripple
    "adapter": "switching_supply",     # the router's adapter reads like a charger
    "phone_screen": "display",         # refresh-locked bursts, coil on the glass
    "mixer": "sparking_motor",         # commutator sparks on the mains half-cycle
    "console": "mains_hum",            # 50/100 Hz from big mains power supplies
    "grinder": "mains_hum",
    "airfryer": "mains_hum",
    "emp": "emp",                      # the SecureTrack emitter, 22-23 Oct
}
# Recorded and kept, but not classifier targets (None), with the reason:
#   amplifier, vacuum, tv_c, router   weak: barely above the room
#   whisk      a motor tone, unlike the mixers' sparks; one device
#   speaker    one device (the Echo Dot); the other speakers were silent
#   purifier   a 1 ms pulse train; one device
#   tv_a on its screen   a backlight tone; one device
#   emp_a_damaged  the emitter after its coil end burnt (23 Oct): kept out of
#              training, reported separately
# emp_a_repaired (the same unit after its burnt coil lead was moved to another
# hole, 23 Oct evening) is in the emp class; train.py also tests it as an
# emitter state never trained on.
MECHANISMS = ["ambient", "spark", "switching_supply", "display",
              "sparking_motor", "mains_hum", "emp"]

# Units of one model, held out together in the held-out-model test.
# charger_c's wattage was never read, so it is grouped with the other Apple
# charger to be safe.
SAME_MODEL = {
    "charger_b": "samsung_45w", "charger_d": "samsung_45w",
    "charger_c": "apple_charger", "charger_e": "apple_charger",
    "charger_f": "apple_charger",      # Apple 20 W, the same model as charger_e
}


def mechanism(r):
    """Classifier class of a record, or None if it is not a target."""
    if r["device"] == "emp_a_damaged":
        return None
    if r["label"] == "tv":
        # tv_a 2 cm from its back by the power cord: the supply's mains hum
        return "mains_hum" if (r["device"], r["distance_cm"]) == ("tv_a", "2") else None
    return MECHANISM.get(r["label"])


def model_of(r):
    return SAME_MODEL.get(r["device"], r["device"])


def read_csv(path):
    """(header dict, int sample array) for one capture file."""
    header, values = {}, []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if row[0].startswith("#"):
                header[row[0].lstrip("# ").strip()] = row[1] if len(row) > 1 else ""
            elif row[0] != "sample_index":
                values.append(int(row[2]))
    return header, np.array(values, dtype=np.int64)


def load(pattern="data/*.csv"):
    """List of capture records: dict with label, batch, values and header."""
    records, skipped = [], 0
    for path in sorted(glob.glob(pattern)):
        header, values = read_csv(path)
        batch = header.get("label", os.path.basename(path).rsplit("_", 3)[0])
        diag = batch.startswith(DIAG_PREFIXES) or \
            batch in {p.rstrip("_") for p in DIAG_PREFIXES}     # plain "test"
        label = None if diag else batch
        if label is None:
            continue
        if len(values) != N_SAMPLES or values.min() < 0 or values.max() > 4095:
            skipped += 1          # damaged on the serial link; never use
            continue
        records.append({
            "path": path,
            "label": label,
            "batch": batch,
            "values": values,
            "mode": header.get("mode", ""),
            "power": header.get("power", "unknown"),
            "room": header.get("room", ""),
            "distance_cm": header.get("distance_cm", ""),
            "device": header.get("device", ""),
            "note": header.get("note", ""),
            "captured_at": header.get("captured_at", ""),
            "time_of_day": header.get("time_of_day", ""),
            "resting": header.get("resting", ""),
            "trig_depth": header.get("trig_depth", ""),
        })
    if skipped:
        print(f"  skipped {skipped} damaged capture(s)")
    attach_rest_refs(records)
    attach_blocks(records)
    return records


def attach_blocks(records, gap_s=60):
    """Number the collection blocks: a run of captures with the same label,
    device, distance and note, none more than gap_s after the previous one.
    Captures in a block are seconds apart and near-duplicates, so evaluation
    must keep each block whole on one side of a split."""
    order = sorted(range(len(records)),
                   key=lambda i: (_when(records[i]) or datetime.min, records[i]["path"]))
    block, prev = -1, None
    for i in order:
        r, t = records[i], _when(records[i])
        sig = (r["label"], r["device"], r["distance_cm"], r["note"], r["batch"])
        if prev is None or sig != prev[0] or t is None or prev[1] is None \
                or (t - prev[1]).total_seconds() > gap_s:
            block += 1
        r["block"] = block
        prev = (sig, t)


def _when(r):
    try:
        return datetime.fromisoformat(r["captured_at"])
    except (KeyError, ValueError):
        return None


def attach_rest_refs(records, k=20):
    """Give each record r["rest_ref"], the circuit's quiet resting level near
    that moment: the median rest of the k ambient captures closest in time
    within the same session (date and room), else of all ambient captures.

    The resting level drifts slowly (1975 -> 2025 over the 16 Oct session), so
    one reference for the whole dataset would blur small steady drops."""
    import features                       # local: features does not import us
    amb = [(r, features.rest_level(r["values"])) for r in records
           if r["label"] == "ambient"]
    if not amb:
        for r in records:
            r["rest_ref"] = None
        return
    everything = float(np.median([rest for _, rest in amb]))
    for r in records:
        t = _when(r)
        key = (r["captured_at"][:10], r["room"])
        # Never reference a capture against its own block (taken within the
        # same couple of minutes): ambient would then read a perfect zero.
        near = [(a, rest) for a, rest in amb
                if (a["captured_at"][:10], a["room"]) == key and _when(a) and t
                and abs((_when(a) - t).total_seconds()) > 120]
        if not near:
            r["rest_ref"] = everything
            continue
        near.sort(key=lambda ar: abs((_when(ar[0]) - t).total_seconds()))
        r["rest_ref"] = float(np.median([rest for _, rest in near[:k]]))
