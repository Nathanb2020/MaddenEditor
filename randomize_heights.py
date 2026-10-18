#!/usr/bin/env python3
"""
QB and WR heights for the upcoming draft class.

Touches ONLY the Height field of QB and WR draft prospects
(ContractStatus == 'Draft'). Weights are handled in Stage 1 for HB, TE, EDGE,
and LB only. Ratings, draft order and everyone else are left alone.

Usage:
  python randomize_heights.py [SAVE] [--output PATH] [--seed N] [--dry-run]

SAVE defaults to CAREER-PAHNTERS-AUTOSAVE-STAGE1 (the ratings-randomized file).
The input save is never modified; output defaults to SAVE-HEIGHTS.
Needs export.mjs / apply.mjs in this folder.
"""
import argparse
import csv
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

# =============================================================== CONFIG
DEFAULT_SAVE = "CAREER-PAHNTERS-AUTOSAVE-STAGE1"
SCRIPT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# Share of each position's prospects in each height bucket (your document).
# Buckets are in inches: 67 = 5'7", 71 = 5'11", 72 = 6'0", 74 = 6'2", 75 = 6'3",
# 77 = 6'5", 78 = 6'6".
BUCKETS = {
    "QB": [("5'11\" and shorter", 0.04), ("6'0\"-6'2\"", 0.44),
           ("6'3\"-6'5\"", 0.48), ("6'6\" and taller", 0.04)],
    "WR": [("5'11\" and shorter", 0.28), ("6'0\"-6'2\"", 0.52),
           ("6'3\"-6'5\"", 0.19), ("6'6\" and taller", 0.01)],
}
# How likely each exact height is inside its bucket (inches -> relative weight).
INSIDE = {
    "5'11\" and shorter": {67: 1, 68: 2, 69: 4, 70: 6, 71: 7},
    "6'0\"-6'2\"": {72: 4, 73: 3, 74: 3},
    "6'3\"-6'5\"": {75: 5, 76: 3, 77: 1},
    "6'6\" and taller": {78: 3, 79: 1},
}
POSITIONS = ("QB", "WR")

# =========================================================== MACHINERY


def fmt(inches):
    return "%d'%d\"" % (inches // 12, inches % 12)


def bucket_of(inches):
    if inches <= 71:
        return "5'11\" and shorter"
    if inches <= 74:
        return "6'0\"-6'2\""
    if inches <= 77:
        return "6'3\"-6'5\""
    return "6'6\" and taller"


def run_node(*args):
    script = SCRIPT_DIR / args[0]
    subprocess.run(
        ["node", str(script), *args[1:]], check=True, stdout=sys.stdout, stderr=sys.stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def pick(rng, weights):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=DEFAULT_SAVE)
    ap.add_argument("--output", help="write the new save to this path")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-export", action="store_true", help="reuse players_h.json (testing)")
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(1, 10 ** 9)
    rng = random.Random(seed)
    out_save = args.output or args.save + "-HEIGHTS"
    print("Seed: %d  (rerun with --seed %d to reproduce this exact set)" % (seed, seed))
    print("Input save: %s" % args.save)

    if not args.skip_export:
        run_node("export.mjs", args.save, "players_h.json")
    players = json.load(open("players_h.json"))
    if "Height" not in players[0]:
        sys.exit("STOP: the export has no Height field. Nothing was changed.")

    # ---- units: refuse to guess
    heights = [p["Height"] for p in players if p["Position"] in POSITIONS and isinstance(p["Height"], (int, float))]
    if not heights:
        sys.exit("STOP: Height is not numeric in this export. Nothing was changed.")
    mh = mean(heights)
    print("\nUnits check: mean QB/WR Height field = %.1f inches" % mh)
    if not 62 <= mh <= 84:
        sys.exit("STOP: Height does not look like inches (expected about 70-76). Paste this output so I can fix it. "
                 "Nothing was changed.")
    print("  Height is in inches (%s = %s)." % (int(mh), fmt(int(mh))))

    # ---- build the edits
    targets = [p for p in players if p["Position"] in POSITIONS and p.get("ContractStatus") == "Draft"]
    print("\nProspects to change: %s" % dict(Counter(p["Position"] for p in targets)))
    edits, planned = [], {}
    for p in targets:
        pos = p["Position"]
        bname = pick(rng, {n: w for n, w in BUCKETS[pos]})
        new_h = pick(rng, INSIDE[bname])
        planned[p["row"]] = new_h
        change = {}
        if new_h != p["Height"]:
            change["Height"] = new_h
        if change:
            edits.append({"row": p["row"], **change})
    expected = sum(len(e) - 1 for e in edits)

    # ---- report
    print("\n" + "=" * 64)
    print("REPORT  (%d players, %d field changes)" % (len(edits), expected))
    print("=" * 64)
    for pos in POSITIONS:
        grp = [p for p in targets if p["Position"] == pos]
        before = Counter(bucket_of(p["Height"]) for p in grp)
        after = Counter(bucket_of(planned[p["row"]]) for p in grp)
        print("\n%s (%d prospects): bucket  | target | before | after" % (pos, len(grp)))
        for name, share in BUCKETS[pos]:
            print("  %-18s | %5.0f%% | %6d | %5d" % (name, 100 * share, before[name], after[name]))
        print("  average height %s -> %s" % (
            fmt(int(round(mean(p["Height"] for p in grp)))),
            fmt(int(round(mean(planned[p["row"]] for p in grp))))))
    print("\nSample changes:")
    for p in targets[:8]:
        h = planned[p["row"]]
        print("  %-22s %-3s %s -> %s" % (
            p["FirstName"] + " " + p["LastName"], p["Position"],
            fmt(int(p["Height"])), fmt(h)))

    json.dump(edits, open("edits_heights.json", "w"))
    with open("heights_preview.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["row", "name", "pos", "old_height", "new_height"])
        for p in targets:
            h = planned[p["row"]]
            wr.writerow([p["row"], p["FirstName"] + " " + p["LastName"], p["Position"],
                         fmt(int(p["Height"])), fmt(h)])
    print("\nWrote edits_heights.json and heights_preview.csv")
    print("Only Height of QB/WR draft prospects changes. No weights are changed in this stage.")

    if args.dry_run:
        print("\nDry run: no save written.")
        return
    # ---- apply + verify
    run_node("apply.mjs", args.save, "edits_heights.json", out_save)
    run_node("export.mjs", out_save, "players_h_after.json")
    after = {p["row"]: p for p in json.load(open("players_h_after.json"))}
    before = {p["row"]: p for p in players}
    edited_rows = {e["row"] for e in edits}
    actual = stray = 0
    for row, b in before.items():
        a = after.get(row)
        if a is None:
            stray += 1
            continue
        diff = sum(1 for k in b if a.get(k) != b[k])
        actual += diff
        if diff and row not in edited_rows:
            stray += 1
    print("\nVerified changes in %s: %d (expected %d)" % (out_save, actual, expected))
    print("Rows changed that should not have changed: %d" % stray)
    if actual == expected and stray == 0:
        print("OK: the new file matches the plan exactly.")
    else:
        sys.exit("MISMATCH: do not use the new file; verification failed.")


if __name__ == "__main__":
    main()
