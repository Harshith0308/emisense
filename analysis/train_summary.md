# Classifier summary

Captures: 2040 in 7 mechanism classes; 255 more from sources that are not classifier targets.

| class | captures | devices | models | rooms |
|---|---|---|---|---|
| ambient | 843 | — | — | 11 |
| spark | 219 | 3 | 3 | 4 |
| switching_supply | 380 | 7 | 4 | 4 |
| display | 174 | 3 | 3 | 5 |
| sparking_motor | 100 | 2 | 2 | 2 |
| mains_hum | 120 | 4 | 4 | 3 |
| emp | 204 | 2 | 2 | 1 |

Model: 15 features -> 32 hidden (ReLU) -> 7, int8 weights. Scores are the quantised model's, mean ± standard deviation over 5 seeds.

## Generalisation

| test | n | accuracy | macro F1 | balanced accuracy |
|---|---|---|---|---|
| blocks held out (5 folds) | 2040.000 ± 0.000 | 0.876 ± 0.005 | 0.846 ± 0.002 | 0.833 ± 0.003 |
| rooms held out | 1736.000 ± 0.000 | 0.775 ± 0.010 | 0.697 ± 0.015 | 0.668 ± 0.015 |
| models held out (ambient and emp train) | 993.000 ± 0.000 | 0.668 ± 0.010 | 0.685 ± 0.019 | 0.616 ± 0.017 |

## Recall per class

| class | blocks held out | rooms held out | models held out |
|---|---|---|---|
| ambient | 0.95 ± 0.01 | 0.94 ± 0.01 | — |
| spark | 0.89 ± 0.02 | 0.78 ± 0.02 | 0.78 ± 0.02 |
| switching_supply | 0.78 ± 0.02 | 0.62 ± 0.02 | 0.69 ± 0.00 |
| display | 0.83 ± 0.03 | 0.83 ± 0.02 | 0.80 ± 0.03 |
| sparking_motor | 0.66 ± 0.05 | 0.37 ± 0.05 | 0.34 ± 0.07 |
| mains_hum | 0.78 ± 0.03 | 0.46 ± 0.03 | 0.47 ± 0.01 |
| emp | 0.92 ± 0.02 | — | — |

## Each source model held out

| model | class | n | accuracy | predicted (summed over 5 seeds) |
|---|---|---|---|---|
| phone_a | display | 94 | 0.79 ± 0.00 | display 370, emp 90, ambient 10 |
| phone_b | display | 40 | 0.64 ± 0.12 | display 127, sparking_motor 42, ambient 24 |
| phone_c | display | 40 | 0.98 ± 0.01 | display 196, sparking_motor 4 |
| airfryer_a | mains_hum | 20 | 1.00 ± 0.00 | mains_hum 100 |
| grinder_a | mains_hum | 20 | 1.00 ± 0.00 | mains_hum 100 |
| ps5_a | mains_hum | 60 | 0.00 ± 0.00 | sparking_motor 196, ambient 100, spark 4 |
| tv_a | mains_hum | 20 | 0.82 ± 0.05 | mains_hum 82, ambient 18 |
| lighter_a | spark | 120 | 0.85 ± 0.03 | spark 511, emp 86, ambient 3 |
| lighter_b | spark | 59 | 0.52 ± 0.02 | spark 153, emp 59, sparking_motor 48 |
| lighter_c | spark | 40 | 0.95 ± 0.02 | spark 190, ambient 8, emp 2 |
| mixer_a | sparking_motor | 60 | 0.21 ± 0.12 | display 174, emp 64, sparking_motor 62 |
| mixer_b | sparking_motor | 40 | 0.54 ± 0.04 | sparking_motor 107, spark 55, mains_hum 21 |
| apple_charger | switching_supply | 180 | 0.46 ± 0.00 | switching_supply 414, ambient 400, emp 75 |
| charger_a | switching_supply | 60 | 1.00 ± 0.00 | switching_supply 300 |
| router_adapter_a | switching_supply | 40 | 1.00 ± 0.00 | switching_supply 200 |
| samsung_45w | switching_supply | 100 | 0.81 ± 0.01 | switching_supply 403, ambient 92, mains_hum 4 |

## Ablation: magnitude against timing

| features | count | accuracy, blocks held out | macro F1 | accuracy at a held-out distance |
|---|---|---|---|---|
| all features | 15 | 0.876 ± 0.005 | 0.846 ± 0.002 | 0.725 ± 0.018 (n=1023) |
| magnitude only | 7 | 0.800 ± 0.006 | 0.684 ± 0.007 | 0.644 ± 0.007 (n=1023) |
| temporal only | 8 | 0.797 ± 0.011 | 0.739 ± 0.007 | 0.572 ± 0.012 (n=1023) |

Magnitude: max_dip, mean_dip, act150, act400, rough, level_drop, depth_cv. Temporal: n_events, width_med, interval_med, interval_cv, ac_peak, ac_lag_ms, zcr, lag_fine_ms. The last column trains with one distance removed and tests only on that distance, for every class recorded at two or more distances.

## Attack detection

Amplitude threshold T = 193 counts (95th percentile of A = rest_ref - min over ambient, as in analyze.py); the classifier alarms when it predicts emp. The attack is one emitter recorded in one place, so emp is never held out by room or by model; its distance can be held out.

| method | detects the attack | false alarms, benign sources | false alarms, ambient |
|---|---|---|---|
| amplitude threshold | 100.0% | 84.7% | 5.1% |
| classifier, blocks held out | 92.4 ± 1.7% | 5.8 ± 0.3% | 0.2 ± 0.1% |
| classifier, emp at an unseen distance | 88.8 ± 1.7% (n=204) | — | — |
| classifier, re-seated emitter never trained on | 91.9 ± 0.0% (n=37) | — | — |
| amplitude threshold, re-seated emitter | 100.0% | — | — |

| emp distance | n | threshold detects | classifier detects (blocks) |
|---|---|---|---|
| 1 cm | 40 | 100.0% | 92.5 ± 2.7% |
| 3 cm | 108 | 100.0% | 91.5 ± 1.8% |
| 5 cm | 56 | 100.0% | 93.9 ± 2.7% |

| re-seated emitter, distance | n | classifier detects (never trained on it) |
|---|---|---|
| 3 cm | 19 | 84.2 ± 0.0% |
| 5 cm | 18 | 100.0 ± 0.0% |

| class | threshold alarms | classifier calls it emp (blocks) |
|---|---|---|
| ambient | 5.1% | 0.2 ± 0.1% |
| spark | 99.1% | 5.6 ± 1.5% |
| switching_supply | 78.9% | 4.2 ± 0.5% |
| display | 96.0% | 10.6 ± 0.3% |
| sparking_motor | 96.0% | 10.8 ± 2.1% |
| mains_hum | 50.8% | 0.2 ± 0.3% |

| never trained on (final model) | n | called emp |
|---|---|---|
| amplifier | 40 | 0.0% |
| emp_a_damaged | 15 | 66.7% |
| purifier | 20 | 5.0% |
| router | 20 | 0.0% |
| speaker | 40 | 10.0% |
| tv | 40 | 0.0% |
| vacuum | 40 | 0.0% |
| whisk | 40 | 2.5% |

## Confusion matrix, blocks held out (rows true, columns predicted; summed over 5 seeds)

| true \ pred | ambient | spark | switching_supply | display | sparking_motor | mains_hum | emp |
|---|---|---|---|---|---|---|---|
| ambient | 4006 | 38 | 123 | 4 | 4 | 33 | 7 |
| spark | 19 | 976 | 0 | 4 | 34 | 1 | 61 |
| switching_supply | 334 | 0 | 1480 | 1 | 4 | 2 | 79 |
| display | 35 | 0 | 1 | 726 | 16 | 0 | 92 |
| sparking_motor | 3 | 61 | 14 | 18 | 332 | 18 | 54 |
| mains_hum | 114 | 0 | 0 | 1 | 13 | 471 | 1 |
| emp | 0 | 34 | 10 | 19 | 12 | 3 | 942 |

## Sources outside the classes, as the final model calls them

| label | n | predicted |
|---|---|---|
| amplifier | 40 | switching_supply 25, spark 7, ambient 6 |
| emp_a_damaged | 15 | emp 10, spark 2, sparking_motor 1 |
| purifier | 20 | switching_supply 13, sparking_motor 4, mains_hum 2 |
| router | 20 | ambient 20 |
| speaker | 40 | mains_hum 21, switching_supply 10, ambient 5 |
| tv | 40 | switching_supply 30, ambient 10 |
| vacuum | 40 | switching_supply 24, ambient 12, display 4 |
| whisk | 40 | mains_hum 19, switching_supply 11, ambient 8 |
