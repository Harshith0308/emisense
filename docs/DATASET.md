# The EMISense dataset

2,295 captures of electromagnetic interference picked up by a coil, each
100 ms long, from 26 household sources and an EMI attack emitter, recorded in
120 blocks over seven days (16–23 October 2026) in eleven places in three
homes. Every capture was recorded with the logging laptop on battery.

## Each capture

One CSV file per capture in `data/`, named
`<label>_<YYYYMMDD>_<HHMMSS>_<ms>.csv`. The file starts with header rows of the
form `# key,value`, followed by 2,000 rows of samples:

```
# label,lighter
# mode,triggered
...
sample_index,time_ms,adc_value
0,0.0,1988
1,0.05,1991
...
```

| Header field | Meaning |
|---|---|
| `label` | the recorded source type (see the table below) |
| `mode` | `free`: 100 ms captured at once; `triggered`: the board waited for an event |
| `samples`, `interval_us` | 2000 samples, 50 µs apart (20 kSa/s) |
| `elapsed_us` | measured duration of the 2000 samples (about 99,991 µs) |
| `resting` | triggered only: the board's resting level, measured just before arming |
| `trig_depth`, `trig_level` | triggered only: the event is the first reading `trig_depth` counts below `resting` |
| `trig_index`, `armed_ms` | triggered only: the event sits at sample 400; time spent waiting |
| `captured_at`, `time_of_day` | local time of the capture (ISO 8601) |
| `power` | the logging laptop's power state (`battery` for every capture) |
| `room` | the place, anonymized: `home1_kitchen`, `home2_hall`, ... |
| `distance_cm` | coil to source; `0` means touching |
| `device` | the physical unit, e.g. `charger_b` |
| `note` | conditions during the block (phone charge, display state, plug-in length, ...) |

`adc_value` is the ESP32's 12-bit reading (0–4095, 11 dB attenuation, about
0 to 3.1 V). **The front end inverts:** the output rests near 1,950–2,075
counts and interference pulls it down, so the depth below the resting level is
what matters. A spark at 1 cm can reach the floor near 600 counts; the
emitter at 1–3 cm drives the reading across the whole range.

## metadata.csv

One row per capture, for selecting and splitting without opening the files:

| Column | Meaning |
|---|---|
| `file` | file name in `data/` |
| `label`, `device`, `distance_cm`, `mode`, `trig_depth`, `room`, `captured_at`, `power`, `note` | as in the header |
| `class` | the classifier class (below), or empty for sources that are not classifier targets |
| `model` | units of the same product model share this value and are held out together |
| `block` | recording block: consecutive captures of one source, unit and distance, seconds apart. Near-duplicates: never split a block between training and test |
| `rest_ref` | resting level of the nearest ambient captures in the same place and session (other blocks only). The amplitude is `A = rest_ref - min(adc_value)` |

## Sources

| Label | Device | What it is | Class | Captures | Distances (cm) |
|---|---|---|---|---|---|
| ambient | — | the place with no deliberate source; appliances sometimes present but off | ambient | 843 | — |
| adapter | router_adapter_a | a Wi-Fi router's power adapter | switching_supply | 40 | 0, 2 |
| charger | charger_a | Anker 100 W phone charger | switching_supply | 60 | 0, 2, 5 |
| charger | charger_b | Samsung 45 W charger | switching_supply | 60 | 0, 2, 5 |
| charger | charger_c | Apple USB-C charger | switching_supply | 40 | 0 |
| charger | charger_d | Samsung 45 W charger, a second unit | switching_supply | 40 | 0, 2 |
| charger | charger_e | Apple 20 W charger | switching_supply | 40 | 0, 2 |
| charger | charger_f | Apple 20 W charger, a second unit | switching_supply | 100 | 0, 2, 5 |
| lighter | lighter_a, lighter_b | piezo lighters | spark | 179 | 1, 2, 3 |
| lighter | lighter_c | gas-stove piezo igniter | spark | 40 | 1, 2 |
| phone_screen | phone_a | Samsung Galaxy S25 Ultra, coil on the screen | display | 94 | 0 |
| phone_screen | phone_b | Apple iPhone 14, coil on the screen | display | 40 | 0 |
| phone_screen | phone_c | Samsung Galaxy S24 Ultra, coil on the screen | display | 40 | 0 |
| mixer | mixer_a, mixer_b | mixer-grinders with commutator sparking | sparking_motor | 100 | 2, 5, 15, 30 |
| console | ps5_a | Sony PlayStation 5 | mains_hum | 60 | 0, 2, 5 |
| tv | tv_a | Samsung TV: back near the power entry / screen | mains_hum / — | 20 / 20 | 2 / 0 |
| grinder | grinder_a | mixer-grinder with a smooth hum and no sparks | mains_hum | 20 | 0 |
| airfryer | airfryer_a | air fryer | mains_hum | 20 | 2 |
| emp | emp_a | EMI attack emitter, battery at 3.3 V | emp | 167 | 1, 3, 5 |
| emp | emp_a_repaired | the same emitter after its coil lead was reconnected, battery at 3.9 V | emp | 37 | 3, 5 |
| emp | emp_a_damaged | the same emitter after one end of its coil burnt | — | 15 | 5 |
| amplifier | amplifier_a | home-theatre amplifier playing music | — | 40 | 0, 2 |
| vacuum | vacuum_a | vacuum cleaner | — | 40 | 1, 2 |
| tv | tv_c | LG TV, back | — | 20 | 2 |
| router | router_a | Wi-Fi router body, its adapter 30 cm away | — | 20 | 0 |
| whisk | whisk_a | electric hand whisk | — | 40 | 2, 5 |
| speaker | alexa_a | Amazon Echo Dot playing music | — | 40 | 2, 3 |
| purifier | purifier_a | RO water purifier, pump running | — | 20 | 2 |

Phone displays were recorded with the always-on display, with the panel off,
and with the screen on; the state is in each note.

## Classes

Classes follow the physical mechanism of the emission rather than the
appliance, so that every benign class contains several devices and can be
tested on a device the model has never seen:

| Class | Mechanism | What the coil sees |
|---|---|---|
| ambient | none | the place's own background |
| spark | piezo discharge | one fast spike, nothing else in 100 ms |
| switching_supply | switch-mode power conversion | a drop of the whole level plus kHz ripple |
| display | display refresh | bursts locked to the refresh (16.65 ms, 19.80 ms) |
| sparking_motor | brush commutation | dense sparks timed by the mains half-cycle |
| mains_hum | mains-frequency current in large supplies and motors | a smooth 100 Hz line |
| emp | the attack emitter | dense discharges reaching the ends of the range |

A source joined a class only if its signature was clearly above the place's
background and another device shares its mechanism. The others stay in the
dataset and in the threshold evaluation, but not in the classifier: weak
sources (amplifier, vacuum, LG TV, router) and the only devices of their kind
(whisk, speaker, purifier, the Samsung TV's screen). `emp_a_damaged` is kept
apart because the damage changed its signal.

## How it was recorded

- **Hardware.** One detector (coil, BC548 stage, envelope detector, ESP32;
  see [HARDWARE.md](HARDWARE.md)) recorded every capture. Its transistor was
  replaced after the attack emitter damaged it on 23 October; only 20 ambient
  captures were recorded on the replacement.
- **Modes.** Continuous sources and ambient were captured free-running.
  Events were captured in triggered mode with a depth of 150 counts below the
  resting level, aligned at sample 400. A triggered capture exists only if its
  event crossed 150 counts, so weaker events are absent.
- **Blocks.** Captures were taken in blocks of 20 (sometimes fewer), each of
  one source, one unit and one distance, set with spacers. Blocks of different
  classes were interleaved, and ambient blocks recurred throughout every
  session, so that no class is tied to a place or a time.
- **Checks.** Every session began with a sensitivity check against a source
  of known response (a phone display or a piezo spark), repeated after every
  move of the detector: a loosened coil lead leaves the resting level normal
  while removing the response.
- **Power.** The laptop logging the captures ran on battery for every
  capture: its charger raises the noise floor near the coil.
- **The attack.** The emitter (a high-voltage module run from a battery,
  feeding a loop coil roughly 6 cm across) was recorded in the open air on a
  rooftop, with no mains wiring nearby, in three sessions, with ambient
  blocks at the same spot. A
  plastic sheet lay between the two coils. The emitter was connected for 1 to
  5 s at a time and the detector, in triggered mode, captured repeatedly while
  it ran. Distances of 1, 3 and 5 cm match the SecureTrack evaluation.

## Caveats

- Distances are approximate (spacers by hand). Up close, strong sources
  saturate the front end, so depths at 1 cm are compressed.
- `charger_f` at 2 and 5 cm was charging a nearly full phone and shows only
  a weak 100 Hz line, no switching signature; it is kept and labelled
  `switching_supply`.
- `emp_a` passes 3–5 at 3 cm read weaker than passes 1–2 at the same
  distance; the cause (coil wear, battery or placement) is not separable.
  `emp_a_repaired` ran on a battery 0.6 V higher than `emp_a`.
- In `home1_theatre`, an uninterruptible power supply and a projector near the
  board injected single-sample dips that do not come through the coil; they
  appear in some ambient captures there.
- The resting level drifts slowly, probably with temperature (`rest_ref`
  ranges from 1,967 to 2,075 counts over the dataset); use `rest_ref` rather
  than a fixed level.

## Not detected

About thirty further devices were tried and did not register above the
background, or only at the noise level; their captures are not released. They
include a hair dryer, kettle, clothes steamer, microwave oven, refrigerator,
kitchen chimney fan, a phone's radio during a 5G call, a laptop charger
brick, a rocker switch under load, a smartwatch charging puck, a 200 Hz
monitor, an infrared remote, a battery Bluetooth speaker, two subwoofers, an
Echo Show 5, a tower speaker, a further mixer-grinder, a second air fryer,
two further TVs, the displays of a Galaxy S25 and S25+, an uninterruptible
power supply, a projector, a set-top box and its adapter, LED bulbs and an
earbuds case. Captures withdrawn for a known fault (a loose coil lead, the
laptop on its charger, a damaged transistor) are not released either.

## License

[CC BY 4.0](../data/LICENSE). Please cite the dataset using
[CITATION.cff](../CITATION.cff).
