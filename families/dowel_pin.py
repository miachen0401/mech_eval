"""Dowel pin — precision cylindrical pin (ISO 8734 / DIN 6325).

ISO 8734 standard diameter series (mm): 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 16, 20
Tolerance: m6 (parallel) — geometry is a plain cylinder with chamfered ends.

Easy:   plain cylinder with end chamfers
Medium: + centre drill hole on one end (tolerance marking indentation)
Hard:   + second end differs (spring pin / grooved end style): axial groove cut
"""
import math

from .base import BaseFamily
from ..pipeline.builder import Op, Program

_ISO8734_DIAMETERS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]
# Standard length series for each nominal diameter (approximate; actual table truncated for codegen)
_LENGTH_OPTIONS = [6, 8, 10, 12, 16, 20, 24, 30, 36, 40, 50, 60, 80, 100]


class DowelPinFamily(BaseFamily):
    name = "dowel_pin"

    def sample_params(self, difficulty: str, rng) -> dict:
        d = float(rng.choice(_ISO8734_DIAMETERS[:10]))  # up to d=12 for reasonable rendering
        min_l = max(6, int(d * 2))
        max_l = min(100, int(d * 12))
        length_opts = [l for l in _LENGTH_OPTIONS if min_l <= l <= max_l]
        if not length_opts:
            length_opts = [min_l]
        length = float(rng.choice(length_opts))

        chamfer = round(d * 0.15, 2)  # ISO: 0.1–0.2 × d
        params = {
            "diameter": d,
            "length": length,
            "chamfer_length": chamfer,
            "difficulty": difficulty,
        }

        if difficulty in ("medium", "hard"):
            # Centre drill on one end — small conical indentation
            cd_d = round(min(d * 0.3, 1.5), 2)
            params["centre_drill_diameter"] = cd_d

        if difficulty == "hard":
            # Axial groove along ~half the length (like a slotted spring pin variant)
            groove_w = round(d * 0.2, 2)
            groove_d = round(d * 0.15, 2)
            params["groove_width"] = groove_w
            params["groove_depth"] = groove_d

        return params

    def validate_params(self, params: dict) -> bool:
        d = params["diameter"]
        l = params["length"]
        ch = params["chamfer_length"]

        if d < 1.0 or l < d * 2 or ch >= d * 0.3:
            return False

        cd = params.get("centre_drill_diameter", 0)
        if cd and cd >= d * 0.5:
            return False

        gw = params.get("groove_width", 0)
        gd = params.get("groove_depth", 0)
        if gw and gd:
            if gw >= d * 0.4 or gd >= d * 0.3:
                return False

        return True

    def make_program(self, params: dict) -> Program:
        difficulty = params.get("difficulty", "easy")
        d = params["diameter"]
        l = params["length"]
        ch = params["chamfer_length"]
        r = round(d / 2, 4)

        ops, tags = [], {
            "has_hole": False, "has_slot": False,
            "has_fillet": False, "has_chamfer": True,
            "rotational": True,
        }

        # Main cylinder
        ops.append(Op("cylinder", {"height": l, "radius": r}))

        # Chamfer both ends
        ops.append(Op("edges", {"selector": "|Z"}))
        ops.append(Op("chamfer", {"length": ch}))

        # Centre drill (medium+) — small blind hole on +Z face
        cd = params.get("centre_drill_diameter", 0)
        if cd:
            tags["has_hole"] = True
            cd_depth = round(cd * 1.2, 3)
            ops.append(Op("workplane", {"selector": ">Z"}))
            ops.append(Op("hole", {"diameter": round(cd, 4), "depth": cd_depth}))

        # Axial groove (hard) — longitudinal slot on one side
        gw = params.get("groove_width", 0)
        gd = params.get("groove_depth", 0)
        if gw and gd:
            tags["has_slot"] = True
            groove_l = round(l * 0.5, 3)
            # Work on the XZ plane (side of cylinder), offset to outer surface
            ops.append(Op("workplane", {"selector": "XZ", "origin": [0, round(r, 4), round(l / 2, 4)]}))
            ops.append(Op("slot2D", {
                "length": groove_l,
                "width": gw,
                "angle": 0,
            }))
            ops.append(Op("cutBlind", {"depth": gd}))

        return Program(family=self.name, difficulty=difficulty,
                       params=params, ops=ops, feature_tags=tags)
