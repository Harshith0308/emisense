/*
 * emi_capture.ino
 *
 * Group 4 - Edge Computing (CSE 469), SRM AP
 * EMI source classification project.
 *
 * Captures a burst of analog samples from the EMI detector front end
 * and dumps them over serial as plain text, one value per line.
 *
 * Two modes, chosen by the first character received over serial:
 *
 *   t or t<depth>  TRIGGERED. Measure the resting level, then sample
 *                  continuously and wait for the output to dip <depth>
 *                  counts below rest (default TRIG_DEPTH). The capture is
 *                  sent with the dip at sample PRE_TRIGGER, so every event
 *                  lines up at the same index. For events: lighter, relay,
 *                  switch-on, charger plug-in. Replies ARMED first, and
 *                  TIMEOUT if nothing fires within ARM_TIMEOUT_MS.
 *
 *   anything else  FREE-RUNNING. Capture 100 ms immediately. For
 *                  continuous sources and ambient.
 *
 * Both modes sample on the same fixed 50 us schedule.
 *
 * Board:  ESP32 DevKit V1 (or any ESP32 / ESP32-S3 dev board)
 * Wiring: detector OUT  -> GPIO34   (ADC1, input only, safe choice)
 *         detector VCC  -> 3V3
 *         detector GND  -> GND
 *
 * IMPORTANT: if you are tapping a 5 V detector instead of
 * your own 3.3 V build, you MUST use a voltage divider (10k / 15k).
 * ESP32 pins are not 5 V tolerant.
 */

#include <algorithm>

#define ADC_PIN      34      // GPIO34: ADC1 channel, input-only, no WiFi conflict
#define N_SAMPLES    2000    // 2000 samples
#define INTERVAL_US  50      // 50 us between samples = 20,000 samples/second
                             // 2000 x 50us = 100 ms of signal per capture

// Triggered mode only. Sampling (pin, count, interval) is shared above.
#define PRE_TRIGGER      400      // samples kept before the dip: 20 ms
#define TRIG_DEPTH       300      // default: fire this many counts below rest
#define REST_PERCENTILE  90       // rest is the upper envelope, see below
#define ARM_TIMEOUT_MS   30000UL  // give up if nothing fires

uint16_t buf[N_SAMPLES];
uint16_t scratch[N_SAMPLES];

void setup() {
  Serial.begin(921600);
  analogReadResolution(12);              // 0 - 4095
  analogSetPinAttenuation(ADC_PIN, ADC_11db);  // full 0 - 3.3 V range
  delay(500);
  Serial.println("READY");
  Serial.println("Send any character to capture, or t to wait for an event.");
}

void capture() {
  uint32_t t0 = micros();
  for (int i = 0; i < N_SAMPLES; i++) {
    // busy-wait until this sample's scheduled moment
    while ((micros() - t0) < (uint32_t)i * INTERVAL_US) {
      // spin
    }
    buf[i] = analogRead(ADC_PIN);
  }
  uint32_t elapsed = micros() - t0;

  Serial.println("BEGIN");
  Serial.println("# mode=free");
  Serial.print("# samples=");   Serial.println(N_SAMPLES);
  Serial.print("# interval_us="); Serial.println(INTERVAL_US);
  Serial.print("# elapsed_us=");  Serial.println(elapsed);
  for (int i = 0; i < N_SAMPLES; i++) {
    Serial.println(buf[i]);
  }
  Serial.println("END");
}

// Resting level for the trigger: a high percentile of one full window, not
// the median. The output rests high and dips on EMI, so rest is its upper
// envelope; a median is dragged down by any EMI present while arming. One
// window is 100 ms, five mains cycles.
uint16_t resting_level() {
  uint32_t t0 = micros();
  for (int i = 0; i < N_SAMPLES; i++) {
    while ((micros() - t0) < (uint32_t)i * INTERVAL_US) {
      // spin
    }
    scratch[i] = analogRead(ADC_PIN);
  }
  int k = (N_SAMPLES * REST_PERCENTILE) / 100;
  std::nth_element(scratch, scratch + k, scratch + N_SAMPLES);
  return scratch[k];
}

// Wait for the output to dip `depth` counts below rest, then send the window
// with the start of the dip at sample PRE_TRIGGER. buf is used as a ring so
// the 20 ms before the dip are kept.
void capture_triggered(int depth) {
  uint16_t rest = resting_level();
  int level = (int)rest - depth;
  Serial.print("ARMED resting="); Serial.print(rest);
  Serial.print(" trig_level="); Serial.println(level);

  uint32_t armed_at = millis();
  uint32_t t0 = micros();
  uint32_t i = 0;
  uint32_t first_below = 0;
  int run = 0;              // consecutive samples below the level
  bool seen_high = false;   // fire on a falling edge, not on a signal already low

  while (true) {
    while ((micros() - t0) < i * INTERVAL_US) {
      // spin
    }
    uint16_t v = analogRead(ADC_PIN);
    buf[i % N_SAMPLES] = v;

    if ((int)v < level) {
      if (run == 0) first_below = i;
      run++;
      // two in a row, so a single noisy reading cannot fire it
      if (run >= 2 && seen_high && first_below >= PRE_TRIGGER) break;
    } else {
      run = 0;
      seen_high = true;
    }

    i++;
    if ((i & 1023) == 0 && (millis() - armed_at) > ARM_TIMEOUT_MS) {
      Serial.print("TIMEOUT resting="); Serial.print(rest);
      Serial.print(" trig_level="); Serial.println(level);
      return;
    }
  }
  uint32_t armed_ms = millis() - armed_at;

  // finish the window: PRE_TRIGGER samples before the dip, the rest after it
  uint32_t start = first_below - PRE_TRIGGER;
  uint32_t last = start + N_SAMPLES - 1;
  for (i = i + 1; i <= last; i++) {
    while ((micros() - t0) < i * INTERVAL_US) {
      // spin
    }
    buf[i % N_SAMPLES] = analogRead(ADC_PIN);
  }
  uint32_t elapsed = micros() - (t0 + start * INTERVAL_US);

  Serial.println("BEGIN");
  Serial.println("# mode=triggered");
  Serial.print("# samples=");     Serial.println(N_SAMPLES);
  Serial.print("# interval_us="); Serial.println(INTERVAL_US);
  Serial.print("# elapsed_us=");  Serial.println(elapsed);
  Serial.print("# resting=");     Serial.println(rest);
  Serial.print("# trig_depth=");  Serial.println(depth);
  Serial.print("# trig_level=");  Serial.println(level);
  Serial.print("# trig_index=");  Serial.println(PRE_TRIGGER);
  Serial.print("# armed_ms=");    Serial.println(armed_ms);
  for (uint32_t j = 0; j < N_SAMPLES; j++) {
    Serial.println(buf[(start + j) % N_SAMPLES]);
  }
  Serial.println("END");
}

void loop() {
  if (!Serial.available()) return;

  char cmd = Serial.read();
  if (cmd == 't' || cmd == 'T') {
    delay(20);                          // let the rest of "t300" arrive
    long depth = 0;
    while (Serial.available()) {
      char c = Serial.read();
      if (c >= '0' && c <= '9') depth = depth * 10 + (c - '0');
    }
    capture_triggered(depth > 0 ? (int)depth : TRIG_DEPTH);
  } else {
    while (Serial.available()) Serial.read();   // flush the trigger
    capture();
  }
  while (Serial.available()) Serial.read();     // drop anything sent meanwhile
}

/*
 * SANITY CHECK BEFORE COLLECTING DATA
 *
 * Open Serial Monitor at 921600 baud and send any character.
 *
 * IMPORTANT: this front end INVERTS. A common-emitter stage pulls the
 * collector down on a positive input, and the 1N4148 is oriented to catch
 * that downward swing (band at the collector). So the output RESTS HIGH
 * and DIPS when EMI arrives. Invert in software before feature extraction.
 *
 *   Resting 1800 - 3200   -> correct. Proceed to real captures.
 *   with small jitter        (collector ~0.9-2.0 V plus a ~0.6 V diode drop
 *                            is ~1.5-2.6 V, which is ~1800-3200 of 4095)
 *
 *   Flat at or near 4095  -> diode backwards, or nothing is connected to
 *                            GPIO34. The 1N4148 band goes at the COLLECTOR
 *                            (C10). Check the D20 -> GPIO34 jumper.
 *                            This is NOT saturation. See below.
 *
 *   Flat near 0           -> the bias is wrong, not the envelope stage.
 *                            Stop and use the multimeter, see below.
 *
 *   Small random values   -> nothing connected: a floating input. Normal at
 *                            step 4, before the circuit exists.
 *
 * SATURATION DOES NOT SHOW UP IN THIS DATA. It shows up as the COLLECTOR
 * sitting at 0 V, measured with a multimeter at C10 (see
 * docs/HARDWARE.md). If it does, raise R_B to 2.2M. If the collector instead
 * sits near 3.3 V the transistor is not conducting: the BC548 legs are
 * reversed (flat face toward you, legs down, C - B - E left to right).
 * Do not try to fix a bias fault by changing anything downstream.
 *
 * Check elapsed_us is close to N_SAMPLES * INTERVAL_US (100000). capture.py
 * warns automatically if it is more than 5% out. If it is much larger,
 * analogRead is too slow to hit 20 kHz on your board; raise INTERVAL_US to
 * 100 (10 kHz) and note the change -- the sampling rate is a claim the paper
 * makes, so it has to be the real one.
 */
