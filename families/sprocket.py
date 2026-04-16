"""Sprocket — roller chain sprocket (ISO 606).

ISO 606 standard roller chain pitches (mm):
  6.35 (#25), 8.0 (#35), 9.525 (#41), 12.7 (#50), 15.875 (#60),
  19.05 (#80), 25.4 (#100), 31.75 (#120)

Geometry: disc with evenly spaced involute-like teeth cut into the periphery,
  central bore, optional keyway.

Key ISO 606 relations:
  PCD (pitch circle diameter) = p / sin(π/z)
  tip diameter    Da ≈ PCD + 0.8 × dr   (dr = roller diameter)
  root diameter   Df = PCD - dr
  where dr (roller diameter) is defined by chain pitch.

Easy:   plain toothed disc with bore
Medium: + hub (cylindrical boss behind disc)
Hard:   + keyway slot in bore
"""
import math

from .base import BaseFamily
from ..pipeline.builder import Op, Program

# ISO 606 pitches and corresponding roller diameters (mm)
_ISO606 = [
    (6.350,  3.30),   # #25
    (8.000,  5.00),   # #35 (non-standard metric)
    (9.525,  6.35),   # #41
    (12.700, 8.51),   # #50
    (15.875, 10.16),  # #60
    (19.050, 11.91),  # #80
    (25.400, 15.88),  # #100
]


class SprocketFamily(BaseFamily):
    name = "sprocket"

    def sample_params(self, difficulty: str, rng) -> dict:
        pitch, dr = _ISO606[int(rng.integers(0, len(_ISO606)))]

        # Tooth count: practical range 9–80; easy=smaller, hard=larger
        z_ranges = {"easy": (9, 18), "medium": (18, 36), "hard": (32, 60)}
        z_min, z_max = z_ranges.get(difficulty, (12, 40))
        n_teeth = int(rng.integers(z_min, z_max + 1))

        pcd = pitch / math.sin(math.pi / n_teeth)
        da = pcd + 0.8 * dr
        df = pcd - dr

        disc_thickness = round(rng.uniform(max(4.0, dr * 0.6), dr * 1.4), 1)
        bore_d = round(rng.uniform(df * 0.2, df * 0.45), 1)
        bore_d = max(bore_d, 5.0)

        params = {
            "pitch": pitch,
            "roller_diameter": dr,
            "n_teeth": n_teeth,
            "pitch_circle_diameter": round(pcd, 3),
            "tip_diameter": round(da, 3),
            "root_diameter": round(df, 3),
            "disc_thickness": disc_thickness,
            "bore_diameter": round(bore_d, 1),
            "difficulty": difficulty,
        }

        if difficulty in ("medium", "hard"):
            hub_d = round(bore_d * rng.uniform(1.8, 2.6), 1)
            hub_d = min(hub_d, df * 0.75)
            hub_h = round(disc_thickness * rng.uniform(0.6, 1.2), 1)
            params["hub_diameter"] = hub_d
            params["hub_height"] = hub_h

        if difficulty == "hard":
            # Keyway — DIN 6885 proportions based on bore diameter
            kw = round(bore_d * 0.25, 1)
            kd = round(bore_d * 0.12, 1)
            params["keyway_width"] = kw
            params["keyway_depth"] = kd

        return params

    def validate_params(self, params: dict) -> bool:
        df = params["root_diameter"]
        da = params["tip_diameter"]
        pcd = params["pitch_circle_diameter"]
        t = params["disc_thickness"]
        bore = params["bore_diameter"]
        z = params["n_teeth"]

        if z < 9 or df <= bore or da <= df or t < 3.0:
            return False
        if bore < 3.0 or bore >= df * 0.5:
            return False

        hub_d = params.get("hub_diameter", 0)
        if hub_d and hub_d >= df:
            return False

        kw = params.get("keyway_width", 0)
        kd = params.get("keyway_depth", 0)
        if kw and kd:
            if kw >= bore * 0.5 or kd >= bore * 0.3:
                return False

        return True

    def make_program(self, params: dict) -> Program:
        difficulty = params.get("difficulty", "easy")
        z = params["n_teeth"]
        da = params["tip_diameter"]
        df = params["root_diameter"]
        pcd = params["pitch_circle_diameter"]
        dr = params["roller_diameter"]
        t = params["disc_thickness"]
        bore = params["bore_diameter"]
        pitch = params["pitch"]

        ops, tags = [], {
            "has_hole": True, "has_slot": False,
            "has_fillet": False, "has_chamfer": False,
            "rotational": True,
        }

        # ── sprocket disc ──────────────────────────────────────────────────────
        # Tip-diameter cylinder, bore, then roller-seat holes at pitch circle.
        # Roller seat holes (radius = dr/2) centered on pitch circle create
        # the characteristic tooth valleys; material between = teeth.
        ops.append(Op("cylinder", {"height": t, "radius": round(da / 2, 4)}))

        # Central bore
        ops.append(Op("workplane", {"selector": ">Z"}))
        ops.append(Op("hole", {"diameter": round(bore, 4)}))

        # Roller-seat holes: N equally-spaced holes on pitch circle
        # Each hole diameter ≈ dr so it seats one roller
        ops.append(Op("workplane", {"selector": ">Z"}))
        ops.append(Op("polarArray", {
            "radius": round(pcd / 2, 4),
            "startAngle": 0,
            "angle": 360,
            "count": z,
        }))
        ops.append(Op("hole", {"diameter": round(dr * 0.97, 4)}))

        # ── hub (medium+) ──────────────────────────────────────────────────────
        hub_d = params.get("hub_diameter", 0)
        hub_h = params.get("hub_height", 0)
        if hub_d and hub_h:
            ops.append(Op("workplane", {"selector": "<Z"}))
            ops.append(Op("circle", {"radius": round(hub_d / 2, 4)}))
            ops.append(Op("extrude", {"distance": round(hub_h, 4)}))
            # bore through hub
            ops.append(Op("workplane", {"selector": "<Z"}))
            ops.append(Op("hole", {"diameter": round(bore, 4)}))

        # ── keyway (hard) ──────────────────────────────────────────────────────
        kw = params.get("keyway_width", 0)
        kd = params.get("keyway_depth", 0)
        if kw and kd:
            tags["has_slot"] = True
            ops.append(Op("workplane", {"selector": "XZ"}))
            ops.append(Op("moveTo", {"x": round(-kw / 2, 4), "y": 0.0}))
            ops.append(Op("lineTo", {"x": round(kw / 2, 4), "y": 0.0}))
            ops.append(Op("lineTo", {"x": round(kw / 2, 4), "y": round(bore / 2 + kd, 4)}))
            ops.append(Op("lineTo", {"x": round(-kw / 2, 4), "y": round(bore / 2 + kd, 4)}))
            ops.append(Op("close", {}))
            total_depth = t + (hub_h if hub_d else 0)
            ops.append(Op("cutBlind", {"depth": round(total_depth, 4)}))

        return Program(family=self.name, difficulty=difficulty,
                       params=params, ops=ops, feature_tags=tags)
