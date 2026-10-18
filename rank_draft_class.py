#!/usr/bin/env python3
"""Score draft prospects from position skills, physical upside, and generated college production."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import randomize_prospects as ratings

SCRIPT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
TEAMS_PER_ROUND = 32
DRAFT_ROUNDS = 7
FIRST_ROUND_QB_ACCURACY_FLOOR = 70
ROUND_POSITION_AVERAGES = {
    1: {"QB": 2.8, "RB": 1.2, "WR": 5.2, "TE": 1.0, "IOL": 2.2,
        "T": 5.8, "DT": 2.6, "EDGE": 4.6, "LB": 2.2, "CB": 3.2, "S": 1.2},
    2: {"QB": .4, "RB": 1.6, "WR": 4.4, "TE": 2.8, "IOL": 3.2,
        "T": 1.6, "DT": 3.2, "EDGE": 3.6, "LB": 3.4, "CB": 5.0, "S": 2.6},
    3: {"QB": 1.6, "RB": 2.4, "WR": 6.0, "TE": 2.4, "IOL": 3.0,
        "T": 3.8, "DT": 2.8, "EDGE": 3.6, "LB": 4.8, "CB": 4.2, "S": 3.0},
    4: {"QB": 1.0, "RB": 4.2, "WR": 4.6, "TE": 2.8, "IOL": 2.6,
        "T": 3.4, "DT": 3.6, "EDGE": 2.0, "LB": 4.0, "CB": 4.4, "S": 2.8},
    5: {"QB": 1.8, "RB": 4.0, "WR": 3.2, "TE": 3.4, "IOL": 4.0,
        "T": 1.8, "DT": 2.8, "EDGE": 3.4, "LB": 5.2, "CB": 5.8, "S": 3.8},
    6: {"QB": 1.8, "RB": 3.4, "WR": 5.4, "TE": 1.4, "IOL": 5.0,
        "T": 3.6, "DT": 4.8, "EDGE": 1.2, "LB": 4.0, "CB": 4.8, "S": 1.8},
    7: {"QB": 2.0, "RB": 2.8, "WR": 4.0, "TE": 2.6, "IOL": 4.8,
        "T": 2.8, "DT": 4.0, "EDGE": 3.2, "LB": 2.8, "CB": 5.8, "S": 4.4},
}

POSITION_GROUP = {
    "QB": "QB", "HB": "HB", "FB": "FB", "WR": "WR", "TE": "TE",
    "LT": "T", "RT": "T", "LG": "IOL", "C": "IOL", "RG": "IOL",
    "DT": "DT", "LE": "EDGE", "RE": "EDGE",
    "MLB": "LB", "LOLB": "LB", "ROLB": "LB",
    "CB": "CB", "FS": "S", "SS": "S",
    "K": "K", "P": "P", "LS": "LS",
}
POSITION_ROUND_GROUP = {
    "QB": "QB", "HB": "RB", "FB": "RB", "WR": "WR", "TE": "TE",
    "LT": "T", "RT": "T", "LG": "IOL", "C": "IOL", "RG": "IOL",
    "DT": "DT", "LE": "EDGE", "RE": "EDGE",
    "MLB": "LB", "LOLB": "LB", "ROLB": "LB",
    "CB": "CB", "FS": "S", "SS": "S",
}

# Attribute importance is position-specific. Madden OverallRating and development
# traits are deliberately absent from every formula below.
SKILL_WEIGHTS = {
    "QB": {"ThrowPowerRating": .10, "ThrowAccuracyShortRating": .12,
           "ThrowAccuracyMidRating": .16, "ThrowAccuracyDeepRating": .13,
           "ThrowOnTheRunRating": .08, "ThrowUnderPressureRating": .15,
           "AwarenessRating": .12, "PlayActionRating": .05,
           "BreakSackRating": .04, "ThrowAccuracyRating": .05},
    "HB": {"BCVisionRating": .18, "CarryingRating": .14, "BreakTackleRating": .12,
           "SpeedRating": .10, "AccelerationRating": .10, "CatchingRating": .07,
           "ShortRouteRunningRating": .05, "PassBlockRating": .04,
           "TruckingRating": .05, "JukeMoveRating": .05, "SpinMoveRating": .04,
           "StrengthRating": .03, "ChangeOfDirectionRating": .03},
    "FB": {"RunBlockRating": .20, "LeadBlockRating": .17, "StrengthRating": .15,
           "ImpactBlockingRating": .12, "PassBlockRating": .10, "CarryingRating": .08,
           "CatchingRating": .06, "SpeedRating": .05, "AccelerationRating": .04,
           "AwarenessRating": .03},
    "WR": {"ReleaseRating": .14, "CatchingRating": .13, "ShortRouteRunningRating": .12,
           "MediumRouteRunningRating": .12, "DeepRouteRunningRating": .12,
           "SpeedRating": .10, "CatchInTrafficRating": .08,
           "SpectacularCatchRating": .07, "ChangeOfDirectionRating": .06},
    "TE": {"CatchingRating": .11, "CatchInTrafficRating": .09,
           "ShortRouteRunningRating": .08, "MediumRouteRunningRating": .08,
           "ReleaseRating": .08, "RunBlockRating": .13, "PassBlockRating": .11,
           "StrengthRating": .09, "ImpactBlockingRating": .08,
           "SpeedRating": .07, "AccelerationRating": .04,
           "AwarenessRating": .04},
    "T": {"PassBlockRating": .17, "PassBlockPowerRating": .12,
          "PassBlockFinesseRating": .12, "RunBlockRating": .15,
          "RunBlockPowerRating": .10, "RunBlockFinesseRating": .10,
          "StrengthRating": .09, "AwarenessRating": .06,
          "ImpactBlockingRating": .05, "AgilityRating": .04},
    "IOL": {"PassBlockRating": .15, "PassBlockPowerRating": .12,
            "PassBlockFinesseRating": .11, "RunBlockRating": .15,
            "RunBlockPowerRating": .11, "RunBlockFinesseRating": .10,
            "StrengthRating": .10, "AwarenessRating": .06,
            "ImpactBlockingRating": .06, "AgilityRating": .04},
    "DT": {"BlockSheddingRating": .20, "PowerMovesRating": .17,
           "FinesseMovesRating": .15, "StrengthRating": .13,
           "TackleRating": .10, "AccelerationRating": .08,
           "SpeedRating": .06, "PlayRecognitionRating": .05,
           "PursuitRating": .04, "HitPowerRating": .02},
    "EDGE": {"FinesseMovesRating": .18, "PowerMovesRating": .16,
             "BlockSheddingRating": .15, "AccelerationRating": .12,
             "SpeedRating": .10, "StrengthRating": .09,
             "PlayRecognitionRating": .07, "PursuitRating": .06,
             "TackleRating": .05, "HitPowerRating": .02},
    "LB": {"TackleRating": .14, "PlayRecognitionRating": .14,
           "PursuitRating": .13, "SpeedRating": .12,
           "AccelerationRating": .10, "BlockSheddingRating": .08,
           "ZoneCoverageRating": .08, "ManCoverageRating": .06,
           "ChangeOfDirectionRating": .07, "HitPowerRating": .05,
           "StrengthRating": .03},
    "CB": {"ManCoverageRating": .17, "ZoneCoverageRating": .14,
           "SpeedRating": .15, "AccelerationRating": .13,
           "ChangeOfDirectionRating": .13, "PressRating": .10,
           "PlayRecognitionRating": .07, "CatchingRating": .05,
           "JumpingRating": .03, "AwarenessRating": .03},
    "S": {"ZoneCoverageRating": .14, "ManCoverageRating": .10,
          "SpeedRating": .13, "AccelerationRating": .11,
          "ChangeOfDirectionRating": .11, "PlayRecognitionRating": .13,
          "PursuitRating": .10, "TackleRating": .08,
          "HitPowerRating": .05, "CatchingRating": .03,
          "AwarenessRating": .02},
    "K": {"KickAccuracyRating": .55, "KickPowerRating": .30,
          "AwarenessRating": .08, "StrengthRating": .04,
          "KickReturnRating": .03},
    "P": {"KickPowerRating": .42, "KickAccuracyRating": .30,
          "AwarenessRating": .12, "SpeedRating": .08,
          "StrengthRating": .08},
    "LS": {"LongSnapRating": .55, "AwarenessRating": .18,
           "StrengthRating": .12, "AgilityRating": .08,
           "SpeedRating": .07},
}

PHYSICAL_WEIGHTS = {
    "QB": {"SpeedRating": .20, "AccelerationRating": .16, "AgilityRating": .12,
           "ChangeOfDirectionRating": .10, "ThrowPowerRating": .12,
           "StrengthRating": .06, "JumpingRating": .05, "height": .10, "weight": .09},
    "HB": {"SpeedRating": .20, "AccelerationRating": .20, "AgilityRating": .14,
           "ChangeOfDirectionRating": .12, "StrengthRating": .08,
           "JumpingRating": .08, "height": .08, "weight": .10},
    "FB": {"SpeedRating": .10, "AccelerationRating": .10, "StrengthRating": .20,
           "AgilityRating": .08, "JumpingRating": .05, "height": .15, "weight": .32},
    "WR": {"SpeedRating": .20, "AccelerationRating": .18, "AgilityRating": .11,
           "ChangeOfDirectionRating": .14, "JumpingRating": .12,
           "StrengthRating": .04, "height": .11, "weight": .10},
    "TE": {"SpeedRating": .12, "AccelerationRating": .12, "StrengthRating": .17,
           "AgilityRating": .08, "JumpingRating": .08, "height": .18, "weight": .25},
    "T": {"StrengthRating": .20, "AccelerationRating": .08, "SpeedRating": .06,
          "AgilityRating": .08, "ImpactBlockingRating": .06,
          "height": .22, "weight": .30},
    "IOL": {"StrengthRating": .19, "AccelerationRating": .08, "SpeedRating": .06,
            "AgilityRating": .08, "ImpactBlockingRating": .07,
            "height": .18, "weight": .34},
    "DT": {"StrengthRating": .18, "AccelerationRating": .13, "SpeedRating": .10,
           "AgilityRating": .08, "JumpingRating": .04, "height": .18, "weight": .29},
    "EDGE": {"SpeedRating": .17, "AccelerationRating": .18, "StrengthRating": .13,
             "AgilityRating": .10, "ChangeOfDirectionRating": .08,
             "JumpingRating": .05, "height": .15, "weight": .14},
    "LB": {"SpeedRating": .17, "AccelerationRating": .16, "AgilityRating": .12,
           "ChangeOfDirectionRating": .12, "StrengthRating": .08,
           "JumpingRating": .06, "height": .14, "weight": .15},
    "CB": {"SpeedRating": .20, "AccelerationRating": .18, "AgilityRating": .12,
           "ChangeOfDirectionRating": .17, "JumpingRating": .10,
           "StrengthRating": .04, "height": .10, "weight": .09},
    "S": {"SpeedRating": .18, "AccelerationRating": .16, "AgilityRating": .12,
          "ChangeOfDirectionRating": .14, "JumpingRating": .09,
          "StrengthRating": .07, "height": .12, "weight": .12},
    "K": {"KickPowerRating": .48, "StrengthRating": .20,
          "AgilityRating": .15, "SpeedRating": .10,
          "AccelerationRating": .07},
    "P": {"KickPowerRating": .40, "SpeedRating": .20,
          "StrengthRating": .18, "AgilityRating": .12,
          "AccelerationRating": .10},
    "LS": {"StrengthRating": .25, "SpeedRating": .20,
           "AgilityRating": .20, "AccelerationRating": .15,
           "height": .10, "weight": .10},
}

SIZE_RANGES = {
    "QB": ((72, 78), (210, 250)), "HB": ((68, 75), (185, 235)),
    "FB": ((68, 76), (220, 270)), "WR": ((69, 79), (170, 230)),
    "TE": ((74, 81), (225, 285)), "T": ((75, 81), (285, 360)),
    "IOL": ((72, 79), (275, 350)), "DT": ((72, 80), (260, 360)),
    "EDGE": ((72, 80), (235, 300)), "LB": ((69, 79), (205, 270)),
    "CB": ((68, 77), (165, 220)), "S": ((69, 78), (175, 235)),
    "K": ((68, 77), (175, 225)), "P": ((70, 79), (190, 250)),
    "LS": ((70, 79), (235, 300)),
}

RED_FLAGS = {
    "QB": [("ThrowAccuracyMidRating", 65, 0.45, "limited intermediate accuracy"),
           ("ThrowUnderPressureRating", 60, 0.40, "pressure-response concern")],
    "HB": [("BCVisionRating", 58, 0.40, "vision concern"),
           ("CarryingRating", 65, 0.28, "ball-security concern")],
    "WR": [("ReleaseRating", 60, 0.32, "release concern"),
           ("CatchingRating", 62, 0.32, "hands concern"),
           ("MediumRouteRunningRating", 60, 0.28, "route-running concern")],
    "TE": [("CatchingRating", 58, 0.30, "receiving concern"),
           ("RunBlockRating", 58, 0.30, "blocking concern")],
    "T": [("PassBlockRating", 62, 0.35, "pass-protection concern"),
          ("AwarenessRating", 60, 0.24, "recognition concern")],
    "IOL": [("PassBlockRating", 62, 0.35, "pass-protection concern"),
            ("RunBlockRating", 62, 0.30, "run-blocking concern")],
    "DT": [("BlockSheddingRating", 62, 0.32, "block-shedding concern"),
           ("PowerMovesRating", 58, 0.24, "power-rush concern"),
           ("FinesseMovesRating", 58, 0.24, "finesse-rush concern")],
    "EDGE": [("BlockSheddingRating", 62, 0.30, "block-shedding concern"),
             ("PowerMovesRating", 58, 0.22, "power-rush concern"),
             ("FinesseMovesRating", 58, 0.22, "finesse-rush concern")],
    "LB": [("PlayRecognitionRating", 58, 0.30, "play-recognition concern"),
           ("TackleRating", 60, 0.30, "tackling concern")],
    "CB": [("ManCoverageRating", 62, 0.32, "man-coverage concern"),
           ("ZoneCoverageRating", 62, 0.32, "zone-coverage concern"),
           ("ChangeOfDirectionRating", 65, 0.22, "change-of-direction concern")],
    "S": [("ZoneCoverageRating", 58, 0.30, "zone-coverage concern"),
          ("ManCoverageRating", 58, 0.25, "man-coverage concern"),
          ("PlayRecognitionRating", 60, 0.25, "play-recognition concern")],
    "K": [("KickAccuracyRating", 65, 0.35, "kicking-accuracy concern")],
    "P": [("KickPowerRating", 65, 0.30, "punt-power concern"),
          ("KickAccuracyRating", 60, 0.25, "punt-placement concern")],
    "LS": [("LongSnapRating", 65, 0.40, "long-snapping concern")],
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def rating(player: dict, key: str, fallback: float = 65) -> float:
    value = player.get(key, fallback)
    return float(value) if isinstance(value, (int, float)) else fallback


def weighted_rating(player: dict, weights: dict[str, float]) -> float:
    available = [(rating(player, key), weight) for key, weight in weights.items()
                 if isinstance(player.get(key), (int, float))]
    if not available:
        values = [float(v) for k, v in player.items()
                  if k.endswith("Rating") and not k.startswith("Original")
                  and isinstance(v, (int, float))]
        return sum(values) / len(values) if values else 60.0
    total = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / total


def size_fit(value: float, expected: tuple[float, float], outside_penalty: float) -> float:
    low, high = expected
    distance = max(low - value, 0, value - high)
    return clamp(100.0 - distance * outside_penalty, 0, 100)


def school_key(player: dict) -> str:
    value = str(player.get("College", "") or "")
    return value if value and value != "00000000000000000000000000000000" else "unknown"


def school_context(player: dict, programs: dict[str, dict]) -> tuple[str, int]:
    key = school_key(player)
    hashed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    code = f"0x{int(key, 2):08X}" if key != "unknown" and set(key) <= {"0", "1"} else f"College-{hashed:08X}"
    configured = programs.get(code) or programs.get(code.lower()) or {}
    default_name = code if key != "unknown" else "unknown"
    label = str(configured.get("name", default_name))
    # The save exposes a packed school reference, not a readable school name.
    # A stable generated tier is used unless the user supplies a mapping.
    strength = int(configured.get("strength", 42 + hashed % 47))
    return label, strength


def production_for_player(player: dict, group: str, program: int,
                          rng: random.Random) -> tuple[float, str, float]:
    skill = weighted_rating(player, SKILL_WEIGHTS.get(group, {}))
    role = clamp(0.42 + (skill - 50) * 0.011, 0.30, 0.98)
    context = (program - 65) / 100.0
    stats: dict[str, str]
    if group == "QB":
        attempts = round(260 + role * 235 + rng.randint(-18, 18))
        accuracy = (rating(player, "ThrowAccuracyShortRating") * .38
                    + rating(player, "ThrowAccuracyMidRating") * .37
                    + rating(player, "ThrowAccuracyDeepRating") * .25)
        comp = clamp(.46 + (accuracy - 60) * .0032
                     + (rating(player, "AwarenessRating") - 65) * .0011
                     + context * .06 + rng.gauss(0, .014), .36, .76)
        ypa = clamp(6.0 + (rating(player, "ThrowAccuracyDeepRating") - 65) * .035
                    + (rating(player, "ThrowPowerRating") - 75) * .018
                    + context * .25 + rng.gauss(0, .22), 4.5, 10.5)
        td_rate = clamp(.022 + (accuracy - 65) * .00042
                        + (rating(player, "AwarenessRating") - 65) * .00024
                        + context * .003 + rng.gauss(0, .002), .008, .075)
        int_rate = clamp(.032 + max(0, 65 - rating(player, "ThrowUnderPressureRating")) * .0008
                         + max(0, 65 - accuracy) * .00045 + rng.gauss(0, .002), .008, .085)
        completions = round(attempts * comp)
        yards = round(completions * ypa)
        tds, picks = round(attempts * td_rate), round(attempts * int_rate)
        score = (.38 * size_fit(comp * 100, (53, 70), 4.5)
                 + .32 * size_fit(ypa, (6.2, 9.0), 18)
                 + .18 * size_fit(tds / max(1, attempts) * 100, (2.5, 6.5), 8)
                 + .12 * size_fit((1 - picks / max(1, attempts)) * 100, (96, 99), 5))
        stats = {"CMP/ATT": f"{completions}/{attempts}", "PASS YDS": str(yards),
                 "PASS TD": str(tds), "INT": str(picks), "YPA": f"{ypa:.1f}"}
    elif group == "HB":
        carries = round(80 + role * 155 + rng.randint(-12, 12))
        ypc = clamp(3.5 + (rating(player, "SpeedRating") - 80) * .025
                    + (rating(player, "BCVisionRating") - 65) * .027
                    + (rating(player, "BreakTackleRating") - 65) * .014
                    + context * .30 + rng.gauss(0, .20), 2.6, 7.4)
        rush_yards = round(carries * ypc)
        td_rate = clamp(.018 + (rating(player, "BreakTackleRating") - 65) * .00045
                        + (rating(player, "StrengthRating") - 65) * .00025 + rng.gauss(0, .002), .004, .08)
        tds = round(carries * td_rate)
        fumbles = max(0, round(carries * (.004 + max(0, 70 - rating(player, "CarryingRating")) * .0003)))
        catches = round(10 + role * (rating(player, "CatchingRating") / 99) * 42)
        rec_yards = round(catches * (5.5 + rating(player, "SpeedRating") * .035))
        score = (.34 * size_fit(rush_yards, (450, 1550), .055)
                 + .24 * size_fit(ypc, (4.0, 6.5), 22)
                 + .20 * size_fit(tds, (4, 18), 5)
                 + .12 * size_fit(catches, (12, 55), 1.5)
                 + .10 * size_fit(fumbles, (0, 3), 14))
        stats = {"RUSH ATT": str(carries), "RUSH YDS": str(rush_yards), "YPC": f"{ypc:.1f}",
                 "RUSH TD": str(tds), "REC": str(catches), "REC YDS": str(rec_yards), "FUM": str(fumbles)}
    elif group in {"WR", "TE"}:
        targets = round((42 if group == "TE" else 55) + role * (60 if group == "TE" else 75)
                        + rng.randint(-6, 6))
        hands = (rating(player, "CatchingRating") * .45
                 + rating(player, "CatchInTrafficRating") * .25
                 + rating(player, "ShortRouteRunningRating") * .15
                 + rating(player, "MediumRouteRunningRating") * .15)
        catch_rate = clamp(.43 + (hands - 60) * .0032 + context * .035 + rng.gauss(0, .015), .33, .82)
        receptions = round(targets * catch_rate)
        ypr = clamp(8.0 + rating(player, "SpeedRating") * .055
                    + (rating(player, "DeepRouteRunningRating") - 65) * .035
                    + (rating(player, "ReleaseRating") - 65) * .018 + rng.gauss(0, .35), 7.0, 22.0)
        yards = round(receptions * ypr)
        tds = round(receptions * clamp(.035 + (rating(player, "SpectacularCatchRating") - 65) * .00035
                                      + context * .004 + rng.gauss(0, .002), .01, .12))
        score = (.30 * size_fit(receptions, (25, 95), 1.2)
                 + .32 * size_fit(yards, (350, 1450), .075)
                 + .18 * size_fit(ypr, (9, 17), 9)
                 + .20 * size_fit(tds, (2, 14), 5))
        stats = {"TARGETS": str(targets), "REC": str(receptions), "REC YDS": str(yards),
                 "Y/R": f"{ypr:.1f}", "REC TD": str(tds)}
        if group == "TE":
            stats["BLOCK GRADE"] = f"{(rating(player, 'RunBlockRating') * .55 + rating(player, 'PassBlockRating') * .45):.0f}"
    elif group in {"T", "IOL", "FB"}:
        snaps = round(340 + role * 410 + rng.randint(-20, 20))
        pass_skill = (rating(player, "PassBlockRating") * .55
                      + rating(player, "PassBlockPowerRating") * .22
                      + rating(player, "PassBlockFinesseRating") * .23)
        run_skill = (rating(player, "RunBlockRating") * .55
                     + rating(player, "RunBlockPowerRating") * .22
                     + rating(player, "RunBlockFinesseRating") * .23)
        pressures = max(0, round((100 - pass_skill) * snaps / 220 + rng.gauss(0, 2)))
        pancakes = max(0, round((run_skill - 45) * snaps / 430 + rng.gauss(0, 2)))
        score = (.46 * pass_skill + .40 * run_skill
                 + .08 * rating(player, "AwarenessRating")
                 + .06 * rating(player, "StrengthRating"))
        score -= min(12, pressures * .12)
        stats = {"OFF SNAPS": str(snaps), "PRESSURES ALLOWED": str(pressures),
                 "PANCAKES": str(pancakes), "PASS BLOCK": f"{pass_skill:.0f}",
                 "RUN BLOCK": f"{run_skill:.0f}"}
    elif group in {"DT", "EDGE", "LB"}:
        snaps = round(190 + role * 360 + rng.randint(-15, 15))
        rush_skill = (rating(player, "PowerMovesRating") * .45
                      + rating(player, "FinesseMovesRating") * .45
                      + rating(player, "BlockSheddingRating") * .10)
        tackles = max(8, round(snaps * (.045 + rating(player, "TackleRating") * .00048)
                               + rng.gauss(0, 3)))
        sacks = max(0, round((snaps / 450) * max(0, rush_skill - 50) * .12 + rng.gauss(0, .7)))
        tfl = max(0, round((snaps / 450) * max(0, rating(player, "BlockSheddingRating") - 50) * .16
                           + rng.gauss(0, .8)))
        score = (.38 * size_fit(tackles, (30, 90), .9)
                 + .30 * size_fit(sacks, (1, 14), 5)
                 + .22 * size_fit(tfl, (3, 24), 3)
                 + .10 * size_fit(rush_skill, (60, 90), 2.0))
        stats = {"DEF SNAPS": str(snaps), "TACKLES": str(tackles),
                 "SACKS": str(sacks), "TFL": str(tfl)}
    elif group == "CB":
        targets = round(28 + role * 24 + rng.randint(-4, 4))
        cover = rating(player, "ManCoverageRating") * .52 + rating(player, "ZoneCoverageRating") * .48
        comp_rate = clamp(.63 - (cover - 60) * .0032 - (rating(player, "SpeedRating") - 75) * .0015
                          + context * .025 + rng.gauss(0, .018), .20, .78)
        completions = round(targets * comp_rate)
        pbu = max(0, round(targets * (rating(player, "PressRating") + rating(player, "CatchingRating") - 100)
                           * .0014 + rng.gauss(0, .8)))
        ints = max(0, round(targets * (rating(player, "CatchingRating") * .00035
                                       + rating(player, "PlayRecognitionRating") * .0002)
                            + rng.gauss(0, .7)))
        score = (.42 * size_fit(100 * (1 - comp_rate), (42, 75), 2.4)
                 + .30 * size_fit(pbu, (3, 18), 3.5)
                 + .18 * size_fit(ints, (1, 8), 8)
                 + .10 * size_fit(targets, (25, 55), 1.2))
        stats = {"TARGETS": str(targets), "COMP ALLOWED": str(completions),
                 "PBU": str(pbu), "INT": str(ints)}
    elif group == "S":
        tackles = round(38 + role * 40 + rng.randint(-4, 4))
        cover = rating(player, "ManCoverageRating") * .40 + rating(player, "ZoneCoverageRating") * .60
        pbu = max(0, round((cover - 45) * .12 + rating(player, "CatchingRating") * .025 + rng.gauss(0, 1)))
        ints = max(0, round(rating(player, "CatchingRating") * .025
                             + rating(player, "PlayRecognitionRating") * .02 + rng.gauss(0, .8)))
        tfl = max(0, round((rating(player, "PursuitRating") - 50) * .09 + rng.gauss(0, 1)))
        score = (.38 * size_fit(tackles, (40, 100), .8)
                 + .25 * size_fit(pbu, (3, 18), 3.5)
                 + .22 * size_fit(ints, (1, 8), 8)
                 + .15 * size_fit(tfl, (2, 16), 4))
        stats = {"TACKLES": str(tackles), "PBU": str(pbu), "INT": str(ints), "TFL": str(tfl)}
    elif group == "K":
        attempts = max(18, round(20 + role * 13 + rng.randint(-2, 2)))
        make_rate = clamp(.69 + (rating(player, "KickAccuracyRating") - 60) * .0042
                          + (rating(player, "AwarenessRating") - 60) * .0007
                          + context * .025 + rng.gauss(0, .018), .55, .98)
        made = round(attempts * make_rate)
        longest = round(clamp(34 + rating(player, "KickPowerRating") * .19
                              + rng.gauss(0, 2.4), 35, 70))
        score = (.58 * size_fit(100 * made / attempts, (72, 96), 2.0)
                 + .27 * size_fit(longest, (40, 62), 1.8)
                 + .15 * size_fit(attempts, (20, 34), 1.0))
        stats = {"FG": f"{made}/{attempts}", "FG%": f"{100 * made / attempts:.1f}",
                 "LONG": str(longest), "XP": str(round(25 + role * 14))}
    elif group == "P":
        attempts = max(24, round(28 + role * 20 + rng.randint(-3, 3)))
        gross = clamp(33 + rating(player, "KickPowerRating") * .16
                      + context * .45 + rng.gauss(0, 1.8), 32, 65)
        inside_rate = clamp(.17 + (rating(player, "KickAccuracyRating") - 60) * .008
                            + context * .02 + rng.gauss(0, .025), .08, .58)
        touchback_rate = clamp(.11 + max(0, rating(player, "KickPowerRating") - 75) * .002
                               - (rating(player, "KickAccuracyRating") - 65) * .001
                               + rng.gauss(0, .018), .02, .25)
        inside20 = round(attempts * inside_rate)
        touchbacks = round(attempts * touchback_rate)
        net = gross - touchback_rate * 18 - .8
        score = (.38 * size_fit(gross, (38, 52), 2.0)
                 + .37 * size_fit(net, (34, 48), 2.2)
                 + .25 * size_fit(100 * inside20 / attempts, (20, 48), 1.5))
        stats = {"PUNTS": str(attempts), "GROSS AVG": f"{gross:.1f}",
                 "NET AVG": f"{net:.1f}", "INSIDE 20": str(inside20),
                 "TOUCHBACKS": str(touchbacks)}
    elif group == "LS":
        snaps = round(145 + role * 75 + rng.randint(-8, 8))
        bad_snap_rate = clamp(.045 - (rating(player, "LongSnapRating") - 55) * .00085
                              - (rating(player, "AwarenessRating") - 60) * .00022
                              + rng.gauss(0, .003), .001, .08)
        bad_snaps = round(snaps * bad_snap_rate)
        score = (.78 * size_fit(100 * bad_snaps / snaps, (0, 2.5), 7.0)
                 + .22 * size_fit(snaps, (140, 220), .22))
        stats = {"SNAPS": str(snaps), "BAD SNAPS": str(bad_snaps),
                 "BAD SNAP%": f"{100 * bad_snaps / snaps:.2f}"}
    else:
        stats = {"ROLE GRADE": f"{skill:.0f}"}
        score = skill
    return clamp(score, 0, 100), "; ".join(f"{k} {v}" for k, v in stats.items()), role


def physical_score(player: dict, group: str) -> float:
    weights = PHYSICAL_WEIGHTS.get(group, {"SpeedRating": .35, "AccelerationRating": .30,
                                           "StrengthRating": .20, "height": .08, "weight": .07})
    values: list[tuple[float, float]] = []
    height, weight = player.get("Height"), player.get("Weight")
    if isinstance(height, (int, float)) and isinstance(weight, (int, float)):
        # Madden stores player weights as pounds minus 160 in these franchise files.
        weight_lb = float(weight) + 160
    else:
        weight_lb = None
    expected_height, expected_weight = SIZE_RANGES.get(group, SIZE_RANGES["QB"])
    for attribute, share in weights.items():
        if attribute == "height" and isinstance(height, (int, float)):
            value = size_fit(float(height), expected_height, 12)
        elif attribute == "weight" and weight_lb is not None:
            value = size_fit(weight_lb, expected_weight, .65)
        elif isinstance(player.get(attribute), (int, float)):
            value = rating(player, attribute)
        else:
            continue
        values.append((value, share))
    total = sum(weight for _, weight in values)
    return clamp(sum(value * weight for value, weight in values) / total, 0, 100) if total else 60


def red_flag_penalty(player: dict, group: str) -> tuple[float, list[str]]:
    penalty = 0.0
    flags = []
    for attribute, threshold, rate, label in RED_FLAGS.get(group, []):
        value = rating(player, attribute, 99)
        if value < threshold:
            points = min(3.5, (threshold - value) * rate)
            penalty += points
            flags.append(f"{label} ({attribute.removesuffix('Rating')} {value:.0f})")
    return min(9.0, penalty), flags


def evaluate(player: dict, seed: int, programs: dict[str, dict]) -> dict:
    group = POSITION_GROUP.get(str(player.get("Position", "")), "GEN")
    nfl_raw = weighted_rating(player, SKILL_WEIGHTS.get(group, {}))
    penalty, flags = red_flag_penalty(player, group)
    nfl = clamp(nfl_raw - penalty, 0, 100)
    physical = physical_score(player, group)
    school, program = school_context(player, programs)
    seed_material = f"{seed}:{player.get('row')}:{player.get('FirstName')}:{player.get('LastName')}"
    local_seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    production, stat_line, role = production_for_player(player, group, program, random.Random(local_seed))
    # A stronger program raises the bar for production. Context is then scored
    # separately, so the college is not double-counted as raw production.
    production_adjusted = clamp(production - max(0, program - 65) * .10
                                + max(0, 65 - program) * .05, 0, 100)
    final = .45 * nfl + .30 * physical + .15 * production_adjusted + .10 * program
    if flags:
        explanation = "; ".join(flags)
    else:
        explanation = "No major position-specific red flag"
    return {
        "group": group, "nfl_raw": nfl_raw, "risk_penalty": penalty,
        "nfl": nfl, "physical": physical, "production": production,
        "production_adjusted": production_adjusted, "program": program,
        "school": school, "role": role, "stats": stat_line,
        "score": final, "flags": flags, "explanation": explanation,
    }


def scouting_key(pair: tuple[dict, dict], evaluations: dict[int, dict]) -> tuple:
    player = pair[1]
    result = evaluations[player["row"]]
    return (-result["score"], -result["nfl"], -result["physical"],
            -result["production_adjusted"], player["row"])


def round_position_quota(round_number: int) -> dict[str, int]:
    averages = ROUND_POSITION_AVERAGES[round_number]
    total = sum(averages.values())
    normalized = {group: value * TEAMS_PER_ROUND / total for group, value in averages.items()}
    quotas = {group: int(value) for group, value in normalized.items()}
    remaining = TEAMS_PER_ROUND - sum(quotas.values())
    fractions = sorted(normalized, key=lambda group: (-(normalized[group] - quotas[group]), group))
    for group in fractions[:remaining]:
        quotas[group] += 1
    if sum(quotas.values()) != TEAMS_PER_ROUND:
        raise ValueError(f"Round {round_number} position averages do not add up to {TEAMS_PER_ROUND}.")
    return quotas


def allocate_draft_order(draft_rows: list[tuple[dict, dict]],
                         evaluations: dict[int, dict]) -> list[tuple[dict, dict]]:
    """Apply the document's per-round position mix, then order each round by scouting score."""
    by_group: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for pair in draft_rows:
        group = POSITION_ROUND_GROUP.get(str(pair[1].get("Position", "")))
        if group:
            by_group[group].append(pair)
    for group in by_group:
        by_group[group].sort(key=lambda pair: scouting_key(pair, evaluations))

    used_by_group: dict[str, int] = defaultdict(int)
    ordered: list[tuple[dict, dict]] = []
    for round_number in range(1, DRAFT_ROUNDS + 1):
        round_players = []
        for group, count in round_position_quota(round_number).items():
            start = used_by_group[group]
            available = by_group.get(group, [])[start:start + count]
            if len(available) != count:
                raise SystemExit(
                    f"The class has too few {group} prospects to match the document's "
                    f"round {round_number} position mix."
                )
            round_players.extend(available)
            used_by_group[group] += count
        ordered.extend(sorted(round_players, key=lambda pair: scouting_key(pair, evaluations)))

    drafted_rows = {player["row"] for _, player in ordered}
    undrafted = [pair for pair in draft_rows if pair[1]["row"] not in drafted_rows]
    ordered.extend(sorted(undrafted, key=lambda pair: scouting_key(pair, evaluations)))
    return ordered


def run_node(*args: str) -> None:
    subprocess.run(["node", str(SCRIPT_DIR / args[0]), *args[1:]], check=True,
                   stdout=sys.stdout, stderr=sys.stderr,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def update_qb_floor(player: dict, overall_model: dict | None) -> None:
    old_overall = player.get("OverallRating")
    old_original_overall = player.get("OriginalOverallRating")
    for attribute in ("ThrowAccuracyShortRating", "ThrowAccuracyMidRating"):
        if rating(player, attribute) < FIRST_ROUND_QB_ACCURACY_FLOOR:
            old = rating(player, attribute)
            updated_rating = FIRST_ROUND_QB_ACCURACY_FLOOR
            player[attribute] = updated_rating
            twin = "Original" + attribute
            if isinstance(player.get(twin), (int, float)):
                player[twin] = int(clamp(updated_rating + (player[twin] - old), 0, 99))
    if overall_model:
        rating_keys = [key for key in player if key.endswith("Rating")
                       and not key.startswith("Original")
                       and key not in ratings.EXCLUDED]
        # The model stores the fitted feature list; every Player record has these fields.
        updated = ratings.predict(overall_model, player)
    else:
        updated = int(clamp(float(old_overall or 60), 0, 99))
    if old_overall is not None:
        player["OverallRating"] = updated
    if old_original_overall == old_overall and old_overall is not None:
        player["OriginalOverallRating"] = updated
    for index in range(4):
        key = f"OverallGrade{index}"
        if isinstance(player.get(key), (int, float)) and player[key] > 0 and old_overall is not None:
            player[key] = int(clamp(updated + (player[key] - old_overall), 0, 99))


def write_report(path: Path, ranked: list[dict], position_counts: dict[tuple[int, str], int]) -> None:
    fields = ["rank", "scouting_rank", "round", "pick_in_round", "position",
              "draft_position_group", "name", "final_score",
              "nfl_skills", "nfl_skills_before_risk", "risk_penalty", "physical_upside",
              "college_production", "production_after_context", "program_context",
              "program_code", "role_share", "generated_fictional_college_stats", "red_flags",
              "average_position_target_for_round", "normalized_position_target_for_round",
              "actual_position_count_in_round"]
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for item in ranked:
            p, e = item["player"], item["evaluation"]
            pick_rank = item["rank"]
            if pick_rank <= TEAMS_PER_ROUND * DRAFT_ROUNDS:
                round_number = (pick_rank - 1) // TEAMS_PER_ROUND + 1
                pick_number = (pick_rank - 1) % TEAMS_PER_ROUND + 1
            else:
                round_number, pick_number = 63, 0
            target_group = POSITION_ROUND_GROUP.get(str(p.get("Position", "")), "")
            round_target = ROUND_POSITION_AVERAGES.get(round_number, {}).get(target_group, "")
            round_values = ROUND_POSITION_AVERAGES.get(round_number, {})
            normalized_target = (round_target * TEAMS_PER_ROUND / sum(round_values.values())
                                 if target_group and round_values else "")
            actual_count = position_counts.get((round_number, target_group), "")
            writer.writerow({
                "rank": pick_rank, "scouting_rank": item["scouting_rank"],
                "round": round_number, "pick_in_round": pick_number,
                "position": p.get("Position", ""),
                "draft_position_group": target_group,
                "name": f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip(),
                "final_score": f"{e['score']:.2f}", "nfl_skills": f"{e['nfl']:.2f}",
                "nfl_skills_before_risk": f"{e['nfl_raw']:.2f}",
                "risk_penalty": f"{e['risk_penalty']:.2f}",
                "physical_upside": f"{e['physical']:.2f}",
                "college_production": f"{e['production']:.2f}",
                "production_after_context": f"{e['production_adjusted']:.2f}",
                "program_context": f"{e['program']:.0f}", "program_code": e["school"],
                "role_share": f"{e['role']:.2f}",
                "generated_fictional_college_stats": e["stats"], "red_flags": e["explanation"],
                "average_position_target_for_round": round_target,
                "normalized_position_target_for_round": (f"{normalized_target:.2f}"
                                                           if normalized_target != "" else ""),
                "actual_position_count_in_round": actual_count,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save", help="Stage 2 save with randomized ratings and heights")
    parser.add_argument("--output", required=True, help="write final draft-class save here")
    parser.add_argument("--report", required=True, help="write scouting report CSV here")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(1, 10 ** 9)
    print(f"Scouting seed: {seed}")
    program_config_path = SCRIPT_DIR / "college_programs.json"
    try:
        program_config = json.loads(program_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read {program_config_path.name}: {exc}")
    programs = program_config.get("programs", {})
    if not isinstance(programs, dict):
        raise SystemExit("college_programs.json must contain a 'programs' object.")
    for code, entry in programs.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("strength"), int) \
                or not 0 <= entry["strength"] <= 100:
            raise SystemExit(f"College program {code} needs a whole-number strength from 0 to 100.")

    before_path = Path("draft_class_before.json")
    edits_path = Path("draft_order_edits.json")
    after_path = Path("draft_class_after.json")
    run_node("export_draft_class.mjs", args.save, str(before_path))
    data = json.loads(before_path.read_text(encoding="utf-8"))
    all_players = data["players"]
    by_row = {p["row"]: p for p in all_players}
    draft_rows = []
    for draft_player in data["draftPlayers"]:
        player = by_row.get(draft_player["playerRow"])
        if player and player.get("ContractStatus") == "Draft":
            draft_rows.append((draft_player, player))
    if not draft_rows:
        raise SystemExit("No DraftPlayer records linked to ContractStatus=Draft players were found.")
    if len({p["row"] for _, p in draft_rows}) != len(draft_rows):
        raise SystemExit("Duplicate Player references exist in DraftPlayer; refusing to create ambiguous ranks.")
    player_draft_rows = {p["row"] for p in all_players if p.get("ContractStatus") == "Draft"}
    linked_draft_rows = {p["row"] for _, p in draft_rows}
    if player_draft_rows != linked_draft_rows:
        missing = sorted(player_draft_rows - linked_draft_rows)
        raise SystemExit(f"DraftPlayer coverage mismatch; {len(missing)} draft players have no ranking record.")

    # Fit the app's existing position formula only to keep displayed Madden OVR
    # consistent if the first-round QB minimum raises an accuracy rating.
    qb_rows = [p for p in all_players if p.get("Position") == "QB"
               and isinstance(p.get("OverallRating"), (int, float))]
    rating_keys = sorted(key for key in (qb_rows[0].keys() if qb_rows else [])
                         if key.endswith("Rating") and not key.startswith("Original")
                         and key not in ratings.EXCLUDED)
    overall_model = None
    if len(qb_rows) >= 30 and rating_keys:
        try:
            overall_model = ratings.fit_sparse(qb_rows, rating_keys, "OverallRating")
        except (ValueError, ArithmeticError):
            overall_model = None

    evaluations: dict[int, dict] = {}
    for _ in range(len(draft_rows) + 1):
        evaluations = {p["row"]: evaluate(p, seed, programs) for _, p in draft_rows}
        ordered = allocate_draft_order(draft_rows, evaluations)
        qb_floor_candidates = [p for rank, (_, p) in enumerate(ordered[:TEAMS_PER_ROUND], 1)
                               if p.get("Position") == "QB"
                               and (rating(p, "ThrowAccuracyShortRating") < FIRST_ROUND_QB_ACCURACY_FLOOR
                                    or rating(p, "ThrowAccuracyMidRating") < FIRST_ROUND_QB_ACCURACY_FLOOR)]
        if not qb_floor_candidates:
            break
        for player in qb_floor_candidates:
            update_qb_floor(player, overall_model)
    else:
        raise SystemExit("Could not stabilize the first-round QB accuracy floor.")

    evaluations = {p["row"]: evaluate(p, seed, programs) for _, p in draft_rows}
    scouting_order = sorted(draft_rows, key=lambda pair: scouting_key(pair, evaluations))
    scouting_rank_by_player_row = {
        player["row"]: rank for rank, (_, player) in enumerate(scouting_order, 1)
    }
    ordered = allocate_draft_order(draft_rows, evaluations)

    player_edits = []
    allowed_player_changes = {"PLYR_DRAFTROUND", "PLYR_DRAFTPICK", "ThrowAccuracyShortRating",
                              "ThrowAccuracyMidRating", "OriginalThrowAccuracyShortRating",
                              "OriginalThrowAccuracyMidRating", "OverallRating",
                              "OriginalOverallRating", "OverallGrade0", "OverallGrade1",
                              "OverallGrade2", "OverallGrade3"}
    edited_player_by_row: dict[int, dict] = {}
    ranked_report = []
    draft_player_edits = []
    expected_rank_by_draft_row = {}
    expected_draft_fields_by_row: dict[int, dict] = {}
    score_by_draft_row = {}
    for rank, (draft_player, player) in enumerate(ordered, 1):
        round_number = (rank - 1) // TEAMS_PER_ROUND + 1 if rank <= TEAMS_PER_ROUND * DRAFT_ROUNDS else 63
        pick_in_round = (rank - 1) % TEAMS_PER_ROUND + 1 if round_number != 63 else 0
        player_after = dict(player)
        player_after["PLYR_DRAFTROUND"] = round_number
        player_after["PLYR_DRAFTPICK"] = pick_in_round
        fields = {key: value for key, value in player_after.items()
                  if key in allowed_player_changes and value != player.get(key)}
        if round_number != player.get("PLYR_DRAFTROUND"):
            fields["PLYR_DRAFTROUND"] = round_number
        if pick_in_round != player.get("PLYR_DRAFTPICK"):
            fields["PLYR_DRAFTPICK"] = pick_in_round
        if fields:
            player_edits.append({"row": player["row"], **fields})
        edited_player_by_row[player["row"]] = player_after

        evaluation = evaluations[player["row"]]
        expected_rank_by_draft_row[draft_player["row"]] = rank
        score_by_draft_row[draft_player["row"]] = evaluation["score"]
        production_grade = int(round(clamp(evaluation["production"], 0, 100)))
        draft_player_edits.append({
            "row": draft_player["row"],
            "InitialDraftRank": rank,
            "TrueOverallRanking": rank,
            "ProductionGrade": production_grade,
        })
        expected_draft_fields_by_row[draft_player["row"]] = {
            "InitialDraftRank": rank,
            "TrueOverallRanking": rank,
            "ProductionGrade": production_grade,
        }
        ranked_report.append({"rank": rank,
                              "scouting_rank": scouting_rank_by_player_row[player["row"]],
                              "player": player_after, "evaluation": evaluation})

    evaluation_edits = []
    evaluation_row_to_rank = {}
    for evaluation in data["evaluations"]:
        draft_player_row = evaluation.get("draftPlayerRow")
        if draft_player_row not in expected_rank_by_draft_row:
            raise SystemExit("A draft-board evaluation points to a prospect outside the ranked class.")
        rank = expected_rank_by_draft_row[draft_player_row]
        evaluation_row_to_rank[evaluation["row"]] = rank
        fields = {"row": evaluation["row"], "OverallRank": rank - 1,
                  "OverallValue": int(round(score_by_draft_row[draft_player_row]))}
        evaluation_edits.append(fields)

    if not data["boards"]:
        raise SystemExit("The save has no draft-board prospect lists to update.")
    board_edits = []
    for board in data["boards"]:
        if len(board["refs"]) != len(draft_rows) or len(set(board["refs"])) != len(board["refs"]):
            raise SystemExit(f"Team draft board {board['row']} is missing or duplicates prospects.")
        if any(ref not in evaluation_row_to_rank for ref in board["refs"]):
            raise SystemExit(f"Team draft board {board['row']} contains an unranked evaluation.")
        sorted_refs = sorted(board["refs"], key=lambda ref: evaluation_row_to_rank[ref])
        board_edits.append({"row": board["row"], "refs": sorted_refs})

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    position_counts: dict[tuple[int, str], int] = defaultdict(int)
    for item in ranked_report:
        round_number = (item["rank"] - 1) // TEAMS_PER_ROUND + 1
        group = POSITION_ROUND_GROUP.get(str(item["player"].get("Position", "")), "")
        if round_number <= DRAFT_ROUNDS:
            if group:
                position_counts[(round_number, group)] += 1
    for round_number in range(1, DRAFT_ROUNDS + 1):
        expected_counts = round_position_quota(round_number)
        actual_counts = {group: position_counts.get((round_number, group), 0)
                         for group in expected_counts}
        if actual_counts != expected_counts:
            raise SystemExit(f"Verification failed: round {round_number} does not match the documented position mix.")
    write_report(Path(args.report), ranked_report, position_counts)
    edits = {"players": player_edits, "draftPlayers": draft_player_edits,
             "evaluations": evaluation_edits, "boards": board_edits}
    edits_path.write_text(json.dumps(edits), encoding="utf-8")
    run_node("apply_draft_order.mjs", args.save, str(edits_path), args.output)
    run_node("export_draft_class.mjs", args.output, str(after_path))
    after = json.loads(after_path.read_text(encoding="utf-8"))

    after_by_row = {p["row"]: p for p in after["players"]}
    after_draft_by_row = {p["row"]: p for p in after["draftPlayers"]}
    after_evaluations = {e["row"]: e for e in after["evaluations"]}
    if len(after["players"]) != len(all_players):
        raise SystemExit("Verification failed: Player record count changed.")
    if len(after["draftPlayers"]) != len(data["draftPlayers"]):
        raise SystemExit("Verification failed: DraftPlayer record count changed.")
    for row, original in by_row.items():
        result = after_by_row.get(row)
        if result is None:
            raise SystemExit(f"Verification failed: player row {row} disappeared.")
        for identity in ("FirstName", "LastName", "Position", "College"):
            if result.get(identity) != original.get(identity):
                raise SystemExit(f"Verification failed: player identity field {identity} changed at row {row}.")
        for key, value in original.items():
            expected = edited_player_by_row.get(row, original)
            if result.get(key) != expected.get(key):
                raise SystemExit(f"Verification failed: unexpected Player.{key} value at row {row}.")
        if result.get("DevelopmentTrait") != original.get("DevelopmentTrait"):
            raise SystemExit(f"Verification failed: development trait changed at row {row}.")

    rank_values = []
    for draft_player in data["draftPlayers"]:
        result = after_draft_by_row.get(draft_player["row"])
        if result is None:
            raise SystemExit(f"Verification failed: DraftPlayer row {draft_player['row']} disappeared.")
        for key, value in draft_player.items():
            expected = expected_draft_fields_by_row.get(draft_player["row"], {}).get(key, value)
            if result.get(key) != expected:
                raise SystemExit(f"Verification failed: unexpected DraftPlayer.{key} change at row {draft_player['row']}.")
        if draft_player["row"] in expected_rank_by_draft_row:
            rank_values.append(result.get("TrueOverallRanking"))
            expected = expected_draft_fields_by_row[draft_player["row"]]
            for key, value in expected.items():
                if result.get(key) != value:
                    raise SystemExit(f"Verification failed: DraftPlayer.{key} did not persist at row {draft_player['row']}.")
    if sorted(rank_values) != list(range(1, len(draft_rows) + 1)):
        raise SystemExit("Verification failed: draft prospect ranks are not unique and complete.")

    expected_evaluation_ranks = {e["row"]: evaluation_row_to_rank[e["row"]] - 1
                                 for e in data["evaluations"]}
    if len(after_evaluations) != len(data["evaluations"]):
        raise SystemExit("Verification failed: a team evaluation record was lost.")
    for evaluation in data["evaluations"]:
        result = after_evaluations.get(evaluation["row"])
        draft_player_row = evaluation["draftPlayerRow"]
        if result is None or result.get("OverallRank") != expected_evaluation_ranks[evaluation["row"]] \
                or result.get("OverallValue") != int(round(score_by_draft_row[draft_player_row])):
            raise SystemExit(f"Verification failed: draft-board rank did not persist at evaluation {evaluation['row']}.")
        for key, value in evaluation.items():
            expected_value = expected_evaluation_ranks[evaluation["row"]] if key == "OverallRank" else value
            if key == "OverallValue":
                expected_value = int(round(score_by_draft_row[draft_player_row]))
            if result.get(key) != expected_value:
                raise SystemExit(f"Verification failed: unexpected evaluation.{key} change at row {evaluation['row']}.")

    after_board_refs = {b["row"]: b["refs"] for b in after["boards"]}
    if len(after_board_refs) != len(board_edits):
        raise SystemExit("Verification failed: a team draft board was lost.")
    for board in board_edits:
        refs = after_board_refs.get(board["row"])
        if refs != board["refs"]:
            raise SystemExit(f"Verification failed: team draft board {board['row']} was not reordered.")
        ranks = [evaluation_row_to_rank[ref] for ref in refs]
        if ranks != list(range(1, len(draft_rows) + 1)):
            raise SystemExit(f"Verification failed: team draft board {board['row']} is not in final rank order.")

    projected_picks = []
    for rank, (_, player) in enumerate(ordered, 1):
        result = after_by_row[player["row"]]
        expected_round = (rank - 1) // TEAMS_PER_ROUND + 1 if rank <= TEAMS_PER_ROUND * DRAFT_ROUNDS else 63
        expected_pick = (rank - 1) % TEAMS_PER_ROUND + 1 if expected_round != 63 else 0
        if result.get("PLYR_DRAFTROUND") != expected_round or result.get("PLYR_DRAFTPICK") != expected_pick:
            raise SystemExit(f"Verification failed: projected round/pick mismatch for rank {rank}.")
        if expected_round <= DRAFT_ROUNDS:
            projected_picks.append((expected_round, expected_pick))
    expected_picks = [(round_number, pick) for round_number in range(1, DRAFT_ROUNDS + 1)
                      for pick in range(1, TEAMS_PER_ROUND + 1)]
    if sorted(projected_picks) != expected_picks:
        raise SystemExit("Verification failed: projected selections contain a duplicate or missing pick.")
    for rank, (_, player) in enumerate(ordered[:TEAMS_PER_ROUND], 1):
        if player.get("Position") == "QB":
            final_player = after_by_row[player["row"]]
            if final_player.get("ThrowAccuracyShortRating", 0) < FIRST_ROUND_QB_ACCURACY_FLOOR \
                    or final_player.get("ThrowAccuracyMidRating", 0) < FIRST_ROUND_QB_ACCURACY_FLOOR:
                raise SystemExit(f"Verification failed: first-round QB at rank {rank} is below the accuracy floor.")

    print(f"Ranked {len(draft_rows)} draft prospects; assigned "
          f"{min(len(draft_rows), TEAMS_PER_ROUND * DRAFT_ROUNDS)} projected selections, "
          f"updated {len(evaluation_edits)} team evaluations, and reordered {len(board_edits)} team boards.")
    print("Applied the document's rounded position targets for each round; prospects are score-ranked within each target group.")
    print(f"Generated scouting report: {Path(args.report).resolve()}")
    print("Verified unique ranks, round/pick projections, player identity, and development traits.")


if __name__ == "__main__":
    main()
