# Threshold baseline and dataset checks

Captures: 2295.

**Threshold T = 193 counts**: the 95th percentile of the amplitude A = rest_ref − min over 843 ambient captures, fixed on ambient alone.

| class | n | median A | alarm rate at T |
|---|---|---|---|
| ambient | 843 | 134 | 5.1% |
| spark | 219 | 549 | 99.1% |
| switching_supply | 380 | 814 | 78.9% |
| display | 174 | 1447 | 96.0% |
| sparking_motor | 100 | 1194 | 96.0% |
| mains_hum | 120 | 193 | 50.8% |
| emp | 204 | 1767 | 100.0% |
| other | 240 | 184 | 40.8% |

By appliance label (the class each label maps to in brackets; "other" = recorded but not a classifier target):

| label | n | median A | alarm rate at T |
|---|---|---|---|
| ambient (ambient) | 843 | 134 | 5.1% |
| lighter (spark) | 219 | 549 | 99.1% |
| adapter (switching_supply) | 40 | 1590 | 100.0% |
| charger (switching_supply) | 340 | 528 | 76.5% |
| phone_screen (display) | 174 | 1447 | 96.0% |
| mixer (sparking_motor) | 100 | 1194 | 96.0% |
| airfryer (mains_hum) | 20 | 127 | 0.0% |
| console (mains_hum) | 60 | 220 | 98.3% |
| grinder (mains_hum) | 20 | 178 | 10.0% |
| tv (mains_hum / other) | 60 | 140 | 26.7% |
| emp (emp / emp_damaged) | 219 | 1710 | 100.0% |
| amplifier (other) | 40 | 192 | 50.0% |
| purifier (other) | 20 | 196 | 70.0% |
| router (other) | 20 | 186 | 40.0% |
| speaker (other) | 40 | 590 | 67.5% |
| vacuum (other) | 40 | 144 | 12.5% |
| whisk (other) | 40 | 157 | 20.0% |

Attack captures (the SecureTrack emitter) by device and distance; `emp_a_damaged` is the same unit after its coil end burnt, `emp_a_repaired` after its coil lead was moved to another hole (battery 3.9 V, against 3.3 V for `emp_a`):

| device | distance (cm) | n | median A | alarm rate at T |
|---|---|---|---|---|
| emp_a | 1 | 40 | 1991 | 100.0% |
| emp_a | 3 | 89 | 1640 | 100.0% |
| emp_a | 5 | 38 | 1484 | 100.0% |
| emp_a_damaged | 5 | 15 | 1384 | 100.0% |
| emp_a_repaired | 3 | 19 | 1982 | 100.0% |
| emp_a_repaired | 5 | 18 | 1951 | 100.0% |

Every benign class's alarm rate is the amplitude threshold's false-alarm rate on that class, and the emp rate its detection rate. Ambient sits near 5% by construction.

## Block-confound check

- No label holds a power or room value alone.

### power

| label | values |
|---|---|
| ambient | battery (843) |
| lighter | battery (219) |
| adapter | battery (40) |
| charger | battery (340) |
| phone_screen | battery (174) |
| mixer | battery (100) |
| airfryer | battery (20) |
| console | battery (60) |
| grinder | battery (20) |
| tv | battery (60) |
| emp | battery (219) |
| amplifier | battery (40) |
| purifier | battery (20) |
| router | battery (20) |
| speaker | battery (40) |
| vacuum | battery (40) |
| whisk | battery (40) |

### room

| label | values |
|---|---|
| ambient | home1_bedroom (160), home1_theatre (102), home2_bedroom (100), home1_terrace (100), home1_kitchen (80), home2_kitchen (80), home1_hall (61), home2_hall (60), home3_kitchen (40), home3_bedroom2 (40), home3_bedroom1 (20) |
| lighter | home1_bedroom (80), home2_bedroom (59), home1_kitchen (40), home3_kitchen (40) |
| adapter | home3_bedroom2 (40) |
| charger | home1_bedroom (220), home2_bedroom (40), home1_hall (40), home3_bedroom2 (40) |
| phone_screen | home1_bedroom (54), home2_bedroom (40), home1_hall (40), home1_kitchen (20), home1_theatre (20) |
| mixer | home1_kitchen (60), home2_kitchen (40) |
| airfryer | home1_kitchen (20) |
| console | home3_bedroom2 (60) |
| grinder | home1_kitchen (20) |
| tv | home2_hall (40), home3_bedroom1 (20) |
| emp | home1_terrace (219) |
| amplifier | home1_theatre (40) |
| purifier | home3_kitchen (20) |
| router | home3_bedroom2 (20) |
| speaker | home1_bedroom (40) |
| vacuum | home1_bedroom (40) |
| whisk | home2_kitchen (40) |

### device

| label | values |
|---|---|
| ambient | none (803), - (40) |
| lighter | lighter_a (120), lighter_b (59), lighter_c (40) |
| adapter | router_adapter_a (40) |
| charger | charger_f (100), charger_a (60), charger_b (60), charger_c (40), charger_d (40), charger_e (40) |
| phone_screen | phone_a (94), phone_b (40), phone_c (40) |
| mixer | mixer_a (60), mixer_b (40) |
| airfryer | airfryer_a (20) |
| console | ps5_a (60) |
| grinder | grinder_a (20) |
| tv | tv_a (40), tv_c (20) |
| emp | emp_a (167), emp_a_repaired (37), emp_a_damaged (15) |
| amplifier | amplifier_a (40) |
| purifier | purifier_a (20) |
| router | router_a (20) |
| speaker | alexa_a (40) |
| vacuum | vacuum_a (40) |
| whisk | whisk_a (40) |

### distance_cm

| label | values |
|---|---|
| ambient | - (823), 5 (20) |
| lighter | 2 (99), 1 (80), 3 (40) |
| adapter | 0 (20), 2 (20) |
| charger | 0 (140), 2 (140), 5 (60) |
| phone_screen | 0 (174) |
| mixer | 5 (40), 15 (20), 30 (20), 2 (20) |
| airfryer | 2 (20) |
| console | 2 (20), 5 (20), 0 (20) |
| grinder | 0 (20) |
| tv | 2 (40), 0 (20) |
| emp | 3 (108), 5 (71), 1 (40) |
| amplifier | 2 (20), 0 (20) |
| purifier | 2 (20) |
| router | 0 (20) |
| speaker | 2 (20), 3 (20) |
| vacuum | 2 (20), 1 (20) |
| whisk | 5 (20), 2 (20) |

### mode

| label | values |
|---|---|
| ambient | free (840), triggered (3) |
| lighter | triggered (219) |
| adapter | free (40) |
| charger | free (340) |
| phone_screen | free (174) |
| mixer | free (100) |
| airfryer | free (20) |
| console | free (60) |
| grinder | free (20) |
| tv | free (60) |
| emp | triggered (219) |
| amplifier | free (40) |
| purifier | free (20) |
| router | free (20) |
| speaker | free (40) |
| vacuum | free (40) |
| whisk | free (40) |

Figures: `amplitude_by_class.png`, `threshold_sweep.png`, `envelopes_by_class.png`.
