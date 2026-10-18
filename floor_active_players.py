#!/usr/bin/env python3
"""Raise active players and free agents to the document's position rating floors.

Only ratings below an explicit document minimum are changed. Values above the
floor and positions without a documented minimum are left alone. No randomness
is used. Current and Original rating fields are floored independently so the
minimum is not undone by the game's baseline-rating behavior.
"""
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ACTIVE_STATUSES = {"Signed", "FreeAgent", "PracticeSquad"}

# Minimums transcribed from the Madden draft-class criteria document. The
# document specifies no skill-rating floors for TE, FB, K, P, or LS.
GROUP_FLOORS = {
    "QB": {
        "ThrowPowerRating": 85,
        "ThrowAccuracyShortRating": 60,
        "ThrowAccuracyMidRating": 58,
        "ThrowAccuracyDeepRating": 59,
        "ThrowOnTheRunRating": 66,
        "ThrowUnderPressureRating": 55,
        "SpeedRating": 82,
        "AccelerationRating": 82,
        "AwarenessRating": 59,
    },
    "HB": {"SpeedRating": 85, "AccelerationRating": 85, "CarryingRating": 75},
    "WR": {"SpeedRating": 88},
    "OL": {
        "PassBlockFinesseRating": 70,
        "PassBlockPowerRating": 70,
        "PassBlockRating": 70,
        "RunBlockFinesseRating": 70,
        "RunBlockPowerRating": 70,
        "RunBlockRating": 70,
        "StrengthRating": 85,
        "ImpactBlockingRating": 75,
        "AwarenessRating": 65,
        "SpeedRating": 65,
        "AccelerationRating": 65,
        "AgilityRating": 65,
    },
    "DT": {"BlockSheddingRating": 75, "FinesseMovesRating": 65, "PowerMovesRating": 65},
    "EDGE": {
        "SpeedRating": 78,
        "AccelerationRating": 78,
        "BlockSheddingRating": 75,
        "FinesseMovesRating": 60,
        "PowerMovesRating": 60,
    },
    "LB": {
        "SpeedRating": 84,
        "AccelerationRating": 84,
        "PlayRecognitionRating": 70,
        "PursuitRating": 75,
        "ChangeOfDirectionRating": 75,
        "ManCoverageRating": 60,
        "ZoneCoverageRating": 65,
    },
    "CB": {
        "SpeedRating": 89,
        "AccelerationRating": 89,
        "ChangeOfDirectionRating": 89,
        "ManCoverageRating": 70,
        "ZoneCoverageRating": 70,
        "PressRating": 70,
    },
    "S": {
        "SpeedRating": 89,
        "AccelerationRating": 89,
        "ChangeOfDirectionRating": 85,
        "PlayRecognitionRating": 70,
        "PursuitRating": 75,
        "ManCoverageRating": 65,
        "ZoneCoverageRating": 65,
    },
}

POSITION_GROUP = {
    "QB": "QB",
    "HB": "HB",
    "WR": "WR",
    "LT": "OL",
    "LG": "OL",
    "C": "OL",
    "RG": "OL",
    "RT": "OL",
    "DT": "DT",
    "LE": "EDGE",
    "RE": "EDGE",
    "MLB": "LB",
    "LOLB": "LB",
    "ROLB": "LB",
    "CB": "CB",
    "FS": "S",
    "SS": "S",
}


def run_node(*args: str) -> None:
    script = SCRIPT_DIR / args[0]
    subprocess.run(
        ["node", str(script), *args[1:]],
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("save", help="input franchise save")
    parser.add_argument("--output", required=True, help="write a separate output save")
    args = parser.parse_args()

    input_save = Path(args.save)
    output_save = Path(args.output)
    run_node("export.mjs", str(input_save), "active_floor_players.json")
    with open("active_floor_players.json", encoding="utf-8") as source:
        players = json.load(source)
    if not isinstance(players, list) or not players:
        raise SystemExit("The franchise export contained no players. No output was written.")

    edits = []
    players_by_group = Counter()
    changed_by_group = Counter()
    fields_by_group = Counter()
    missing = []
    samples = []

    for player in players:
        status = player.get("ContractStatus")
        group = POSITION_GROUP.get(player.get("Position"))
        floors = GROUP_FLOORS.get(group, {})
        if status not in ACTIVE_STATUSES or not floors:
            continue

        players_by_group[group] += 1
        changes = {}
        for attribute, floor in floors.items():
            value = player.get(attribute)
            if not isinstance(value, (int, float)):
                missing.append((player.get("row"), player.get("Position"), attribute))
                continue

            if value < floor:
                changes[attribute] = floor
                original_attribute = "Original" + attribute
                original_value = player.get(original_attribute)
                if isinstance(original_value, (int, float)) and original_value < floor:
                    changes[original_attribute] = floor
                if len(samples) < 20:
                    samples.append(
                        f"{player.get('FirstName', '')} {player.get('LastName', '')} "
                        f"({player.get('Position')}): {attribute} {value} -> {floor}"
                    )
            else:
                original_attribute = "Original" + attribute
                original_value = player.get(original_attribute)
                if isinstance(original_value, (int, float)) and original_value < floor:
                    changes[original_attribute] = floor

        if changes:
            edits.append({"row": player["row"], **changes})
            changed_by_group[group] += 1
            fields_by_group[group] += len(changes)

    if missing:
        details = ", ".join(f"row {row} {pos}.{field}" for row, pos, field in missing[:10])
        raise SystemExit(
            "Required rating fields were missing from active players; refusing to write a partial result. "
            + details
        )

    print(
        f"Active players with documented floors: {sum(players_by_group.values())}; "
        f"players raised: {len(edits)}; rating fields raised: "
        f"{sum(len(edit) - 1 for edit in edits)}. No ratings were randomized."
    )
    for group in sorted(players_by_group):
        print(
            f"  {group}: {players_by_group[group]} checked, "
            f"{changed_by_group[group]} players raised, {fields_by_group[group]} fields raised"
        )
    for sample in samples:
        print("  " + sample)

    with open("active_floor_edits.json", "w", encoding="utf-8") as target:
        json.dump(edits, target)

    run_node("apply.mjs", str(input_save), "active_floor_edits.json", str(output_save))
    run_node("export.mjs", str(output_save), "active_floor_after.json")
    with open("active_floor_after.json", encoding="utf-8") as result:
        after_players = json.load(result)

    before_by_row = {player["row"]: player for player in players}
    after_by_row = {player["row"]: player for player in after_players}
    allowed = {
        edit["row"]: {key: value for key, value in edit.items() if key != "row"}
        for edit in edits
    }
    expected_fields = sum(len(edit) - 1 for edit in edits)
    actual_fields = 0
    stray_fields = []

    for row, before in before_by_row.items():
        after = after_by_row.get(row)
        if after is None:
            stray_fields.append(f"player row {row} disappeared")
            continue
        keys = set(before) | set(after)
        for key in keys:
            if before.get(key) == after.get(key):
                continue
            actual_fields += 1
            if key not in allowed.get(row, {}) or after.get(key) != allowed[row][key]:
                stray_fields.append(f"unexpected change at player row {row}: {key}")

    if len(after_by_row) != len(before_by_row):
        stray_fields.append("player count changed")
    if actual_fields != expected_fields:
        stray_fields.append(f"expected {expected_fields} field changes but found {actual_fields}")
    if stray_fields:
        raise SystemExit("Verification failed: " + "; ".join(stray_fields[:10]))

    print(f"Verified {actual_fields} rating-field changes in {output_save}.")


if __name__ == "__main__":
    main()
