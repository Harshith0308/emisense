"""
features.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

The per-capture features the classifier uses. Each one is defined so that the
ESP32 can compute exactly the same number from the same 2000 samples: integer
thresholds, a fixed rest percentile, no FFT. The C port must match this file;
if a definition changes here, change it there and re-check on the board.

The output rests high and dips on EMI (the front end inverts), so everything
works on the dip  d[i] = rest - v[i],  where rest is the 90th percentile of
the window: the same rest the firmware's trigger uses.

Two groups, so the contribution of each can be tested:

  MAGNITUDE  how deep and how much: depends on source strength AND distance.
  TEMPORAL   when and how often: event counts, widths, intervals, periodicity.
"""

import numpy as np

N_SAMPLES = 2000
SAMPLE_MS = 0.05               # 20 kSa/s
REST_INDEX = N_SAMPLES * 90 // 100   # 1800: the firmware's nth_element index
EVENT_LEVEL = 150              # an event is d > 150 (the dataset's trigger depth)
STRONG_LEVEL = 400
MERGE_GAP = 10                 # samples; dips closer than 0.5 ms are one event
POOL = 4                       # max-pool before autocorrelation: 0.2 ms per bin
LAG_MIN, LAG_MAX = 10, 250     # pooled bins: 2 ms to 50 ms

FEATURE_NAMES = [
    "max_dip",        # deepest dip, counts
    "mean_dip",       # mean of max(d, 0)
    "act150",         # fraction of samples with d > 150
    "act400",         # fraction of samples with d > 400
    "rough",          # mean |v[i] - v[i-1]|: fine ripple, e.g. a charger's
    "n_events",       # dips above 150, merged if < 0.5 ms apart
    "width_med",      # median event width, samples
    "interval_med",   # median spacing of event starts, samples
    "interval_cv",    # std/mean of those spacings: regular vs irregular
    "ac_peak",        # strongest autocorrelation between 2 and 50 ms (0..1)
    "ac_lag_ms",      # where it is: the repetition period
    "zcr",            # crossings of the window mean, per sample
    "level_drop",     # resting reference minus this window's rest: a steady drop
    # added 19 Oct, after collection, for the mixer/display confusion:
    "lag_fine_ms",    # ac_lag_ms refined to one sample (0.05 ms): a display's
                      # refresh (19.80 ms) from a motor locked to mains (20.0)
    "depth_cv",       # std/mean of the events' peak depths: sparks vary,
                      # display bursts repeat at one depth
]
# Chosen 19 Oct by grouped cross-validation over three seeds against the 13
# features alone and against 17 (these two plus "frag", unmerged runs per
# event, and "spike_frac", one-sample-wide events): this set was best or tied
# on blocks, rooms and models held out, the other two added nothing.
MAGNITUDE = ["max_dip", "mean_dip", "act150", "act400", "rough", "level_drop",
             "depth_cv"]
TEMPORAL = ["n_events", "width_med", "interval_med", "interval_cv",
            "ac_peak", "ac_lag_ms", "zcr", "lag_fine_ms"]


def rest_level(v):
    """90th percentile exactly as the firmware takes it (nth_element at 1800)."""
    return int(np.partition(np.asarray(v), REST_INDEX)[REST_INDEX])


def events(d):
    """Start index and width of each event: runs of d > EVENT_LEVEL, merged
    when separated by MERGE_GAP samples or fewer."""
    above = d > EVENT_LEVEL
    starts, widths = [], []
    last_end = None
    for i, a in enumerate(above):
        if not a:
            continue
        if last_end is not None and i - last_end <= MERGE_GAP:
            widths[-1] += i - last_end      # extend the current event
        else:
            starts.append(i)
            widths.append(1)
        last_end = i
    return starts, widths


def compute(values, rest_ref=None):
    """Feature vector (list of floats, FEATURE_NAMES order) for one capture.

    rest_ref is the circuit's quiet resting level, which every other feature
    ignores because it works inside the window. A source that lowers the whole
    window (a phone charger at contact pins it near the floor) shows up only
    as level_drop = rest_ref - rest. On the board, rest_ref is measured in a
    quiet window at start-up; for the dataset, dataset.py takes it from the
    nearest ambient captures of the same session. Without it, level_drop is 0.
    """
    v = np.asarray(values, dtype=np.int64)
    if len(v) != N_SAMPLES:
        raise ValueError(f"expected {N_SAMPLES} samples, got {len(v)}")
    rest = rest_level(v)
    level_drop = float(rest_ref - rest) if rest_ref is not None else 0.0
    d = rest - v
    dp = np.maximum(d, 0)

    max_dip = float(d.max())
    mean_dip = float(dp.mean())
    act150 = float(np.count_nonzero(d > EVENT_LEVEL)) / N_SAMPLES
    act400 = float(np.count_nonzero(d > STRONG_LEVEL)) / N_SAMPLES
    rough = float(np.abs(np.diff(v)).mean())

    starts, widths = events(d)
    n_events = float(len(starts))
    width_med = float(np.median(widths)) if widths else 0.0
    peaks = np.array([d[s:s + w].max() for s, w in zip(starts, widths)], dtype=np.float64)
    depth_cv = (float(peaks.std() / peaks.mean())
                if len(peaks) >= 2 and peaks.mean() > 0 else 0.0)
    gaps = np.diff(starts) if len(starts) >= 2 else np.array([])
    interval_med = float(np.median(gaps)) if len(gaps) else 0.0
    interval_cv = (float(gaps.std() / gaps.mean())
                   if len(gaps) >= 2 and gaps.mean() > 0 else 0.0)

    pooled = dp.reshape(-1, POOL).max(axis=1).astype(np.float64)
    m = pooled - pooled.mean()
    r0 = float(np.dot(m, m))
    ac_peak, ac_lag = 0.0, 0
    if r0 > 0:
        best = -np.inf
        for k in range(LAG_MIN, LAG_MAX + 1):
            r = float(np.dot(m[:-k], m[k:]))
            if r > best:
                best, ac_lag = r, k
        ac_peak = max(best / r0, 0.0)
    ac_lag_ms = ac_lag * POOL * SAMPLE_MS if ac_peak > 0 else 0.0

    # the same autocorrelation on the unpooled dip, at every lag within one
    # pooled bin of the coarse peak: the period to one sample
    lag_fine_ms = 0.0
    if ac_peak > 0:
        md = dp.astype(np.float64) - dp.mean()
        c = ac_lag * POOL
        best, lag_f = -np.inf, c
        for k in range(c - POOL, c + POOL + 1):
            r = float(np.dot(md[:-k], md[k:]))
            if r > best:
                best, lag_f = r, k
        lag_fine_ms = lag_f * SAMPLE_MS

    centred = v - v.mean()
    zcr = float(np.count_nonzero(np.diff(np.signbit(centred)))) / N_SAMPLES

    return [max_dip, mean_dip, act150, act400, rough, n_events, width_med,
            interval_med, interval_cv, ac_peak, ac_lag_ms, zcr, level_drop,
            lag_fine_ms, depth_cv]
