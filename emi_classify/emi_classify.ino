/*
 * emi_classify.ino
 *
 * Group 4 - Edge Computing (CSE 469), SRM AP
 * EMI source classification project.
 *
 * On-device classification: the same 100 ms capture as emi_capture.ino, the
 * features defined in features.py, and the int8 MLP that train.py writes to
 * emi_model.h. Every line of the feature code mirrors features.py; change
 * the two together.
 *
 * NOT the collection firmware. The dataset is collected with emi_capture.ino;
 * flash that back before collecting again.
 *
 * Commands (921600 baud):
 *   c   capture 100 ms, classify, print the class, timings and features
 *   t or t<depth>   arm exactly as emi_capture.ino does, wait for a dip
 *       <depth> counts below rest (default TRIG_DEPTH), then classify the
 *       window with the dip at sample PRE_TRIGGER. This is how a deployed
 *       detector runs: an event arrives, it is identified.
 *   k   re-measure the resting reference (do it with no source near the coil)
 *   v   then the resting reference, then 2000 sample values, one per line:
 *       classify those instead. Used to check this code against features.py
 *       and train.py on stored CSVs.
 *   w / x   start / stop sending the window after each c or t result, as one
 *       line "WAVE v0 v1 ... v1999" (for the live dashboard; off at start-up,
 *       never sent for v)
 *
 * With the trigger mode this sketch contains everything emi_capture.ino
 * does, so its flash and RAM minus emi_capture's are the classifier's cost.
 *
 * The resting reference is the circuit's quiet resting level. level_drop
 * (feature 12) is measured against it, so a source that lowers the whole
 * window, such as a charger at contact, is visible. It is measured at start-up:
 * power the board up with nothing near the coil.
 */

#include <algorithm>
#include <math.h>
#include <string.h>
#include "emi_model.h"

#define ADC_PIN      34
#define N_SAMPLES    2000
#define INTERVAL_US  50

// Feature constants: must equal features.py
#define REST_INDEX   (N_SAMPLES * 90 / 100)
#define EVENT_LEVEL  150
#define STRONG_LEVEL 400
#define MERGE_GAP    10
#define POOL         4
#define N_POOLED     (N_SAMPLES / POOL)
#define LAG_MIN      10
#define LAG_MAX      250
#define SAMPLE_MS    0.05f
#define MAX_EVENTS   200      // merged events are >= 11 samples apart: <= 182
#define N_FEATURES_C 15       // compute_features() fills exactly this many
static_assert(EMI_N_FEATURES == N_FEATURES_C,
              "emi_model.h was trained on a different feature list: retrain");

// Triggered mode: the same constants as emi_capture.ino
#define PRE_TRIGGER      400
#define TRIG_DEPTH       150      // the dataset's trigger depth
#define ARM_TIMEOUT_MS   30000UL

uint16_t buf[N_SAMPLES];
uint16_t scratch[N_SAMPLES];
float pooled[N_POOLED];
int32_t starts[MAX_EVENTS];
int32_t widths[MAX_EVENTS];
int32_t peaks[MAX_EVENTS];
int32_t gaps[MAX_EVENTS];
int32_t rest_ref = 0;     // quiet resting level, see measure_rest_ref()
bool send_wave = false;   // w / x: also send the window (dashboard)

void setup() {
  Serial.begin(921600);
  Serial.setTimeout(3000);
  analogReadResolution(12);
  analogSetPinAttenuation(ADC_PIN, ADC_11db);
  delay(500);
  measure_rest_ref();
  Serial.print("READY classify rest_ref=");
  Serial.println(rest_ref);
}

void capture() {
  uint32_t t0 = micros();
  for (int i = 0; i < N_SAMPLES; i++) {
    while ((micros() - t0) < (uint32_t)i * INTERVAL_US) {
      // spin
    }
    buf[i] = analogRead(ADC_PIN);
  }
}

static int32_t rest_of(const uint16_t *v) {
  memcpy(scratch, v, sizeof(scratch));
  std::nth_element(scratch, scratch + REST_INDEX, scratch + N_SAMPLES);
  return scratch[REST_INDEX];
}

// Median of five quiet windows' resting levels.
void measure_rest_ref() {
  int32_t r[5];
  for (int k = 0; k < 5; k++) { capture(); r[k] = rest_of(buf); }
  std::sort(r, r + 5);
  rest_ref = r[2];
}

// np.median: middle value, or the mean of the two middle values. Sorts a.
static float median_i32(int32_t *a, int n) {
  if (n == 0) return 0.0f;
  std::sort(a, a + n);
  if (n % 2) return (float)a[n / 2];
  return 0.5f * ((float)a[n / 2 - 1] + (float)a[n / 2]);
}

// FEATURE_NAMES order: max_dip, mean_dip, act150, act400, rough, n_events,
// width_med, interval_med, interval_cv, ac_peak, ac_lag_ms, zcr, level_drop,
// lag_fine_ms, depth_cv
void compute_features(const uint16_t *v, float *f) {
  int32_t rest = rest_of(v);

  int32_t max_d = INT32_MIN;
  int64_t sum_dp = 0, sum_abs = 0, sum_v = 0;
  int32_t n150 = 0, n400 = 0;
  int n_ev = 0;
  int32_t last_end = 0;
  bool have_last = false;

  for (int i = 0; i < N_SAMPLES; i++) {
    int32_t d = rest - (int32_t)v[i];
    if (d > max_d) max_d = d;
    if (d > 0) sum_dp += d;
    if (d > STRONG_LEVEL) n400++;
    if (d > EVENT_LEVEL) {
      n150++;
      if (have_last && i - last_end <= MERGE_GAP) {
        widths[n_ev - 1] += i - last_end;          // extend the current event
        if (d > peaks[n_ev - 1]) peaks[n_ev - 1] = d;
      } else if (n_ev < MAX_EVENTS) {
        starts[n_ev] = i;
        widths[n_ev] = 1;
        peaks[n_ev] = d;
        n_ev++;
      }
      last_end = i;
      have_last = true;
    }
    if (i > 0) sum_abs += abs((int32_t)v[i] - (int32_t)v[i - 1]);
    sum_v += v[i];
  }

  // spread of the events' peak depths
  float depth_cv = 0.0f;
  if (n_ev >= 2) {
    double p_s = 0, p_q = 0;
    for (int j = 0; j < n_ev; j++) {
      p_s += peaks[j];
      p_q += (double)peaks[j] * peaks[j];
    }
    double mean = p_s / n_ev;
    if (mean > 0) {
      double var = p_q / n_ev - mean * mean;       // population, as np.std
      depth_cv = (float)(sqrt(var > 0 ? var : 0) / mean);
    }
  }

  int ng = n_ev >= 2 ? n_ev - 1 : 0;
  double g_sum = 0, g_sq = 0;
  for (int j = 0; j < ng; j++) {
    gaps[j] = starts[j + 1] - starts[j];
    g_sum += gaps[j];
    g_sq += (double)gaps[j] * gaps[j];
  }
  float interval_cv = 0.0f;
  if (ng >= 2 && g_sum > 0) {
    double mean = g_sum / ng;
    double var = g_sq / ng - mean * mean;          // population, as np.std
    interval_cv = (float)(sqrt(var > 0 ? var : 0) / mean);
  }

  // max-pool the positive dip, remove its mean, autocorrelate 2..50 ms
  double p_sum = 0;
  for (int j = 0; j < N_POOLED; j++) {
    int32_t best = 0;
    for (int q = 0; q < POOL; q++) {
      int32_t d = rest - (int32_t)v[j * POOL + q];
      if (d > best) best = d;
    }
    pooled[j] = (float)best;
    p_sum += best;
  }
  float p_mean = (float)(p_sum / N_POOLED);
  float r0 = 0;
  for (int j = 0; j < N_POOLED; j++) {
    pooled[j] -= p_mean;
    r0 += pooled[j] * pooled[j];
  }
  float ac_peak = 0.0f, ac_lag_ms = 0.0f, lag_fine_ms = 0.0f;
  int lag = 0;
  if (r0 > 0) {
    float best = -INFINITY;
    for (int k = LAG_MIN; k <= LAG_MAX; k++) {
      float r = 0;
      for (int i = 0; i + k < N_POOLED; i++) r += pooled[i] * pooled[i + k];
      if (r > best) { best = r; lag = k; }
    }
    ac_peak = best / r0 > 0 ? best / r0 : 0.0f;
    if (ac_peak > 0) ac_lag_ms = lag * POOL * SAMPLE_MS;
  }

  // The same autocorrelation on the unpooled positive dip, at each lag within
  // one pooled bin of the coarse peak. sum((a-m)(b-m)) is expanded so the
  // products stay exact in int64: sum(ab) - m*(sum a + sum b) + n*m*m.
  if (ac_peak > 0) {
    double m = (double)sum_dp / N_SAMPLES;
    int c = lag * POOL;
    double best = -INFINITY;
    int lag_f = c;
    for (int k = c - POOL; k <= c + POOL; k++) {
      int64_t s_ab = 0, s_a = 0, s_b = 0;
      int n = N_SAMPLES - k;
      for (int i = 0; i < n; i++) {
        int32_t a = rest - (int32_t)v[i];
        int32_t b = rest - (int32_t)v[i + k];
        if (a < 0) a = 0;
        if (b < 0) b = 0;
        s_ab += (int64_t)a * b;
        s_a += a;
        s_b += b;
      }
      double r = (double)s_ab - m * (double)(s_a + s_b) + n * m * m;
      if (r > best) { best = r; lag_f = k; }
    }
    lag_fine_ms = lag_f * SAMPLE_MS;
  }

  float v_mean = (float)((double)sum_v / N_SAMPLES);
  int32_t crossings = 0;
  for (int i = 1; i < N_SAMPLES; i++) {
    bool a = ((float)v[i - 1] - v_mean) < 0;
    bool b = ((float)v[i] - v_mean) < 0;
    if (a != b) crossings++;
  }

  f[0] = (float)max_d;
  f[1] = (float)sum_dp / N_SAMPLES;
  f[2] = (float)n150 / N_SAMPLES;
  f[3] = (float)n400 / N_SAMPLES;
  f[4] = (float)sum_abs / (N_SAMPLES - 1);
  f[5] = (float)n_ev;
  f[6] = median_i32(widths, n_ev);
  f[7] = median_i32(gaps, ng);
  f[8] = interval_cv;
  f[9] = ac_peak;
  f[10] = ac_lag_ms;
  f[11] = (float)crossings / N_SAMPLES;
  f[12] = (float)(rest_ref - rest);
  f[13] = lag_fine_ms;
  f[14] = depth_cv;
}

// The quantised MLP exactly as train.py's QuantisedMLP runs it.
int classify(const float *f, float *logits) {
  float x[EMI_N_FEATURES];
  for (int i = 0; i < EMI_N_FEATURES; i++) {
    float t = f[i];
    if (EMI_LOG1P[i]) t = log1pf(t > 0 ? t : 0);
    x[i] = (t - EMI_MEAN[i]) / EMI_SCALE[i];
  }
  float h[EMI_N_HIDDEN];
  for (int j = 0; j < EMI_N_HIDDEN; j++) {
    float acc = 0;
    for (int i = 0; i < EMI_N_FEATURES; i++) acc += x[i] * EMI_W1[i][j];
    h[j] = acc * EMI_W1_SCALE + EMI_B1[j];
    if (h[j] < 0) h[j] = 0;
  }
  int best = 0;
  for (int c = 0; c < EMI_N_CLASSES; c++) {
    float acc = 0;
    for (int j = 0; j < EMI_N_HIDDEN; j++) acc += h[j] * EMI_W2[j][c];
    logits[c] = acc * EMI_W2_SCALE + EMI_B2[c];
    if (logits[c] > logits[best]) best = c;
  }
  return best;
}

void report(const char *tag) {
  float f[EMI_N_FEATURES];
  float logits[EMI_N_CLASSES];
  uint32_t t0 = micros();
  compute_features(buf, f);
  uint32_t t1 = micros();
  int c = classify(f, logits);
  uint32_t t2 = micros();

  Serial.print(tag);
  Serial.print(" class=");       Serial.print(EMI_CLASSES[c]);
  Serial.print(" features_us="); Serial.print(t1 - t0);
  Serial.print(" model_us=");    Serial.println(t2 - t1);
  Serial.print("FEAT");
  for (int i = 0; i < EMI_N_FEATURES; i++) { Serial.print(' '); Serial.print(f[i], 6); }
  Serial.println();
  Serial.print("LOGITS");
  for (int k = 0; k < EMI_N_CLASSES; k++) { Serial.print(' '); Serial.print(logits[k], 4); }
  Serial.println();
  if (send_wave && strcmp(tag, "VERIFY") != 0) {
    Serial.print("WAVE");
    for (int i = 0; i < N_SAMPLES; i++) { Serial.print(' '); Serial.print(buf[i]); }
    Serial.println();
  }
}

// Arm as emi_capture.ino's capture_triggered does: rest from one window, then
// sample continuously into buf as a ring until two samples in a row fall
// `depth` below rest after the output was seen high, with PRE_TRIGGER
// samples of history. Then finish the window, unroll the ring so the dip
// sits at PRE_TRIGGER, and classify it. Returns false on timeout.
bool capture_triggered(int depth) {
  capture();
  int32_t rest = rest_of(buf);
  int level = (int)rest - depth;
  Serial.print("ARMED resting="); Serial.print(rest);
  Serial.print(" trig_level="); Serial.println(level);

  uint32_t armed_at = millis();
  uint32_t t0 = micros();
  uint32_t i = 0, first_below = 0;
  int run = 0;
  bool seen_high = false;
  while (true) {
    while ((micros() - t0) < i * INTERVAL_US) {
      // spin
    }
    uint16_t v = analogRead(ADC_PIN);
    buf[i % N_SAMPLES] = v;
    if ((int)v < level) {
      if (run == 0) first_below = i;
      run++;
      if (run >= 2 && seen_high && first_below >= PRE_TRIGGER) break;
    } else {
      run = 0;
      seen_high = true;
    }
    i++;
    if ((i & 1023) == 0 && (millis() - armed_at) > ARM_TIMEOUT_MS) {
      Serial.println("TIMEOUT");
      return false;
    }
  }
  uint32_t start = first_below - PRE_TRIGGER;
  uint32_t last = start + N_SAMPLES - 1;
  for (i = i + 1; i <= last; i++) {
    while ((micros() - t0) < i * INTERVAL_US) {
      // spin
    }
    buf[i % N_SAMPLES] = analogRead(ADC_PIN);
  }
  std::rotate(buf, buf + (start % N_SAMPLES), buf + N_SAMPLES);
  return true;
}

void loop() {
  if (!Serial.available()) return;
  char cmd = Serial.read();
  if (cmd == 'c') {
    while (Serial.available()) Serial.read();
    capture();
    report("RESULT");
  } else if (cmd == 't' || cmd == 'T') {
    delay(20);                          // let the rest of "t150" arrive
    long depth = 0;
    while (Serial.available()) {
      char ch = Serial.read();
      if (ch >= '0' && ch <= '9') depth = depth * 10 + (ch - '0');
    }
    if (capture_triggered(depth > 0 ? (int)depth : TRIG_DEPTH)) report("TRIGGERED");
  } else if (cmd == 'w' || cmd == 'x') {
    while (Serial.available()) Serial.read();
    send_wave = (cmd == 'w');
    Serial.println(send_wave ? "WAVE on" : "WAVE off");
  } else if (cmd == 'k') {
    while (Serial.available()) Serial.read();
    measure_rest_ref();
    Serial.print("rest_ref=");
    Serial.println(rest_ref);
  } else if (cmd == 'v') {
    rest_ref = Serial.parseInt();
    for (int i = 0; i < N_SAMPLES; i++) buf[i] = (uint16_t)Serial.parseInt();
    while (Serial.available()) Serial.read();
    report("VERIFY");
  }
}
