#!/usr/bin/env python3
"""
make_diagrams.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Draws the EMI detector two ways and writes them next to this file:

    schematic.png / .svg          circuit symbols; how it works electrically
    breadboard_layout.png / .svg  top-down view; exactly where each part goes

The breadboard layout reproduces the hole-by-hole wiring table in
docs/HARDWARE.md. If that table changes (for example C_hold),
change the values below and re-run:

    pip install schemdraw matplotlib numpy
    python docs/make_diagrams.py
"""

import os

# Reproducible output: a fixed SVG date and fixed element ids, so
# re-running only changes a file when the drawing itself changes.
os.environ.setdefault("SOURCE_DATE_EPOCH", "0")

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "emi-classifier"
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, Polygon, Rectangle, FancyBboxPatch
import schemdraw
import schemdraw.elements as elm

HERE = os.path.dirname(os.path.abspath(__file__))

# Component values - change these if a part changes.
R_B = "1 MΩ"
R_C = "10 kΩ"
C_IN = "10 nF (103)"
C_HOLD = "10 nF (103)"
R_PULL = "100 kΩ"


# ---------------------------------------------------------------------------
# Schematic
# ---------------------------------------------------------------------------

def xy(p):
    return (float(p[0]), float(p[1]))


def draw_schematic():
    schemdraw.use("matplotlib")
    d = schemdraw.Drawing(show=False)
    d.config(fontsize=11, unit=2.5, lw=1.4)

    Q = d.add(elm.BjtNpn(circle=True).anchor("base").at((0, 0))
              .label("Q1\nBC548", loc="right"))
    qb, qc, qe = xy(Q.base), xy(Q.collector), xy(Q.emitter)

    NC = (qc[0], qc[1] + 1.25)        # collector node
    RAIL = NC[1] + 3.25               # +3.3 V rail
    BN = (-2.25, 0.0)                 # base node
    K = (BN[0] - 3.5, 0.0)            # coil / C_in node
    O = (NC[0] + 4.5, NC[1])          # OUT node

    # --- stage 1: amplifier -------------------------------------------------
    d.add(elm.Line().at(qc).to(NC))
    d.add(elm.Dot().at(NC))
    d.add(elm.Resistor().endpoints((NC[0], RAIL), NC)
          .label(f"R_C\n{R_C}", loc="bottom"))

    d.add(elm.Line().at(qb).to(BN))
    d.add(elm.Dot().at(BN))
    d.add(elm.Line().at(BN).to((BN[0], NC[1])))
    d.add(elm.Resistor().endpoints((BN[0], NC[1]), NC)
          .label(f"R_B  {R_B}\n(sets the bias)", loc="top"))

    d.add(elm.Capacitor().endpoints(K, BN).label(f"C_in\n{C_IN}", loc="top"))
    d.add(elm.Dot().at(K))
    d.add(elm.Inductor2(loops=4).endpoints(K, (K[0], K[1] - 3.0))
          .label("L1  pickup coil\n6 turns, Ø 4 cm\n19 AWG enamelled", loc="bottom"))
    d.add(elm.Ground().at((K[0], K[1] - 3.0)))

    d.add(elm.Line().at(qe).to((qe[0], qe[1] - 0.75)))
    d.add(elm.Ground().at((qe[0], qe[1] - 0.75)))

    # --- stage 2: envelope detector ----------------------------------------
    d.add(elm.Diode().endpoints(NC, O).reverse()
          .label("D1  1N4148\nband (cathode) at collector", loc="bottom"))
    d.add(elm.Dot().at(O))
    d.add(elm.Resistor().endpoints((O[0], RAIL), O)
          .label(f"R_pull\n{R_PULL}", loc="bottom"))
    d.add(elm.Capacitor().endpoints(O, (O[0], O[1] - 3.0))
          .label(f"C_hold\n{C_HOLD}", loc="bottom"))
    d.add(elm.Ground().at((O[0], O[1] - 3.0)))

    d.add(elm.Line().at(O).to((O[0] + 3.0, O[1])))
    d.add(elm.Dot(open=True).at((O[0] + 3.0, O[1]))
          .label("OUT → ESP32 GPIO34 (D34)\nrests high, dips on EMI", loc="right"))

    # --- 3.3 V rail, supply entry and decoupling ---------------------------
    rail_end = O[0] + 7.0
    d.add(elm.Line().at((NC[0], RAIL)).to((rail_end, RAIL)))
    d.add(elm.Dot().at((O[0], RAIL)))
    for x, txt in ((O[0] + 3.5, "100 nF"), (O[0] + 5.5, "10 µF")):
        d.add(elm.Dot().at((x, RAIL)))
        d.add(elm.Capacitor().endpoints((x, RAIL), (x, RAIL - 1.5))
              .label(txt, loc="bottom"))
        d.add(elm.Ground().at((x, RAIL - 1.5)))
    d.add(elm.Dot(open=True).at((rail_end, RAIL))
          .label("+3.3 V\nfrom ESP32 3V3", loc="right"))

    # --- annotations --------------------------------------------------------
    d.add(elm.Label().at(((K[0] + NC[0]) / 2, -4.9))
          .label("STAGE 1 — amplifier", fontsize=12))
    d.add(elm.Label().at((O[0], -4.9))
          .label("STAGE 2 — envelope detector", fontsize=12))
    d.add(elm.Label().at((O[0] + 4.5, RAIL + 1.1))
          .label("rail decoupling, at the breadboard", fontsize=10))
    d.add(elm.Label().at(((K[0] + rail_end) / 2, RAIL + 2.4))
          .label("EMI detector — full schematic", fontsize=15))

    d.save(os.path.join(HERE, "schematic.png"), transparent=False, dpi=200)
    d.save(os.path.join(HERE, "schematic.svg"), transparent=False)


# ---------------------------------------------------------------------------
# Breadboard layout
# ---------------------------------------------------------------------------

COL_Y = {"A": 0.0, "B": 1.0, "C": 2.0, "D": 3.0, "E": 4.0,
         "F": 6.2, "G": 7.2, "H": 8.2, "I": 9.2, "J": 10.2}
RAIL_POS = -2.0          # + rail, next to column A
RAIL_NEG = -2.9          # - rail
TOP_RAILS = (11.9, 12.8)
NROWS = 25

BOARD = "#f3efe4"
CHANNEL = "#e2dccb"
HOLE = "#bdb6a4"
USED = "#1c1c1c"
RED = "#d0312d"
BLUE = "#1f5fbf"
BLACKW = "#262626"
YELLOW = "#e3a500"
GREEN = "#1f9d48"
COPPER = "#b5602a"
LEADC = "#8c8c8c"
BAND = {"brown": "#7b3f00", "black": "#111111", "orange": "#ff8c00",
        "yellow": "#f2d22e", "green": "#2e8b57", "gold": "#c9a227"}


def H(col, row):
    return (float(row), COL_Y[col])


def P(row):
    return (float(row), RAIL_POS)


def N(row):
    return (float(row), RAIL_NEG)


def rect_poly(c, u, L, W):
    u = np.asarray(u, float)
    u = u / np.linalg.norm(u)
    n = np.array([-u[1], u[0]])
    c = np.asarray(c, float)
    return [c + u * L / 2 + n * W / 2, c - u * L / 2 + n * W / 2,
            c - u * L / 2 - n * W / 2, c + u * L / 2 - n * W / 2]


def pin(ax, p):
    ax.add_patch(Rectangle((p[0] - 0.16, p[1] - 0.16), 0.32, 0.32,
                           color=USED, zorder=9))


def wire(ax, pts, color, lw=3.4, z=7, ends=(True, True)):
    """ends: which ends sit in a breadboard hole (drawn as a black square)."""
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=lw, solid_capstyle="round",
            solid_joinstyle="round", zorder=z)
    if ends[0]:
        pin(ax, pts[0])
    if ends[1]:
        pin(ax, pts[-1])


def resistor(ax, p0, p1, bands, L=0.95, W=0.36):
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=LEADC, lw=1.8, zorder=6)
    c = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    u = (p1[0] - p0[0], p1[1] - p0[1])
    ax.add_patch(Polygon(rect_poly(c, u, L, W), closed=True, fc="#e9cc9c",
                         ec="#8a6d3b", lw=0.8, zorder=7))
    u = np.asarray(u, float) / np.linalg.norm(u)
    for frac, colour in zip((-0.30, -0.12, 0.06, 0.30), bands):
        bc = np.asarray(c) + u * frac * L
        ax.add_patch(Polygon(rect_poly(bc, u, 0.08, W), closed=True,
                             fc=BAND[colour], ec="none", zorder=8))
    pin(ax, p0)
    pin(ax, p1)


def disc_cap(ax, p0, p1, text, rx=0.42, ry=0.34, fc="#d9a441"):
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=LEADC, lw=1.8, zorder=6)
    c = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    ax.add_patch(Ellipse(c, 2 * rx, 2 * ry, fc=fc, ec="#8a5a00", lw=0.8,
                         zorder=7))
    ax.text(c[0], c[1], text, ha="center", va="center", fontsize=6.5,
            color="#3a2400", zorder=8, fontweight="bold")
    pin(ax, p0)
    pin(ax, p1)


def label(ax, text, xy_target, xy_text, fs=9):
    ax.annotate(text, xy=xy_target, xytext=xy_text, fontsize=fs,
                ha="center", va="center", zorder=20,
                arrowprops=dict(arrowstyle="-", color="#555555", lw=0.9,
                                shrinkA=0, shrinkB=2),
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#8a8a8a",
                          lw=0.7))


def draw_breadboard():
    fig, ax = plt.subplots(figsize=(17, 12.5))
    ax.set_aspect("equal")
    ax.axis("off")

    # --- board, channel, holes ---------------------------------------------
    ax.add_patch(FancyBboxPatch((-0.6, -3.55), NROWS + 1.2, 16.95,
                                boxstyle="round,pad=0.05,rounding_size=0.4",
                                fc=BOARD, ec="#cfc8b4", lw=1.2, zorder=0))
    ax.add_patch(Rectangle((-0.6, 4.55), NROWS + 1.2, 1.25, fc=CHANNEL,
                           ec="none", zorder=1))
    for row in range(1, NROWS + 1):
        for col, y in COL_Y.items():
            faded = col in "FGHIJ"
            ax.add_patch(Rectangle((row - 0.13, y - 0.13), 0.26, 0.26,
                                   color=HOLE, alpha=0.35 if faded else 1.0,
                                   zorder=2))
        for y, faded in ((RAIL_POS, False), (RAIL_NEG, False),
                         (TOP_RAILS[0], True), (TOP_RAILS[1], True)):
            ax.add_patch(Rectangle((row - 0.13, y - 0.13), 0.26, 0.26,
                                   color=HOLE, alpha=0.35 if faded else 1.0,
                                   zorder=2))
        used = row in (10, 11, 12, 15, 20)
        ax.text(row, 5.5, str(row), ha="center", va="center", fontsize=7.5,
                color=USED if used else "#8a8474",
                fontweight="bold" if used else "normal", zorder=10,
                bbox=dict(boxstyle="round,pad=0.12", fc=CHANNEL, ec="none"))

    for col, y in COL_Y.items():
        a = 0.35 if col in "FGHIJ" else 1.0
        ax.text(0.1, y, col, ha="center", va="center", fontsize=9,
                color="#6d6757", alpha=a, fontweight="bold", zorder=3)
        ax.text(NROWS + 0.9, y, col, ha="center", va="center", fontsize=9,
                color="#6d6757", alpha=a, fontweight="bold", zorder=3)

    for y, colour, sign, a in ((RAIL_POS, RED, "+", 1.0),
                               (RAIL_NEG, BLUE, "−", 1.0),
                               (TOP_RAILS[0], BLUE, "−", 0.35),
                               (TOP_RAILS[1], RED, "+", 0.35)):
        off = 0.42 if y in (RAIL_POS, TOP_RAILS[1]) else -0.42
        if y == TOP_RAILS[0]:
            off = -0.42
        ax.plot([0.5, NROWS + 0.5], [y + off * 0.9, y + off * 0.9],
                color=colour, lw=1.2, alpha=a, zorder=2)
        for x in (0.1, NROWS + 0.9):
            ax.text(x, y, sign, ha="center", va="center", fontsize=12,
                    color=colour, alpha=a, fontweight="bold", zorder=3)

    ax.text(-3.3, RAIL_POS, "+ rail", ha="center", va="center", fontsize=10,
            color=RED, fontweight="bold", zorder=3)
    ax.text(-3.3, RAIL_NEG, "− rail", ha="center", va="center", fontsize=10,
            color=BLUE, fontweight="bold", zorder=3)

    ax.text(7.5, 11.2, "F–J and the top rails are not used",
            ha="center", va="center", fontsize=9, color="#9a9483",
            style="italic", zorder=3)

    # --- Q1 BC548: C-B-E in E10, E11, E12, flat face toward column A --------
    t = np.linspace(0, np.pi, 40)
    body = [(9.62, 4.32), (12.38, 4.32)] + \
        [(11 + 1.38 * np.cos(a), 4.32 + 0.95 * np.sin(a)) for a in t]
    ax.add_patch(Polygon(body, closed=True, fc="#1c1c1c", ec="#000000",
                         zorder=8))
    ax.text(11, 4.72, "BC548", ha="center", va="center", fontsize=7,
            color="white", fontweight="bold", zorder=9)
    for r, letter in ((10, "C"), (11, "B"), (12, "E")):
        ax.plot([r, r], [4.0, 4.32], color=LEADC, lw=1.6, zorder=7)
        pin(ax, H("E", r))
        ax.text(r, 3.5, letter, ha="center", va="center", fontsize=7.5,
                color="#444", fontweight="bold", zorder=9)

    # --- amplifier ---------------------------------------------------------
    resistor(ax, P(10), H("A", 10), ["brown", "black", "orange", "gold"])
    resistor(ax, H("B", 10), H("B", 11), ["brown", "black", "green", "gold"],
             L=0.7, W=0.34)
    wire(ax, [H("A", 12), N(13)], BLUE, lw=3.0)

    # --- coil through C_in --------------------------------------------------
    disc_cap(ax, H("C", 11), H("C", 15), "103")
    coil_c = (15.0, 16.4)
    for k in range(6):
        ax.add_patch(Ellipse(coil_c, 3.6 - 0.12 * k, 1.9 - 0.08 * k,
                             fc="none", ec=COPPER, lw=1.5, zorder=6))
    wire(ax, [(coil_c[0], coil_c[1] - 0.95), H("D", 15)], COPPER, lw=2.2,
         ends=(False, True))
    wire(ax, [(coil_c[0] - 1.8, coil_c[1]), (-1.3, coil_c[1]),
              (-1.3, RAIL_NEG), N(1)], COPPER, lw=2.2, ends=(False, True))

    # --- envelope detector -------------------------------------------------
    p0, p1 = np.array(H("C", 10)), np.array(H("C", 20))
    ctrl = np.array([15.0, 0.9])
    s = np.linspace(0, 1, 60)[:, None]
    arc = (1 - s) ** 2 * p0 + 2 * (1 - s) * s * ctrl + s ** 2 * p1
    ax.plot(arc[:, 0], arc[:, 1], color=LEADC, lw=1.8, zorder=6)
    ax.add_patch(Polygon(rect_poly((15.0, 1.45), (1, 0), 1.6, 0.42),
                         closed=True, fc="#f2b36b", ec="#9a5b12", lw=0.8,
                         alpha=0.95, zorder=7))
    ax.add_patch(Polygon(rect_poly((14.38, 1.45), (1, 0), 0.2, 0.42),
                         closed=True, fc="#111111", ec="none", zorder=8))
    pin(ax, H("C", 10))
    pin(ax, H("C", 20))

    disc_cap(ax, H("A", 20), N(19), "103")
    resistor(ax, P(21), H("B", 20), ["brown", "black", "yellow", "gold"])

    # --- rail decoupling ----------------------------------------------------
    disc_cap(ax, P(5), N(5), "104", rx=0.3, ry=0.26)
    disc_cap(ax, P(7), N(7), "10µ", rx=0.34, ry=0.3, fc="#c9b27a")

    # --- ESP32, off the breadboard, three female-to-male jumpers ------------
    ax.add_patch(FancyBboxPatch((27.6, -4.4), 5.4, 9.4,
                                boxstyle="round,pad=0.05,rounding_size=0.3",
                                fc="#1b2a41", ec="#0d1624", lw=1.2, zorder=4))
    ax.text(30.4, 3.9, "ESP32\nDevKit V1", ha="center", va="center",
            fontsize=11, color="white", fontweight="bold", zorder=5)
    ax.text(30.4, 1.2, "stays OFF the\nbreadboard;\n3 female-to-male\njumpers",
            ha="center", va="center", fontsize=8, color="#c9d4e5", zorder=5)
    for y, name in ((3.0, "D34"), (RAIL_POS, "3V3"), (RAIL_NEG, "GND")):
        ax.add_patch(Rectangle((27.45, y - 0.18), 0.36, 0.36, fc="#d8d8d8",
                               ec="#666", zorder=6))
        ax.text(28.05, y, name, ha="left", va="center", fontsize=9,
                color="white", fontweight="bold", zorder=6)
    ax.text(30.3, -5.1, "never use VIN (5 V)", ha="center", va="center",
            fontsize=8.5, color=RED, fontweight="bold", zorder=5)

    # colours as on the board since the 17 Oct rewiring
    wire(ax, [H("D", 20), (27.45, 3.0)], GREEN, ends=(True, False))
    wire(ax, [P(25), (27.45, RAIL_POS)], RED, ends=(True, False))
    wire(ax, [N(25), (27.45, RAIL_NEG)], YELLOW, ends=(True, False))

    # --- labels --------------------------------------------------------------
    label(ax, "Q1  BC548\nC·B·E in E10·E11·E12\nflat face toward column A",
          (10.6, 5.1), (8.4, 9.4))
    label(ax, f"R_B  {R_B}\nB10 → B11", (10.5, 1.15), (3.2, 7.7))
    label(ax, f"C_in  {C_IN}\nC11 → C15", (13.0, 2.34), (12.7, 7.95))
    label(ax, "D1  1N4148   C10 → C20\nBLACK BAND at C10\n(arches over C_in)",
          (15.4, 1.6), (20.2, 8.6))
    label(ax, "L1 coil: 6 turns, Ø 4 cm\nlead 1 → D15\nlead 2 → any − rail hole\n"
              "sand 1 cm of each lead first", (16.9, 16.4), (21.8, 16.4))
    label(ax, "rail decoupling\n104 + 10 µF\n+ rail → − rail", (6.0, -2.45),
          (3.4, -5.6))
    label(ax, f"R_C  {R_C}\n+ rail → A10", (10.0, -1.0), (8.2, -6.6))
    label(ax, "jumper\nA12 → − rail", (12.5, -1.45), (13.0, -5.6))
    label(ax, f"C_hold  {C_HOLD}\nA20 → − rail", (19.5, -1.45), (17.9, -6.6))
    label(ax, f"R_pull  {R_PULL}\n+ rail → B20", (20.5, -0.5), (23.0, -5.6))

    ax.text(-4.8, 19.4, "EMI detector — breadboard layout", fontsize=17,
            fontweight="bold", ha="left", va="center")
    ax.text(-4.8, 18.6,
            "Holes match the wiring table in docs/HARDWARE.md.  Viewed from "
            "above, with you on the column-A side.",
            fontsize=10, ha="left", va="center", color="#444")
    ax.text(-4.8, -8.1,
            "Wires:  red = 3.3 V    yellow = ground    green = signal to D34"
            "    blue = emitter jumper"
            "    copper = coil leads.        Black squares = holes in use.\n"
            "If your rails are split in the middle, bridge each half with a "
            "jumper.",
            fontsize=9.5, ha="left", va="center", color="#333",
            linespacing=1.6)

    ax.set_xlim(-5.2, 34.2)
    ax.set_ylim(-9.0, 20.2)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "breadboard_layout.png"), dpi=160,
                facecolor="white")
    fig.savefig(os.path.join(HERE, "breadboard_layout.svg"), facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Pickup coil, 3D, drawn to scale (millimetres)
# ---------------------------------------------------------------------------

def _tube(path, radius, n=14):
    """Quads for a round tube along a 3D path, plus each quad's segment."""
    path = np.asarray(path, float)
    T = np.gradient(path, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    N = np.cross(T, [0.0, 0.0, 1.0])
    weak = np.linalg.norm(N, axis=1) < 1e-6
    N[weak] = np.cross(T[weak], [0.0, 1.0, 0.0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    B = np.cross(T, N)
    th = np.linspace(0, 2 * np.pi, n + 1)
    ring = (path[:, None, :]
            + radius * (np.cos(th)[None, :, None] * N[:, None, :]
                        + np.sin(th)[None, :, None] * B[:, None, :]))
    quads = np.stack([ring[:-1, :-1], ring[1:, :-1], ring[1:, 1:],
                      ring[:-1, 1:]], axis=2).reshape(-1, 4, 3)
    seg = np.repeat(np.arange(len(path) - 1), n)
    return quads, path[seg], seg


def _shade(quads, centres, rgb, light=(0.35, -0.75, 0.75)):
    L = np.asarray(light, float) / np.linalg.norm(light)
    normal = quads.mean(axis=1) - centres
    normal /= np.linalg.norm(normal, axis=1)[:, None] + 1e-12
    lam = np.clip(normal @ L, 0, 1)
    k = 0.38 + 0.55 * lam
    return np.clip(rgb * k[:, None] + 0.3 * (lam ** 18)[:, None], 0, 1)


def draw_coil(with_text=True, out=None):
    """Draw the coil. with_text=False draws no text at all and returns where
    each label belongs, for renderers that can shape scripts matplotlib
    cannot (make_coil_telugu.py)."""
    from matplotlib.colors import to_rgb
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    ENAMEL = np.array(to_rgb("#a4522a"))
    BARE = np.array(to_rgb("#f2ae66"))
    TAPE = np.array(to_rgb("#f2c230"))

    R, wire_r, pitch, turns = 20.0, 0.5, 1.05, 6      # 19 AWG is ~1 mm
    zc = pitch * turns / 2

    t = np.linspace(0, turns * 2 * np.pi, 110 * turns)
    helix = np.c_[R * np.cos(t), R * np.sin(t), pitch * t / (2 * np.pi)]
    z_top = helix[-1, 2]

    tw_r, tw_pitch, x0, x1 = 0.55, 9.0, 32.0, 98.0
    xs = np.linspace(x0, x1, 400)
    ph = 2 * np.pi * (xs - x0) / tw_pitch
    a = np.linspace(0, 1, 40)[:, None]
    smooth = a * a * (3 - 2 * a)

    def lead(z_start, phase, side):
        exitp = np.c_[np.linspace(R, R + 5, 20), np.zeros(20),
                      np.full(20, z_start)]
        p0 = exitp[-1]
        p1 = np.array([x0, tw_r * np.cos(phase), zc + tw_r * np.sin(phase)])
        blend = p0 + (p1 - p0) * np.c_[a, smooth, smooth]
        twist = np.c_[xs, tw_r * np.cos(ph + phase),
                      zc + tw_r * np.sin(ph + phase)]
        q1 = np.array([x1 + 14, side * 9.0, zc])
        split = twist[-1] + (q1 - twist[-1]) * np.c_[a, smooth, smooth]
        tail = np.c_[np.linspace(x1 + 14, x1 + 27, 30), np.full(30, side * 9.0),
                     np.full(30, zc)]
        return np.vstack([exitp, blend[1:], twist[1:], split[1:], tail[1:]])

    quads, colours = [], []

    q, c, seg = _tube(helix, wire_r)
    quads.append(q)
    colours.append(np.c_[_shade(q, c, np.tile(ENAMEL, (len(q), 1))),
                         np.ones(len(q))])

    for z_start, phase, side in ((0.0, 0.0, -1), (z_top, np.pi, 1)):
        path = lead(z_start, phase, side)
        q, c, seg = _tube(path, wire_r)
        mid_x = (path[seg, 0] + path[seg + 1, 0]) / 2
        rgb = np.where((mid_x > x1 + 17)[:, None], BARE, ENAMEL)
        quads.append(q)
        colours.append(np.c_[_shade(q, c, rgb), np.ones(len(q))])

    # three strips of tape across the turns
    for ang in np.radians([70, 190, 310]):
        th = np.linspace(ang - 0.15, ang + 0.15, 6)
        rr = R + wire_r + 0.2
        for j in range(5):
            quad = np.array([
                [rr * np.cos(th[j]), rr * np.sin(th[j]), -1.4],
                [rr * np.cos(th[j + 1]), rr * np.sin(th[j + 1]), -1.4],
                [rr * np.cos(th[j + 1]), rr * np.sin(th[j + 1]), z_top + 1.4],
                [rr * np.cos(th[j]), rr * np.sin(th[j]), z_top + 1.4]])
            centre = np.array([0.0, 0.0, quad[:, 2].mean()])
            quads.append(quad[None])
            colours.append(np.c_[_shade(quad[None], centre[None], TAPE[None]),
                                 [0.92]])

    quads = np.concatenate(quads)
    colours = np.concatenate(colours)

    fig = plt.figure(figsize=(16, 10), dpi=150)   # display px == saved px
    ax = fig.add_axes([0.0, 0.2, 1.0, 0.72], projection="3d")
    # 3D axes draw inside a centred square and clip to it; the coil and its
    # leads are wider than tall, so let them run past the square's edges.
    coil = Poly3DCollection(quads, facecolors=colours, edgecolors=colours,
                            linewidths=0.15)
    coil.set_clip_on(False)
    ax.add_collection3d(coil)
    ax.set_xlim(-24, 128)
    ax.set_ylim(-24, 24)
    ax.set_zlim(-4, 10)
    azim = -62
    ax.set_box_aspect((152, 48, 14), zoom=1.55)
    ax.view_init(elev=32, azim=azim)
    ax.set_axis_off()

    # Diameter bar across the top, perpendicular to the line of sight so it
    # reads as a flat horizontal dimension.
    ink = "#2b2b2b"
    u = np.array([np.cos(np.radians(azim + 90)), np.sin(np.radians(azim + 90))])
    zt = z_top + 2.5
    ax.plot([-R * u[0], R * u[0]], [-R * u[1], R * u[1]], [zt, zt],
            color=ink, lw=1.2, clip_on=False)
    for s in (-1, 1):
        ax.plot([s * R * u[0]] * 2, [s * R * u[1]] * 2, [zt - 1.0, zt + 1.0],
                color=ink, lw=1.2, clip_on=False)

    # Labels are placed in screen space so they never sit on the wire.
    from mpl_toolkits.mplot3d import proj3d
    fig.canvas.draw()

    def note(p3, text, dx, dy, ha="center", arrow=True, bold=False):
        x2, y2, _ = proj3d.proj_transform(*p3, ax.get_proj())
        ax.annotate(text, xy=(x2, y2), xytext=(dx, dy),
                    textcoords="offset points", ha=ha, va="center",
                    annotation_clip=False,
                    fontsize=11, color=ink,
                    fontweight="bold" if bold else "normal",
                    arrowprops=(dict(arrowstyle="-", color="#777", lw=0.9)
                                if arrow else None))

    ang = np.radians(310)
    # key, 3D anchor, text offset (points), alignment, leader line, bold
    specs = [
        ("dia", (0, 0, zt), 0, 22, "center", False, True),
        ("turns", (-R * u[0], -R * u[1], zc), -95, 0, "center", True, False),
        ("tape", (R * np.cos(ang), R * np.sin(ang), -1.0), -10, -62,
         "center", True, False),
        ("leads", (66, tw_r, zc), -30, 58, "center", True, False),
        ("bare", (x1 + 22, 9.0, zc), 30, 58, "center", True, False),
        ("d15", (x1 + 27, -9.0, zc), 12, -4, "left", False, True),
        ("rail", (x1 + 27, 9.0, zc), 12, 4, "left", False, True),
    ]
    english = {
        "dia": "Ø 4 cm",
        "turns": "6 turns, side by side\n≈ 6 mm tall",
        "tape": "tape across the turns\nin 3 places",
        "leads": "leads ≈ 10 cm each,\nloosely twisted together",
        "bare": "last 1 cm sanded bare:\nbright copper all round",
        "d15": "one lead → D15",
        "rail": "other lead → − rail (blue line)",
    }
    positions = []
    for key, p3, dx, dy, ha, arrow, bold in specs:
        if with_text:
            note(p3, english[key], dx, dy, ha=ha, arrow=arrow, bold=bold)
            continue
        # Text-free mode: report where each label belongs, in pixels of the
        # saved image (origin top-left), so another renderer can place it.
        x2, y2, _ = proj3d.proj_transform(*p3, ax.get_proj())
        px, py = ax.transData.transform((x2, y2))
        k = fig.dpi / 72.0
        height = fig.bbox.height
        positions.append(dict(key=key, ax=px, ay=height - py,
                              tx=px + dx * k, ty=height - (py + dy * k),
                              ha=ha, arrow=arrow, bold=bold))

    if not with_text:
        fig.savefig(out, dpi=150, facecolor="white")
        plt.close(fig)
        return positions

    fig.text(0.03, 0.955, "L1 pickup coil — what it should look like",
             fontsize=18, fontweight="bold")
    fig.text(0.03, 0.918,
             "6 turns of the 19 AWG enamelled wire, 4 cm across, with two "
             "10 cm leads.  Drawn to scale.  Either lead can go to either "
             "hole.", fontsize=11, color="#444")
    fig.text(0.03, 0.035,
             "How to make it\n"
             "1   Wrap 6 turns, side by side, around something about 4 cm "
             "across: a tape roll or a small bottle.\n"
             "2   Leave about 10 cm of wire at the start and at the end, "
             "both coming off the coil at the same point.\n"
             "3   Slide it off and tape across the turns in 3 places so it "
             "keeps its shape.\n"
             "4   Twist the two leads loosely together, leaving the last 2 cm "
             "apart. Then only the coil picks up EMI, not the loose leads,\n"
             "     so the sensor is the same size in every capture.\n"
             "5   Sand the last 1 cm of each lead, rotating as you go, until "
             "it is bright copper all round. Meter on continuity, one probe\n"
             "     on each end: it must beep. The clear varnish on the rest of "
             "the wire is insulation and conducts nothing.\n"
             "6   For data collection, tape the coil to the desk so it sits "
             "in the same place and orientation for every capture.",
             fontsize=10.5, color="#222", linespacing=1.55, va="bottom")

    fig.savefig(out or os.path.join(HERE, "coil_3d.png"), dpi=150,
                facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    draw_schematic()
    draw_breadboard()
    draw_coil()
    print("wrote schematic, breadboard_layout and coil_3d to", HERE)
