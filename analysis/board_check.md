# Board check: emi_classify against the Python pipeline

255 stored captures (15 per label, 17 labels), sent over serial with `v`; reference = features.py + the model rebuilt from `emi_classify/emi_model.h`.

- **Class agreement: 100.0%** (0 disagreements)
- Features outside tolerance (abs 0.0001, rel 0.0001): none
- Largest logit difference: 7.77e-05

| time on the ESP32 (µs) | median | 95th pct | max |
|---|---|---|---|
| features | 9612 | 10200 | 10439 |
| model | 60 | 62 | 161 |
| total | 9671 | 10261 | 10499 |

Per label, total µs (median): adapter 9834, airfryer 9651, ambient 9698, amplifier 9314, charger 9676, console 9756, emp 10273, grinder 9681, lighter 9656, mixer 9274, phone_screen 9427, purifier 9895, router 9794, speaker 9679, tv 9211, vacuum 9210, whisk 9994

Largest absolute difference per feature: max_dip 0, mean_dip 0.00012, act150 0, act400 0, rough 1.1e-05, n_events 0, width_med 0, interval_med 0, interval_cv 5.3e-07, ac_peak 1.5e-06, ac_lag_ms 2e-06, zcr 0, level_drop 0, lag_fine_ms 2e-06, depth_cv 5e-07
