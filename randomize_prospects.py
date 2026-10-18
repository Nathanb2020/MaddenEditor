#!/usr/bin/env python3
"""
Stage 1: randomize ratings and mapped weights for the upcoming draft class.

What it touches (draft prospects only, ContractStatus == 'Draft'):
  - current ratings, redrawn from bell curves inside your min/max ranges
  - the matching Original...Rating twin of every rating it changes
  - OverallRating (estimated from a formula fitted to the players in the save)
  - OverallGrade0-3 (scouting grades, shifted with the new overall)
  - Weight for HB, TE, EDGE, and LB only, based on the new speed rating and height

What it does NOT touch: other positions' weights, heights, draft order/ranks, dev traits,
K/P/LS ratings, or anyone who is not a draft prospect. Fullback ratings are randomized
inside the normal rating window because the source document provides no FB-specific ranges.

Usage:
  python randomize_prospects.py [SAVE] [--output PATH] [--seed N] [--dry-run]

Needs: numpy (pip install numpy), plus export.mjs / apply.mjs in this folder.
The original save is never modified; output defaults to SAVE-STAGE1.
"""
import argparse
import csv
import json
import math
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, mean, median

try:
    import numpy as np
except ImportError:
    sys.exit("This script needs numpy. Run:  pip install numpy")

# =============================================================== CONFIG
# Edit this section to change the rules. Everything below it is machinery.

DEFAULT_SAVE = "CAREER-PAHNTERS-AUTOSAVE"
SCRIPT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# Typical actual weights (lb) from the speed-to-weight map, converted to the
# player's stored speed/weight scale below. These are medians by speed band.
# Bands beyond the listed endpoints use the nearest endpoint value.
WEIGHT_GROUP_OF = {
    "HB": "HB", "TE": "TE", "LE": "EDGE", "RE": "EDGE",
    "MLB": "LB", "LOLB": "LB", "ROLB": "LB",
}
WEIGHT_BY_SPEED = {
    "HB": [(85, 89, 214), (90, 94, 206)],
    "TE": [(75, 79, 248), (80, 84, 253), (85, 89, 254)],
    "EDGE": [(60, 69, 298), (70, 74, 296), (75, 79, 268), (80, 89, 263)],
    "LB": [(75, 79, 241), (80, 89, 234), (90, 94, 240)],
}
# Height adjusts the speed-map target by 3 lb per inch from the group's typical
# height. The reference heights are the medians in this save's active roster.
WEIGHT_REFERENCE_HEIGHT = {"HB": 71, "TE": 76, "EDGE": 76, "LB": 73}
WEIGHT_HEIGHT_SLOPE = 3.0
# Preserve realistic player-to-player variation around the map medians.
WEIGHT_RESIDUAL_SD = {"HB": 12, "TE": 10, "EDGE": 9, "LB": 8}
WEIGHT_LIMITS_LB = {"HB": (180, 260), "TE": (220, 285),
                    "EDGE": (240, 310), "LB": (210, 270)}
WEIGHT_ACTIVE_STATUSES = {"Signed", "FreeAgent", "PracticeSquad"}

# Attributes that are not real skill ratings: never touched.
EXCLUDED = {"OverallRating", "ConfidenceRating", "PersonalityRating", "RunningStyleRating"}

UNLISTED_WINDOW = 10        # attributes with no range: old value +/- this
OFFENSE_COD_CAP = 89        # max ChangeOfDirectionRating for offensive prospects
FIRST_ROUND_QB_FLOOR = {"ThrowAccuracyShortRating": 70, "ThrowAccuracyMidRating": 70}

# position -> group
GROUP_OF = {
    "QB": "QB", "HB": "HB", "FB": "FB", "WR": "WR", "TE": "TE",
    "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL",
    "DT": "DT", "LE": "EDGE", "RE": "EDGE",
    "MLB": "LB", "LOLB": "LB", "ROLB": "LB",
    "CB": "CB", "FS": "S", "SS": "S",
}
OFFENSE_GROUPS = {"QB", "HB", "FB", "WR", "TE", "OL"}

# (min, max) per group. The bell curve spans the range: the floor and ceiling
# are the two tails of the curve (nothing is piled up on them).
RANGES = {
    "QB": {
        "ThrowPowerRating": (85, 99), "ThrowAccuracyShortRating": (60, 86),
        "ThrowAccuracyMidRating": (58, 81), "ThrowAccuracyDeepRating": (59, 84),
        "ThrowOnTheRunRating": (66, 85), "ThrowUnderPressureRating": (55, 80),
        "SpeedRating": (82, 99), "AccelerationRating": (82, 99),
        "AwarenessRating": (59, 76),
    },
    "HB": {"SpeedRating": (85, 99), "AccelerationRating": (85, 99),
           "CarryingRating": (75, 99)},
    "TE": {"SpeedRating": (78, 94)},
    "WR": {"SpeedRating": (88, 99)},
    "OL": {
        "PassBlockFinesseRating": (70, 85), "PassBlockPowerRating": (70, 85),
        "PassBlockRating": (70, 90), "RunBlockFinesseRating": (70, 85),
        "RunBlockPowerRating": (70, 85), "RunBlockRating": (70, 90),
        "StrengthRating": (85, 99), "ImpactBlockingRating": (75, 99),
        "AwarenessRating": (65, 80), "SpeedRating": (65, 80),
        "AccelerationRating": (65, 85), "AgilityRating": (65, 85),
    },
    "DT": {"BlockSheddingRating": (75, 88), "FinesseMovesRating": (65, 75),
           "PowerMovesRating": (65, 75)},
    "EDGE": {"SpeedRating": (78, 94), "AccelerationRating": (78, 97),
             "BlockSheddingRating": (75, 88), "FinesseMovesRating": (60, 75),
             "PowerMovesRating": (60, 75)},
    "LB": {"SpeedRating": (84, 93), "AccelerationRating": (84, 96),
           "PlayRecognitionRating": (70, 90), "PursuitRating": (75, 99),
           "ChangeOfDirectionRating": (75, 93), "ManCoverageRating": (60, 70),
           "ZoneCoverageRating": (65, 80)},
    "CB": {"SpeedRating": (89, 99), "AccelerationRating": (89, 99),
           "ChangeOfDirectionRating": (89, 99), "ManCoverageRating": (70, 85),
           "ZoneCoverageRating": (70, 85), "PressRating": (70, 85)},
    "S": {"SpeedRating": (89, 99), "AccelerationRating": (89, 99),
          "ChangeOfDirectionRating": (85, 99), "PlayRecognitionRating": (70, 90),
          "PursuitRating": (75, 99), "ManCoverageRating": (65, 85),
          "ZoneCoverageRating": (65, 85)},
}

# (group, attribute) -> target mean for the right-skewed bell curve.
SKEW_MEAN = {
    ("QB", "SpeedRating"): 86.0,
    ("HB", "SpeedRating"): 91.0,
    ("TE", "SpeedRating"): 85.0,
}
# A small explicit top-end share keeps elite HB speed ratings from disappearing
# into the thin tail. The skew curve's mean is adjusted so the combined mean
# remains at the target above.
SKEW_MAX_CHANCE = {("HB", "SpeedRating"): 0.03}

# Ratings computed from other ratings (fitted from the save). If the fit is
# poor the attribute falls back to the normal old +/- 10 window.
DERIVED = {
    "QB": {"ThrowAccuracyRating": ["ThrowAccuracyShortRating", "ThrowAccuracyMidRating",
                                   "ThrowAccuracyDeepRating"]},
}

# Skill "leans". Each cluster is a hidden per-player dial (about N(0,1)); an
# attribute moves up with the dial (+1) or down with it (-1). This is what makes
# a player a run-blocker vs a pass-blocker, a receiving back vs a power back,
# an unpolished-but-athletic QB, and so on.  group -> cluster -> {attr: sign}
REC_ATTRS = ["CatchingRating", "CatchInTrafficRating", "SpectacularCatchRating",
             "ShortRouteRunningRating", "MediumRouteRunningRating",
             "DeepRouteRunningRating", "ReleaseRating"]
PASSPRO = ["PassBlockRating", "PassBlockPowerRating", "PassBlockFinesseRating"]
RUNBLK = ["RunBlockRating", "RunBlockPowerRating", "RunBlockFinesseRating",
          "LeadBlockRating", "ImpactBlockingRating"]

CLUSTERS = {
    "QB": {
        "physical": {"ThrowPowerRating": 1, "SpeedRating": 1, "AccelerationRating": 1},
        "polish": {"ThrowAccuracyShortRating": 1, "ThrowAccuracyMidRating": 1,
                   "ThrowAccuracyDeepRating": 1, "ThrowOnTheRunRating": 1,
                   "ThrowUnderPressureRating": 1, "AwarenessRating": 1,
                   "PlayActionRating": 1},
    },
    "HB": {
        "receiving": {a: 1 for a in REC_ATTRS},
        "pass_pro": {a: 1 for a in PASSPRO},
        "power_vs_elusive": {"TruckingRating": 1, "BreakTackleRating": 1, "StiffArmRating": 1,
                             "StrengthRating": 1, "JukeMoveRating": -1, "SpinMoveRating": -1,
                             "AgilityRating": -1, "ChangeOfDirectionRating": -1},
    },
    "WR": {
        "hands": {"CatchingRating": 1, "CatchInTrafficRating": 1, "SpectacularCatchRating": 1},
        "routes": {"ShortRouteRunningRating": 1, "MediumRouteRunningRating": 1,
                   "DeepRouteRunningRating": 1, "ReleaseRating": 1},
        "yac": {"BreakTackleRating": 1, "JukeMoveRating": 1, "SpinMoveRating": 1,
                "CarryingRating": 1},
    },
    "TE": {
        "receive_vs_block": {**{a: 1 for a in REC_ATTRS},
                             **{a: -1 for a in PASSPRO + RUNBLK + ["StrengthRating"]}},
    },
    "OL": {
        "pass_vs_run": {**{a: 1 for a in PASSPRO}, **{a: -1 for a in RUNBLK}},
        "power_vs_finesse": {"PassBlockPowerRating": 1, "RunBlockPowerRating": 1,
                             "PassBlockFinesseRating": -1, "RunBlockFinesseRating": -1},
    },
    "DT": {"finesse_vs_power": {"FinesseMovesRating": 1, "SpinMoveRating": 1,
                                "PowerMovesRating": -1}},
    "EDGE": {"finesse_vs_power": {"FinesseMovesRating": 1, "SpinMoveRating": 1,
                                  "PowerMovesRating": -1}},
}

# (talent loading, cluster loading) -- how strongly the overall talent dial and
# the cluster dial drive an attribute. The rest is per-attribute noise.
DEFAULT_LOADING = (0.50, 0.55)
LOADINGS = {
    ("QB", "physical"): (0.25, 0.75),
    ("OL", "pass_vs_run"): (0.50, 0.50),
    ("OL", "power_vs_finesse"): (0.50, 0.25),   # kept small on purpose
    ("TE", "receive_vs_block"): (0.40, 0.65),
}
OL_WEIGHT_LEAN = 0.6   # how much the weight of a lineman steers power vs finesse

# =========================================================== MACHINERY
ND = NormalDist()
_A, _B = ND.cdf(-2.0), ND.cdf(2.0)


def trunc2(s):
    """Standard-normal score -> bell-shaped value in [-2, 2] (no clamping)."""
    u = ND.cdf(s)
    u = min(max(u, 1e-12), 1 - 1e-12)
    return ND.inv_cdf(_A + u * (_B - _A))


def solve_skew_k(target_frac, n=2001):
    """Find k so the convex map y -> (e^(k y)-1)/(e^k-1) gives the target mean."""
    xs = [-2 + 4 * i / (n - 1) for i in range(n)]
    ws = [ND.pdf(x) for x in xs]
    wsum = sum(ws)

    def mean_for(k):
        return sum(w * (math.exp(k * (x / 4 + 0.5)) - 1) / (math.exp(k) - 1)
                   for x, w in zip(xs, ws)) / wsum

    lo, hi = 1e-3, 40.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if mean_for(mid) > target_frac:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def sample_value(s, lo, hi, k=None):
    if hi <= lo:
        return int(lo)
    y = trunc2(s) / 4.0 + 0.5
    if k:
        y = (math.exp(k * y) - 1) / (math.exp(k) - 1)
    return int(round(lo + (hi - lo) * y))


def clamp99(v):
    return max(0, min(99, int(round(v))))


def fit_linear(rows, feats, target, alpha=20.0):
    """Ridge regression with intercept. Returns model dict incl. holdout MAE."""
    X = np.array([[r[f] for f in feats] for r in rows], dtype=float)
    y = np.array([r[target] for r in rows], dtype=float)

    def solve(Xs, ys):
        xm, ym = Xs.mean(0), ys.mean()
        Xc = Xs - xm
        w = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(Xs.shape[1]), Xc.T @ (ys - ym))
        return w, ym - xm @ w

    idx = np.arange(len(rows))
    hold = idx % 5 == 0                      # deterministic 20% holdout
    w, b = solve(X[~hold], y[~hold])
    mae = float(np.mean(np.abs(X[hold] @ w + b - y[hold]))) if hold.any() else float("nan")
    w, b = solve(X, y)
    return {"w": w, "b": float(b), "feats": feats, "mae": mae, "n": len(rows)}


def predict(model, ratings):
    x = np.array([ratings[f] for f in model["feats"]], dtype=float)
    return clamp99(float(x @ model["w"] + model["b"]))


def mapped_weight_lb(group, speed, height, rng):
    """Map speed to a position-specific weight, then adjust for height."""
    bands = WEIGHT_BY_SPEED[group]
    target = next((weight for lo, hi, weight in bands if lo <= speed <= hi), None)
    if target is None:
        target = bands[0][2] if speed < bands[0][0] else bands[-1][2]
    target += WEIGHT_HEIGHT_SLOPE * (height - WEIGHT_REFERENCE_HEIGHT[group])
    target += rng.gauss(0, WEIGHT_RESIDUAL_SD[group])
    lo, hi = WEIGHT_LIMITS_LB[group]
    return int(round(min(max(target, lo), hi)))


def _ols(X, y, alpha=1e-3):
    xm, ym = X.mean(0), y.mean()
    Xc = X - xm
    w = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(X.shape[1]), Xc.T @ (y - ym))
    return w, float(ym - xm @ w)


def _omp_path(X, y, max_k):
    """Greedy forward selection. Returns [(columns, weights, intercept)] for k=1..max_k."""
    n, p = X.shape
    sd = X.std(0)
    sel, path = [], []
    resid = y - y.mean()
    for _ in range(min(max_k, p)):
        rc = resid - resid.mean()
        rn = float(np.linalg.norm(rc))
        if rn < 1e-9:
            break
        best, best_c = None, 0.0
        for j in range(p):
            if j in sel or sd[j] < 1e-9:
                continue
            xc = X[:, j] - X[:, j].mean()
            c = abs(float(xc @ rc)) / (float(np.linalg.norm(xc)) * rn + 1e-12)
            if c > best_c:
                best, best_c = j, c
        if best is None:
            break
        sel.append(best)
        w, b = _ols(X[:, sel], y)
        resid = y - (X[:, sel] @ w + b)
        path.append((list(sel), w, b))
    return path


def fit_sparse(rows, feats, target, max_k=16, trim=0.10):
    """Sparse linear fit: picks the few ratings that really drive the overall.
    Two passes; after each, the worst 10% of rows (junk/stale records) are dropped
    so they cannot distort which ratings get picked."""
    X = np.array([[r[f] for f in feats] for r in rows], dtype=float)
    y = np.array([r[target] for r in rows], dtype=float)
    val = np.arange(len(y)) % 5 == 1
    keep = np.ones(len(y), dtype=bool)
    sel, w, b = [], None, 0.0
    for _ in range(2):
        tr, va = keep & ~val, keep & val
        path = _omp_path(X[tr], y[tr], max_k)
        errs = [float(np.median(np.abs(X[va][:, s] @ pw + pb - y[va]))) for s, pw, pb in path]
        sel = path[int(np.argmin(errs))][0]
        w, b = _ols(X[keep][:, sel], y[keep])
        res = np.abs(X[:, sel] @ w + b - y)
        keep = res <= np.quantile(res[keep], 1 - trim)
    w, b = _ols(X[keep][:, sel], y[keep])
    full = np.zeros(len(feats))
    full[sel] = w
    return {"w": full, "b": b, "feats": feats, "sel": [feats[i] for i in sel]}


def abs_errors(model, rows, target):
    X = np.array([[r[f] for f in model["feats"]] for r in rows], dtype=float)
    y = np.array([r[target] for r in rows], dtype=float)
    return np.abs(X @ model["w"] + model["b"] - y)


def fit_position(pos, by_pos, players, feats):
    """Fit the overall formula for one position, from its own players or from its
    whole position group, whichever predicts that position's holdout better."""
    own = by_pos.get(pos, [])
    grp = [q for q in players if GROUP_OF.get(q["Position"]) == GROUP_OF[pos]]
    hold = {id(r) for i, r in enumerate(own) if i % 5 == 0}
    own_ho = [r for r in own if id(r) in hold]
    cands = {}
    if len(own) - len(hold) >= 30:
        cands["own"] = [r for r in own if id(r) not in hold]
    if len(grp) > len(own):
        cands["group"] = [r for r in grp if id(r) not in hold]
    best = None
    for name, tr in cands.items():
        if len(tr) < 30 or not own_ho:
            continue
        e = abs_errors(fit_sparse(tr, feats, "OverallRating"), own_ho, "OverallRating")
        if best is None or np.median(e) < np.median(best[2]):
            best = (name, tr, e)
    if best is None:
        return None
    model = fit_sparse(own if best[0] == "own" else grp, feats, "OverallRating")
    errs = best[2]
    order = np.argsort(-errs)[:3]
    model.update({"source": best[0], "n": len(own), "mae": float(errs.mean()),
                  "median": float(np.median(errs)),
                  "worst": [(own_ho[i], float(errs[i])) for i in order]})
    return model


def run_node(*args):
    script = SCRIPT_DIR / args[0]
    subprocess.run(
        ["node", str(script), *args[1:]], check=True, stdout=sys.stdout, stderr=sys.stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


# ================================================================ MAIN
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=DEFAULT_SAVE)
    ap.add_argument("--output", help="write the new save to this path")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="build the edits and the report but do not write a save")
    ap.add_argument("--skip-export", action="store_true", help="reuse players.json (testing)")
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(1, 10 ** 9)
    rng = random.Random(seed)
    out_save = args.output or args.save + "-STAGE1"
    print("Seed: %d  (rerun with --seed %d to reproduce this exact class)" % (seed, seed))

    if not args.skip_export:
        run_node("export.mjs", args.save, "players.json")
    players = json.load(open("players.json"))
    keys = set(players[0].keys())
    rating_keys = sorted(k for k in keys if k.endswith("Rating")
                         and not k.startswith("Original") and k not in EXCLUDED)

    # ---- overall-rating formulas, fitted from every player in the save
    by_pos = defaultdict(list)
    for p in players:
        by_pos[p["Position"]].append(p)
    models = {}
    print("\nOverall-rating formula fit (typical = median error on players held out, in rating points):")
    for pos in sorted(GROUP_OF):
        m = fit_position(pos, by_pos, players, rating_keys)
        if m is None:
            print("  %-5s too few players to fit: skipped" % pos)
            continue
        models[pos] = m
        weak = m["median"] > 1.5
        print("  %-5s n=%-4d from %-5s typical %.2f  average %.2f  (%d ratings)%s" %
              (pos, m["n"], m["source"], m["median"], m["mae"], len(m["sel"]),
               "   <-- WARNING: weak fit" if weak else ""))
        if weak:
            print("        ratings used: " + ", ".join(s.replace("Rating", "") for s in m["sel"]))
            for r, e in m["worst"]:
                print("        worst miss: %s %s (%s) overall %s, off by %.0f" %
                      (r["FirstName"], r["LastName"], r.get("ContractStatus"), r["OverallRating"], e))

    derived = {}
    for group, targets in DERIVED.items():
        rows = [p for p in players if GROUP_OF.get(p["Position"]) == group]
        for target, inputs in targets.items():
            if target not in keys or any(i not in keys for i in inputs) or len(rows) < 30:
                continue
            m = fit_linear(rows, inputs, target, alpha=1.0)
            ok = m["mae"] <= 2.0
            print("  derived %s.%s from %d ratings: MAE %.2f -> %s" %
                  (group, target, len(inputs), m["mae"], "used" if ok else "NOT used (normal window instead)"))
            if ok:
                derived[(group, target)] = m

    # ---- per-attribute loadings
    skew_k = {}
    for ga, target_mean in SKEW_MEAN.items():
        lo, hi = RANGES[ga[0]][ga[1]]
        max_chance = SKEW_MAX_CHANCE.get(ga, 0)
        curve_mean = (target_mean - max_chance * hi) / (1 - max_chance)
        skew_k[ga] = solve_skew_k((curve_mean - lo) / (hi - lo))

    def loadings(group, attr):
        lt, cl = DEFAULT_LOADING[0], []
        for cname, members in CLUSTERS.get(group, {}).items():
            if attr in members:
                lt_c, lc = LOADINGS.get((group, cname), DEFAULT_LOADING)
                lt = lt_c
                cl.append((cname, members[attr], lc))
        return lt, cl

    # ---- who gets edited
    prospects = [p for p in players if p.get("ContractStatus") == "Draft"]
    targets = [p for p in prospects if p["Position"] in GROUP_OF]
    skipped = [p for p in prospects if p["Position"] not in GROUP_OF]
    print("\nDraft prospects: %d (editing %d; leaving %d K/P/LS untouched)" %
          (len(prospects), len(targets), len(skipped)))

    ol_weights = [p.get("Weight", 0) for p in targets if GROUP_OF[p["Position"]] == "OL"]
    w_mu = mean(ol_weights) if ol_weights else 0
    w_sd = (sum((w - w_mu) ** 2 for w in ol_weights) / len(ol_weights)) ** 0.5 if ol_weights else 1
    w_sd = w_sd or 1

    weight_targets = [p for p in prospects if p["Position"] in WEIGHT_GROUP_OF]
    bad_body_data = [p for p in weight_targets
                     if not isinstance(p.get("Weight"), (int, float))
                     or not isinstance(p.get("Height"), (int, float))
                     or not 60 <= p.get("Height", 0) <= 84]
    if bad_body_data:
        sys.exit("STOP: selected draft prospects need numeric Weight and inch-based Height fields. "
                 "No edits were written.")
    weight_refs = [p["Weight"] for p in players
                   if p.get("Position") in WEIGHT_GROUP_OF
                   and p.get("ContractStatus") in WEIGHT_ACTIVE_STATUSES
                   and isinstance(p.get("Weight"), (int, float))]
    if not weight_refs:
        sys.exit("STOP: could not determine the save's stored weight units. No edits were written.")
    weight_offset = 160 if median(weight_refs) < 120 else 0
    if not 180 <= median(weight_refs) + weight_offset <= 360:
        sys.exit("STOP: weight values are outside the expected pounds / pounds-minus-160 range. "
                 "No edits were written.")
    weight_rng = random.Random(seed ^ 0x5A17C3)

    edits, new_players = [], {}
    for p in targets:
        group = GROUP_OF[p["Position"]]
        talent = rng.gauss(0, 1)
        z = {c: rng.gauss(0, 1) for c in CLUSTERS.get(group, {})}
        if group == "OL":
            wz = (p.get("Weight", w_mu) - w_mu) / w_sd
            z["power_vs_finesse"] = (OL_WEIGHT_LEAN * wz +
                                     math.sqrt(1 - OL_WEIGHT_LEAN ** 2) * rng.gauss(0, 1))
        first_round_qb = group == "QB" and p.get("PLYR_DRAFTROUND") == 1

        new = {}
        for attr in rating_keys:
            if (group, attr) in derived:
                continue
            old = p[attr]
            rng_ = RANGES.get(group, {}).get(attr)
            if rng_:
                lo, hi = rng_
                if first_round_qb and attr in FIRST_ROUND_QB_FLOOR:
                    lo = max(lo, FIRST_ROUND_QB_FLOOR[attr])
            else:
                lo, hi = max(0, old - UNLISTED_WINDOW), min(99, old + UNLISTED_WINDOW)
            if attr == "ChangeOfDirectionRating" and group in OFFENSE_GROUPS:
                hi = min(hi, OFFENSE_COD_CAP)
                lo = min(lo, hi)
            lt, cl = loadings(group, attr)
            sq = lt ** 2 + sum(lc ** 2 for _, _, lc in cl)
            r = math.sqrt(max(0.05, 1 - sq))
            s = lt * talent + sum(sg * lc * z[c] for c, sg, lc in cl) + r * rng.gauss(0, 1)
            s /= math.sqrt(lt ** 2 + sum(lc ** 2 for _, _, lc in cl) + r ** 2)
            max_chance = SKEW_MAX_CHANCE.get((group, attr), 0)
            if max_chance and rng.random() < max_chance:
                new[attr] = hi
            else:
                new[attr] = sample_value(s, lo, hi, skew_k.get((group, attr)))
        for (g, attr), m in derived.items():
            if g == group:
                new[attr] = predict(m, new)

        full = {**{k: p[k] for k in rating_keys}, **new}
        new_ovr = (predict(models[p["Position"]], full)
                   if p["Position"] in models else p["OverallRating"])
        changes = {k: v for k, v in new.items() if v != p[k]}
        for attr, v in new.items():                       # Original twins
            tw = "Original" + attr
            if tw in p:
                nv = clamp99(v + (p[tw] - p[attr]))
                if nv != p[tw]:
                    changes[tw] = nv
        if new_ovr != p["OverallRating"]:
            changes["OverallRating"] = new_ovr
        if p.get("OriginalOverallRating") == p["OverallRating"] and new_ovr != p["OriginalOverallRating"]:
            changes["OriginalOverallRating"] = new_ovr
        for i in range(4):                                # scouting grades
            g = "OverallGrade%d" % i
            if g in p and p[g] > 0:
                nv = clamp99(new_ovr + (p[g] - p["OverallRating"]))
                if nv != p[g]:
                    changes[g] = nv
        if p["Position"] in WEIGHT_GROUP_OF:
            weight_group = WEIGHT_GROUP_OF[p["Position"]]
            speed = new.get("SpeedRating", p["SpeedRating"])
            weight_lb = mapped_weight_lb(weight_group, speed, p["Height"], weight_rng)
            stored_weight = weight_lb - weight_offset
            if stored_weight != p["Weight"]:
                changes["Weight"] = stored_weight
        if changes:
            edits.append({"row": p["row"], **changes})
        new_players[p["row"]] = {**p, **changes}

    json.dump(edits, open("edits.json", "w"))
    n_fields = sum(len(e) - 1 for e in edits)

    # =================================================== report
    print("\n" + "=" * 64)
    print("REPORT  (%d players, %d field changes)" % (len(edits), n_fields))
    print("=" * 64)
    print("\nOverall rating by group (before -> after, new min/max):")
    for group in ["QB", "HB", "WR", "TE", "OL", "DT", "EDGE", "LB", "CB", "S"]:
        grp = [p for p in targets if GROUP_OF[p["Position"]] == group]
        if not grp:
            continue
        old = [p["OverallRating"] for p in grp]
        nw = [new_players[p["row"]]["OverallRating"] for p in grp]
        print("  %-5s n=%-3d  %.1f -> %.1f   (%d to %d)" %
              (group, len(grp), mean(old), mean(nw), min(nw), max(nw)))

    viol = 0
    edge = defaultdict(lambda: [0, 0, 0])
    for p in targets:
        group = GROUP_OF[p["Position"]]
        q = new_players[p["row"]]
        for attr, (lo, hi) in RANGES.get(group, {}).items():
            if group == "QB" and p.get("PLYR_DRAFTROUND") == 1 and attr in FIRST_ROUND_QB_FLOOR:
                lo = max(lo, FIRST_ROUND_QB_FLOOR[attr])
            v = q[attr]
            viol += not (lo <= v <= hi)
            e = edge[(group, attr)]
            e[0] += 1
            e[1] += v == lo
            e[2] += v == hi
    print("\nRange check: %d values outside your min/max." % viol)
    at_edge = sum(e[1] + e[2] for e in edge.values())
    total = sum(e[0] for e in edge.values())
    print("Values sitting exactly on a floor or ceiling: %d of %d (%.1f%%)" %
          (at_edge, total, 100.0 * at_edge / max(1, total)))

    qbs = [p for p in targets if p["Position"] == "QB"]
    if qbs:
        sp = [new_players[p["row"]]["SpeedRating"] for p in qbs]
        print("\nQB speed (%d QBs): mean %.1f, median %.0f, >=90: %d, >=94: %d, max %d" %
              (len(sp), mean(sp), median(sp), sum(v >= 90 for v in sp), sum(v >= 94 for v in sp), max(sp)))
        fr = [p for p in qbs if p.get("PLYR_DRAFTROUND") == 1]
        print("QBs currently projected in round 1 (short/medium accuracy floor 70): %d" % len(fr))
        for p in fr:
            q = new_players[p["row"]]
            print("   %s %s  short %d  med %d  deep %d  spd %d  pow %d  ovr %d" %
                  (p["FirstName"], p["LastName"], q["ThrowAccuracyShortRating"],
                   q["ThrowAccuracyMidRating"], q["ThrowAccuracyDeepRating"],
                   q["SpeedRating"], q["ThrowPowerRating"], q["OverallRating"]))

    off = [new_players[p["row"]]["ChangeOfDirectionRating"] for p in targets
           if GROUP_OF[p["Position"]] in OFFENSE_GROUPS]
    print("\nMax Change of Direction among offensive prospects: %d (cap %d)" %
          (max(off) if off else 0, OFFENSE_COD_CAP))
    fb = [p for p in skipped if p["Position"] == "FB" and p.get("ChangeOfDirectionRating", 0) > OFFENSE_COD_CAP]
    if fb:
        print("Note: %d untouched FB prospects are above the COD cap." % len(fb))

    print("\nNear-duplicate check (smallest average rating gap between two prospects):")
    for group in ["QB", "HB", "WR", "TE", "OL", "DT", "EDGE", "LB", "CB", "S"]:
        grp = [new_players[p["row"]] for p in targets if GROUP_OF[p["Position"]] == group]
        if len(grp) < 2:
            continue
        M = np.array([[q[k] for k in rating_keys] for q in grp], dtype=float)
        best = min(float(np.mean(np.abs(M[i] - M[j])))
                   for i in range(len(M)) for j in range(i + 1, len(M)))
        print("  %-5s %.1f%s" % (group, best, "   <-- very similar pair" if best < 3 else ""))

    with open("stage1_preview.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["row", "name", "pos", "old_overall", "new_overall", "height_in",
                     "old_speed", "new_speed", "old_weight_lb", "new_weight_lb"])
        for p in targets:
            q = new_players[p["row"]]
            wr.writerow([p["row"], p["FirstName"] + " " + p["LastName"], p["Position"],
                         p["OverallRating"], q["OverallRating"], p.get("Height"),
                         p.get("SpeedRating"), q.get("SpeedRating"),
                         p.get("Weight", 0) + weight_offset,
                         q.get("Weight", 0) + weight_offset])
    print("\nWrote edits.json and stage1_preview.csv")
    print("Only HB/TE/EDGE/LB weights were recalculated from speed and height.")
    print("Other weights, heights, draft order, ranks, and dev traits were NOT touched.")

    if args.dry_run:
        print("\nDry run: no save written.")
        return

    # =================================================== apply + verify
    run_node("apply.mjs", args.save, "edits.json", out_save)
    run_node("export.mjs", out_save, "players_after.json")
    after = {p["row"]: p for p in json.load(open("players_after.json"))}
    before = {p["row"]: p for p in players}
    actual, stray = 0, 0
    edited_rows = {e["row"] for e in edits}
    for row, b in before.items():
        a = after.get(row)
        if a is None:
            stray += 1
            continue
        diff = sum(1 for k in b if a.get(k) != b[k])
        actual += diff
        if diff and row not in edited_rows:
            stray += 1
    print("\nVerified changes in %s: %d (expected %d)" % (out_save, actual, n_fields))
    print("Rows changed that should not have changed: %d" % stray)
    if actual == n_fields and stray == 0:
        print("OK: the new file matches the plan exactly.")
    else:
        sys.exit("MISMATCH: do not use the new file; verification failed.")


if __name__ == "__main__":
    main()
