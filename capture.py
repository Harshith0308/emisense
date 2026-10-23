#!/usr/bin/env python3
"""
capture.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Triggers one or more captures on the ESP32, saves each as a labelled CSV,
and plots them.

Usage:
    python capture.py <label> [-n N] [--no-plot] [--delay SEC] [--port PORT]
                              [--trigger [DEPTH]]

    python capture.py ambient              one capture, plot window shown
    python capture.py lighter --n 20       20 in a row, PNGs written, no windows
    python capture.py phone --n 50 --no-plot --delay 2
    python capture.py lighter --trigger --n 20 --no-plot

Two capture modes:

  free (default)  capture 100 ms the moment the command is sent. For
                  continuous sources and ambient. Use --delay to give
                  yourself time to start the source; a countdown is printed.

  --trigger       the board arms, waits for the output to dip DEPTH counts
                  below rest (default 300), and saves the 100 ms around it
                  with the dip at sample 400. For events -- lighter, relay,
                  switch-on, plug-in -- whose few milliseconds a human
                  countdown would usually miss. Gives up after 30 s.

A batch keeps the serial port open throughout, so the ESP32 is not reset
between captures.

Requirements:
    pip install pyserial numpy matplotlib

Serial port, in priority order:
    1. --port COM3
    2. the EMI_PORT environment variable
    3. config.local.ini next to this script:

           [serial]
           port = COM3

Copy config.example.ini to config.local.ini and edit it. That file is
gitignored, so each laptop keeps its own port. Running with no port
configured prints these instructions and exits.

"""

import argparse
import configparser
import os
import subprocess
import sys
import time
import csv
from datetime import datetime

import serial
import numpy as np
import matplotlib.pyplot as plt

BAUD = 921600
CONFIG_FILE = "config.local.ini"

# Collection conditions written into every CSV header. "unknown" is a real
# value, not a missing one: it says nobody recorded the power state, which
# is exactly the thing that makes a block confound undetectable later.
CONDITION_DEFAULTS = {"power": "unknown", "room": "", "distance_cm": "",
                      "device": "", "note": ""}
OUTDIR = "data"

# The front end INVERTS: a common-emitter stage pulls the collector down on a
# positive input and the 1N4148 catches that downward swing, so the output
# rests HIGH and DIPS on EMI. Collector at ~0.9-2.0 V (gain dependent) plus a
# ~0.6 V diode drop is ~1.5-2.6 V, which is roughly 1800-3200 of 4095.
RESTING_MIN = 1800
RESTING_MAX = 3200

# The sketch schedules samples INTERVAL_US apart, but analogRead() on the
# ESP32 can be too slow to keep up. If it falls behind, elapsed_us grows and
# the real sampling rate is not the one the paper claims. Anything past this
# fraction of the expected elapsed time is reported loudly.
TIMING_TOLERANCE = 0.05          # 5 percent


def resolve_port(cli_port=None):
    """Work out which serial port to use, or explain how to set one.

    Priority: --port, then the EMI_PORT environment variable, then
    config.local.ini next to this script. The port used to be hardcoded
    here, which meant four laptops editing the same line and colliding
    every time the file was shared.

    Returns (port, where_it_came_from). Exits with instructions if unset.
    """
    if cli_port:
        return cli_port, "--port"

    env_port = os.environ.get("EMI_PORT", "").strip()
    if env_port:
        return env_port, "EMI_PORT"

    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(here, CONFIG_FILE)
    if os.path.exists(cfg_path):
        parser = configparser.ConfigParser()
        try:
            parser.read(cfg_path, encoding="utf-8")
            file_port = parser.get("serial", "port", fallback="").strip()
        except configparser.Error as exc:
            print(f"could not read {CONFIG_FILE}: {exc}")
            file_port = ""
        if file_port:
            return file_port, CONFIG_FILE

    print("No serial port configured. Do any one of these:")
    print()
    print(f"  1. Copy config.example.ini to {CONFIG_FILE} and edit it:")
    print()
    print("       [serial]")
    print("       port = COM3")
    print()
    print(f"     {CONFIG_FILE} is gitignored, so everyone keeps their own port")
    print("     and nobody's edit lands on anybody else.")
    print()
    print("  2. Set an environment variable:")
    print("       PowerShell:     $env:EMI_PORT = 'COM3'")
    print("       Linux / macOS:  export EMI_PORT=/dev/ttyUSB0")
    print()
    print("  3. Pass it on the command line:")
    print("       python capture.py ambient --port COM3")
    print()
    print("Find the port in Arduino IDE under Tools > Port.")
    print("  Windows  COM3, COM4, ...")
    print("  Linux    /dev/ttyUSB0 or /dev/ttyACM0")
    print("  macOS    /dev/cu.usbserial-0001")
    sys.exit(1)


def detect_power():
    """Return "charger" or "battery" as Windows reports it, or None.

    The --power flag is easy to forget or to leave stale: on 16 Oct three
    pilot runs were labelled "charger" while the laptop had been unplugged.
    Win32_Battery.BatteryStatus 1, 4 and 5 mean discharging; 2, 3 and 6-9 mean
    the charger is connected. Anything else, or no battery, is None.
    """
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Battery).BatteryStatus"],
            capture_output=True, text=True, timeout=15).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out or not out[0].isdigit():
        return None
    status = int(out[0])
    if status in (1, 4, 5):
        return "battery"
    if status in (2, 3, 6, 7, 8, 9):
        return "charger"
    return None


def _status_fields(line):
    """'ARMED resting=4095 trig_level=3795' -> {'resting': '4095', ...}"""
    return dict(part.split("=", 1) for part in line.split()[1:] if "=" in part)


def read_capture(ser, timeout_s=15, command=b"g"):
    """Trigger one capture and return (samples, metadata).

    command b"g" captures immediately. b"t" or b"t<depth>" arms the board's
    triggered mode: it replies ARMED, waits for the output to dip, and sends
    the capture, or replies TIMEOUT if nothing fires within its 30 s window.
    On a timeout the samples are empty and meta["timeout"] is set. Lines
    received before BEGIN that are not ARMED or TIMEOUT are kept in
    meta["stray"], so a capture that never arrives can be diagnosed.
    """
    ser.reset_input_buffer()
    ser.write(command)

    values = []
    meta = {}
    stray = []
    started = False
    t_start = time.time()

    while time.time() - t_start < timeout_s:
        raw = ser.readline().decode("utf-8", errors="ignore").strip()
        if not raw:
            continue
        if raw.startswith("ARMED"):
            meta["armed"] = raw
            f = _status_fields(raw)
            print(f"  armed: resting {f.get('resting', '?')}, fires below "
                  f"{f.get('trig_level', '?')}  -> trigger the source now")
            continue
        if raw.startswith("TIMEOUT"):
            meta["timeout"] = raw
            break
        if raw == "BEGIN":
            started = True
            continue
        if raw == "END":
            break
        if not started:
            stray.append(raw)
            continue
        if raw.startswith("#"):
            body = raw.lstrip("# ").strip()
            if "=" in body:
                k, v = body.split("=", 1)
                meta[k.strip()] = v.strip()
            continue
        try:
            values.append(int(raw))
        except ValueError:
            pass

    if stray:
        meta["stray"] = stray
    return np.array(values), meta


def check_timing(meta, announce_ok=True):
    """Warn if the board did not actually sustain the requested sampling rate.

    Both build guides say to confirm elapsed_us is close to
    N_SAMPLES * INTERVAL_US. Nothing enforced it, so a board quietly
    sampling at 12 kSa/s would have been written up as 20 kSa/s.

    Returns True only if the timing was checked and is within tolerance.
    """
    try:
        n = int(meta["samples"])
        interval_us = float(meta["interval_us"])
        elapsed_us = float(meta["elapsed_us"])
    except (KeyError, ValueError, TypeError):
        print("  WARNING: no timing metadata in this capture.")
        print("           Sampling rate unverified - is the sketch up to date?")
        return False

    expected_us = n * interval_us
    if expected_us <= 0 or elapsed_us <= 0:
        print("  WARNING: timing metadata makes no sense, sampling rate unverified.")
        return False

    deviation = (elapsed_us - expected_us) / expected_us
    actual_khz = n / elapsed_us * 1000.0
    target_khz = 1000.0 / interval_us

    if abs(deviation) > TIMING_TOLERANCE:
        print("  WARNING: the board is not sampling at the rate the sketch asked for.")
        print(f"           target {target_khz:.1f} kSa/s, actual {actual_khz:.1f} kSa/s "
              f"({deviation * 100:+.1f}% on elapsed time)")
        print(f"           elapsed_us={elapsed_us:.0f}, expected {expected_us:.0f}")
        print("           analogRead() cannot keep up. Raise INTERVAL_US in")
        print("           emi_capture.ino (100 gives 10 kSa/s) and note the change.")
        print("           The sampling rate is a claim the paper makes, so it has to")
        print("           be the rate actually achieved, not the one requested.")
        return False

    if announce_ok:
        print(f"  timing OK   {actual_khz:.1f} kSa/s "
              f"({deviation * 100:+.1f}% vs {target_khz:.0f} kSa/s target)")
    return True


def check_signal(values):
    """Warn about a capture that does not look like a working front end.

    The output rests high and dips on EMI, so the failure modes are not the
    ones you would expect from a non-inverting stage. In particular, pinned
    at 4095 means the diode is backwards, NOT that the transistor is
    saturated. Saturation is a bias fault and shows up as the collector
    sitting at 0 V on a multimeter, which this data cannot see.

    Returns True if the capture looks usable.
    """
    lo, hi = int(values.min()), int(values.max())
    resting = float(np.median(values))
    span = hi - lo

    if lo >= 4000:
        print("  WARNING: pinned at the top of the range.")
        print("           The diode is backwards, or nothing is connected to GPIO34.")
        print("           The 1N4148 band goes at the COLLECTOR, hole C10.")
        print("           This is NOT saturation - do not change R_B.")
        return False

    if hi <= 5:
        print("  WARNING: flat near zero. This is a bias fault, not an envelope fault.")
        print("           Measure the collector at C10 with a multimeter (check 6):")
        print("             near 0 V   -> saturated, raise R_B to 2.2M")
        print("             near 3.3 V -> not conducting, BC548 legs reversed")
        return False

    if span <= 2:
        print("  WARNING: no variation at all across the whole capture.")
        print("           Usually the coil enamel is not scraped through.")
        print("           Check continuity across the two coil leads (check 7).")
        return False

    if not RESTING_MIN <= resting <= RESTING_MAX:
        print(f"  NOTE: resting value {resting:.0f} is outside the expected "
              f"{RESTING_MIN}-{RESTING_MAX}.")
        print("        Not necessarily wrong, but confirm the collector sits at 0.9-2.0 V.")

    return True


def save_csv(label, values, meta, conditions=None):
    os.makedirs(OUTDIR, exist_ok=True)
    now = datetime.now()
    # Millisecond resolution, not seconds: a batch can finish two captures
    # inside the same second and a seconds-only stamp silently overwrites
    # the earlier one. The loop below is the belt to that braces -- under no
    # circumstances should a capture destroy data already on disk.
    stamp = now.strftime("%Y%m%d_%H%M%S_") + f"{now.microsecond // 1000:03d}"
    path = os.path.join(OUTDIR, f"{label}_{stamp}.csv")
    dedupe = 1
    while os.path.exists(path):
        path = os.path.join(OUTDIR, f"{label}_{stamp}_{dedupe}.csv")
        dedupe += 1

    interval_us = float(meta.get("interval_us", 50))

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# label", label])
        for k, v in meta.items():
            w.writerow([f"# {k}", v])

        # Collection conditions, so a block confound can be detected later
        # instead of being remembered. See docs/DATASET.md.
        w.writerow(["# captured_at", now.isoformat(timespec="seconds")])
        w.writerow(["# time_of_day", now.strftime("%H:%M")])
        cond = dict(CONDITION_DEFAULTS, **(conditions or {}))
        for key in CONDITION_DEFAULTS:
            w.writerow([f"# {key}", cond[key]])
        w.writerow(["sample_index", "time_ms", "adc_value"])
        for i, v in enumerate(values):
            w.writerow([i, round(i * interval_us / 1000.0, 4), int(v)])

    return path


def plot(label, values, meta, path, show=True):
    interval_us = float(meta.get("interval_us", 50))
    t_ms = np.arange(len(values)) * interval_us / 1000.0

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(t_ms, values, linewidth=0.6)
    ax.set_xlabel("time (ms)")
    ax.set_ylabel("ADC value (0-4095)")
    ax.set_title(
        f"{label}   |   n={len(values)}   "
        f"mean={values.mean():.1f}  max={values.max()}  min={values.min()}"
    )
    ax.grid(alpha=0.3)
    fig.tight_layout()

    png = path.replace(".csv", ".png")
    fig.savefig(png, dpi=130)
    print(f"plot saved  -> {png}")

    if show:
        plt.show()
    plt.close(fig)      # in a batch, never leave figures open to accumulate


def countdown(seconds, label):
    """Print a ticking countdown so there is time to trigger the source."""
    if seconds <= 0:
        return
    whole = int(seconds)
    for remaining in range(whole, 0, -1):
        print(f"\r  trigger '{label}' in {remaining}... ", end="", flush=True)
        time.sleep(1)
    leftover = seconds - whole
    if leftover > 0:
        time.sleep(leftover)
    print(f"\r  capturing '{label}' now       ", flush=True)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="capture.py",
        description="Trigger EMI captures on the ESP32 and save them as labelled CSV.",
        epilog=(
            "examples:\n"
            "  python capture.py ambient               one capture, plot shown\n"
            "  python capture.py lighter --n 20        20 captures, no blocking windows\n"
            "  python capture.py phone --n 50 --no-plot --delay 2\n"
            "  python capture.py lighter --trigger --n 20 --no-plot\n"
            "                                          wait for each click, no countdown\n"
            "\n"
            "Put the label first: 'capture.py lighter --trigger', not\n"
            "'capture.py --trigger lighter'.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("label", help="class label, e.g. ambient, lighter, phone")
    ap.add_argument("-n", "--n", type=int, default=1, metavar="N",
                    help="take N captures in a row under the same label (default 1)")
    ap.add_argument("--no-plot", action="store_true",
                    help="skip matplotlib entirely, no window and no PNG")
    ap.add_argument("--delay", type=float, default=None, metavar="SEC",
                    help="pause before each capture, with a countdown "
                         "(default 3 when N > 1, 0 when N == 1)")
    ap.add_argument("--port", default=None,
                    help="serial port, overrides config and EMI_PORT")
    ap.add_argument("--trigger", nargs="?", const=300, type=int, default=None,
                    metavar="DEPTH",
                    help="wait for an event instead of capturing at once: the "
                         "board arms, then saves the 100 ms around the first "
                         "dip at least DEPTH counts below rest (default 300), "
                         "with the dip at sample 400. For events: lighter, "
                         "relay, switch-on, plug-in. No countdown needed")

    meta_group = ap.add_argument_group(
        "collection conditions",
        "Recorded in the CSV header. These guard against block confounds: if "
        "one class is collected under a condition no other class shares, the "
        "model can learn the condition instead of the source. See "
        "docs/DATASET.md.")
    meta_group.add_argument("--power", choices=("charger", "battery", "unknown"),
                            default="unknown",
                            help="laptop power state. Detected automatically on "
                                 "Windows, which overrides this flag; it is the "
                                 "fallback elsewhere (default: unknown)")
    meta_group.add_argument("--room", default="",
                            help="where this was collected, e.g. lab, hostel, kitchen")
    meta_group.add_argument("--distance-cm", default="", metavar="CM",
                            help="approximate coil-to-source distance")
    meta_group.add_argument("--device", default="", metavar="ID",
                            help="which physical source, e.g. charger_a, phone_b. "
                                 "Lets the evaluation hold out a whole device")
    meta_group.add_argument("--note", default="",
                            help="anything else worth remembering about this batch")
    return ap.parse_args(argv)


def main():
    args = parse_args()

    label = args.label.strip().replace(" ", "_")
    if args.n < 1:
        print("--n must be at least 1")
        sys.exit(1)

    triggered = args.trigger is not None
    if triggered and args.trigger < 1:
        print("--trigger DEPTH must be at least 1")
        sys.exit(1)
    if triggered:
        command = f"t{args.trigger}".encode()
        read_timeout = 45          # board gives up after 30 s armed
        default_delay = 0.0        # the board waits for the event itself
    else:
        command = b"g"
        read_timeout = 15
        default_delay = 3.0 if args.n > 1 else 0.0
    delay = args.delay if args.delay is not None else default_delay

    port, port_source = resolve_port(args.port)

    detected_power = detect_power()
    power = args.power
    if detected_power:
        if args.power not in ("unknown", detected_power):
            print(f"  WARNING: --power {args.power}, but the laptop reports "
                  f"'{detected_power}'. Recording '{detected_power}'.")
        power = detected_power
        print(f"  laptop power: {power} (detected)")
    elif args.power == "unknown":
        print("  NOTE: --power not set, recording 'unknown'. The laptop charger")
        print("        shifts the noise floor, so an unlabelled dataset is hard")
        print("        to defend later. See docs/DATASET.md.")

    conditions = {
        "power": power,
        "room": args.room.strip(),
        "distance_cm": args.distance_cm.strip(),
        "device": args.device.strip(),
        "note": args.note.strip(),
    }

    print(f"opening {port} at {BAUD}   (port from {port_source})")
    ser = serial.Serial(port, BAUD, timeout=2)
    time.sleep(2)          # let the ESP32 finish resetting

    saved = []
    failed = 0
    timing_bad = 0
    pending_plots = []

    try:
        for i in range(args.n):
            if args.n > 1:
                print(f"\n[{i + 1}/{args.n}]")

            countdown(delay, label)
            values, meta = read_capture(ser, timeout_s=read_timeout,
                                        command=command)

            if len(values) == 0 and "timeout" in meta:
                print("  nothing fired within 30 s - no capture saved.")
                print(f"  If the source did fire, try a smaller depth, e.g. "
                      f"--trigger {max(1, args.trigger // 2)}")
                failed += 1
                if args.n == 1:
                    sys.exit(2)
                continue

            if len(values) == 0 and "armed" in meta:
                # Seen once, 16 Oct: ARMED arrived, then neither TIMEOUT nor
                # a capture. The board itself was fine on retry.
                print(f"  NO REPLY after arming: no TIMEOUT and no capture "
                      f"within {read_timeout} s. The board may have reset.")
                for line in meta.get("stray", [])[-5:]:
                    print(f"    received: {line[:70]!r}")
                failed += 1
                if args.n == 1:
                    sys.exit(2)
                continue

            if len(values) == 0:
                for line in meta.get("stray", [])[-5:]:
                    print(f"    received: {line[:70]!r}")
                print("NO DATA. Things to check:")
                print("  - is the port correct, and is the Arduino Serial Monitor closed?")
                print("  - is the sketch uploaded and running?")
                print("  - is the USB cable a data cable, not charge-only?")
                failed += 1
                if args.n == 1:
                    sys.exit(2)
                continue

            # diagnostics only; save_csv writes every meta key to the header
            meta.pop("armed", None)
            meta.pop("stray", None)

            # Never save a damaged capture. Seen 16 Oct with a running mixer
            # beside the board: a capture arrived with 1980 of 2000 samples,
            # i.e. lines were lost on the serial link. A merged line would
            # parse as a value far above 4095.
            expected = int(meta.get("samples", 0) or 0)
            if len(values) != expected or values.min() < 0 or values.max() > 4095:
                print(f"  DAMAGED capture, not saved: {len(values)} of {expected} "
                      f"samples, range {values.min()}..{values.max()}.")
                print("  Strong interference near the ESP32 or its USB cable? "
                      "Move the source or the cable further from the board.")
                failed += 1
                continue

            print(f"got {len(values)} samples   "
                  f"min={values.min()}  max={values.max()}  mean={values.mean():.1f}")
            if meta.get("mode") == "triggered":
                print(f"  fired after {int(meta.get('armed_ms', 0)) / 1000:.1f} s "
                      f"armed; dip starts at sample {meta.get('trig_index', '?')}")

            check_signal(values)
            if not check_timing(meta, announce_ok=(i == 0 or args.n == 1)):
                timing_bad += 1

            path = save_csv(label, values, meta, conditions)
            print(f"csv saved   -> {path}")
            saved.append(path)

            if not args.no_plot:
                # Deferred until after the port is closed, below.
                pending_plots.append((label, values, meta, path))
    finally:
        ser.close()

    # The state is read once at the start; say so if it moved mid-batch.
    if detected_power and saved:
        end_power = detect_power()
        if end_power and end_power != detected_power:
            print(f"  WARNING: laptop power changed during this batch "
                  f"({detected_power} -> {end_power}). Its files all say "
                  f"'{detected_power}'; note which ones are wrong.")

    # Plot only once the serial port is released. A blocking plot window used
    # to sit inside the try block, so it held the port open for as long as it
    # was on screen and the next run failed with "Access is denied". During
    # collection that would look like random dead captures.
    for plot_label, plot_values, plot_meta, plot_path in pending_plots:
        # Only block on a window for a single capture. In a batch the PNG is
        # still written, but nothing waits for a click -- 200 captures a class
        # means 1600 windows otherwise.
        plot(plot_label, plot_values, plot_meta, plot_path, show=(args.n == 1))

    if args.n > 1:
        print(f"\ndone: {len(saved)} saved, {failed} failed, label '{label}'")
        if timing_bad:
            print(f"  {timing_bad} of {len(saved)} captures missed the target "
                  f"sampling rate - see the warnings above before using this data")
        if failed:
            sys.exit(2)


if __name__ == "__main__":
    main()
