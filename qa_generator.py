"""QA pair generation + ISO tag annotation for each sample.

For every family, defines:
  - qa_pairs : list of {question, answer, type, tolerance}
      type = "integer" | "ratio"
      Scoring: min(pred, gt) / max(pred, gt)  — symmetric ratio accuracy
  - iso_tags : dict of applicable ISO standards + derived values

Design rule:
  Prefer integer counts and dimensionless ratios — scale-invariant and
  directly answerable from images without knowing absolute dimensions.
  Use absolute mm only for ISO-mandated standard values (module, pitch).
"""
from __future__ import annotations
import math
from typing import Any


# ── helpers ───────────────────────────────────────────────────────────────────

def _q(question: str, answer: float, qtype: str = "ratio") -> dict:
    return {"question": question, "answer": round(float(answer), 4), "type": qtype}


def _ratio(a: float, b: float) -> float:
    """Return a/b, always ≥ 1 (larger/smaller — symmetric for scoring)."""
    if b <= 0:
        return 1.0
    return max(a, b) / min(a, b)


# ── family → QA + ISO ─────────────────────────────────────────────────────────

def get_qa_and_iso(family: str, params: dict) -> tuple[list[dict], dict]:
    fn = _REGISTRY.get(family)
    if fn is None:
        return [], {}
    return fn(params)


# ══════════════════════════════════════════════════════════════════════════════
# GEARS
# ══════════════════════════════════════════════════════════════════════════════

def _spur_gear(p: dict):
    m, z = p["module"], p["n_teeth"]
    qa = [
        _q("How many teeth does this gear have?", z, "integer"),
        _q("What is the gear module in mm?", m, "ratio"),
        _q("What is the outer-to-pitch diameter ratio?",
           _ratio(m * (z + 2), m * z)),
    ]
    iso = {
        "iso_53": True, "iso_54": True, "iso_1328_grade": {"easy": 10, "medium": 7, "hard": 4}.get(p.get("difficulty", "medium"), 7),
        "module": m, "n_teeth": z,
        "tip_diameter_mm": round(m * (z + 2), 3),
        "root_diameter_mm": round(m * (z - 2.5), 3),
        "pitch_diameter_mm": round(m * z, 3),
    }
    return qa, iso


def _helical_gear(p: dict):
    m, z = p["module"], p["n_teeth"]
    ha = p.get("helix_angle", 15.0)
    qa = [
        _q("How many teeth does this gear have?", z, "integer"),
        _q("What is the normal module in mm?", m, "ratio"),
        _q("What is the helix angle in degrees?", ha, "ratio"),
    ]
    iso = {"iso_53": True, "iso_54": True, "module": m, "n_teeth": z, "helix_angle_deg": ha}
    return qa, iso


def _bevel_gear(p: dict):
    m = p.get("module", p.get("face_module", 2.0))
    z = p["n_teeth"]
    ca = p.get("pitch_cone_angle", 45.0)
    qa = [
        _q("How many teeth does this bevel gear have?", z, "integer"),
        _q("What is the module in mm?", m, "ratio"),
        _q("What is the pitch cone angle in degrees?", ca, "ratio"),
    ]
    iso = {"iso_23509": True, "iso_54": True, "module": m, "n_teeth": z, "pitch_cone_angle_deg": round(ca, 2)}
    return qa, iso


def _worm_screw(p: dict):
    m = p.get("module", 2.0)
    ns = p.get("n_starts", 1)
    qa = [
        _q("How many thread starts does this worm have?", ns, "integer"),
        _q("What is the axial module in mm?", m, "ratio"),
    ]
    iso = {"iso_1122": True, "iso_54": True, "module": m, "n_starts": ns}
    return qa, iso


def _sprocket(p: dict):
    z = p["n_teeth"]
    pitch = p["pitch"]  # sprocket family uses "pitch", not "chain_pitch"
    pcd = p.get("pitch_circle_diameter", pitch / math.sin(math.pi / z))
    hub_d = p.get("hub_diameter", 0)
    qa = [
        _q("How many teeth does this sprocket have?", z, "integer"),
        _q("What is the chain pitch in mm?", pitch, "ratio"),
    ]
    if hub_d:
        qa.append(_q("What is the pitch circle to hub diameter ratio?", _ratio(pcd, hub_d)))
    iso = {"iso_606": True, "n_teeth": z, "chain_pitch_mm": pitch,
           "pitch_diameter_mm": round(pcd, 3)}
    return qa[:3], iso


# ══════════════════════════════════════════════════════════════════════════════
# FASTENERS
# ══════════════════════════════════════════════════════════════════════════════

def _bolt(p: dict):
    # bolt family uses shaft_diameter + shaft_length
    d = p.get("shaft_diameter", p.get("outer_diameter", 10.0))
    l = p.get("shaft_length", p.get("length", d * 4))
    pitch = p.get("thread_pitch")
    qa = [
        _q("What is the length-to-diameter ratio?", _ratio(l, d)),
        _q("What is the shank diameter in mm?", d, "ratio"),
    ]
    if pitch:
        qa.append(_q("What is the thread pitch in mm?", pitch, "ratio"))
    iso = {"iso_261": True, "iso_4014": True, "nominal_diameter_mm": round(d, 2), "length_mm": round(l, 2)}
    if pitch:
        iso["thread_pitch_mm"] = round(pitch, 3)
    return qa[:3], iso


def _hex_nut(p: dict):
    d = p.get("inner_diameter", p.get("thread_diameter", 10.0))
    s = p.get("across_flats", round(d * 1.7, 1))
    qa = [
        _q("What is the across-flats to thread diameter ratio?", _ratio(s, d)),
        _q("What is the thread diameter in mm?", d, "ratio"),
    ]
    iso = {"iso_4032": True, "thread_diameter_mm": round(d, 2), "across_flats_mm": round(s, 2)}
    return qa, iso


def _hex_standoff(p: dict):
    d, l = p.get("outer_diameter", 10.0), p.get("length", 20.0)
    qa = [
        _q("What is the length-to-diameter ratio?", _ratio(l, d)),
        _q("What is the body diameter in mm?", d, "ratio"),
    ]
    iso = {"iso_4766": True, "outer_diameter_mm": round(d, 2), "length_mm": round(l, 2)}
    return qa, iso


def _standoff(p: dict):
    return _hex_standoff(p)


def _threaded_adapter(p: dict):
    od = p.get("outer_diameter", p.get("outer_d", 20.0))
    id_ = p.get("inner_diameter", p.get("bore_d", 10.0))
    l = p.get("length", p.get("height", 30.0))
    qa = [
        _q("What is the outer-to-inner diameter ratio?", _ratio(od, id_)),
        _q("What is the length-to-outer-diameter ratio?", _ratio(l, od)),
    ]
    iso = {"iso_261": True}
    return qa, iso


def _dowel_pin(p: dict):
    d, l = p["diameter"], p["length"]
    qa = [
        _q("What is the length-to-diameter ratio?", _ratio(l, d)),
        _q("What is the pin diameter in mm?", d, "ratio"),
    ]
    iso = {"iso_8734": True, "diameter_mm": round(d, 2), "length_mm": round(l, 2)}
    return qa, iso


def _circlip(p: dict):
    d_shaft = p["shaft_diameter"]
    rod = p["ring_od"]
    rid = p["ring_id"]
    gap = p["gap_angle"]
    qa = [
        _q("What is the ring outer to inner diameter ratio?", _ratio(rod, rid)),
        _q("What is the shaft diameter this clip fits in mm?", d_shaft, "ratio"),
        _q("What is the opening gap angle in degrees?", gap, "ratio"),
    ]
    iso = {"din_471": True, "iso_464": True, "shaft_diameter_mm": round(d_shaft, 2)}
    return qa[:3], iso


# ══════════════════════════════════════════════════════════════════════════════
# PIPES & FLANGES
# ══════════════════════════════════════════════════════════════════════════════

def _pipe_flange(p: dict):
    # pipe_flange is a rectangular plate with bore: length × width × bore_diameter
    l = p["length"]
    w = p["width"]
    bd = p["bore_diameter"]
    qa = [
        _q("What is the plate length to width ratio?", _ratio(l, w)),
        _q("What is the plate width to bore diameter ratio?", _ratio(w, bd)),
    ]
    iso = {"iso_2768_1": True, "bore_diameter_mm": round(bd, 2)}
    return qa, iso


def _round_flange(p: dict):
    # round_flange is a circular disc with bore + optional bolt circle
    or_ = p["outer_radius"]
    ir = p["inner_radius"]
    nb = p.get("bolt_count", 0)
    qa = [
        _q("What is the outer to inner radius ratio?", _ratio(or_, ir)),
    ]
    if nb:
        qa.append(_q("How many bolt holes does the flange have?", nb, "integer"))
    iso = {"iso_7005": True, "outer_radius_mm": round(or_, 2), "inner_radius_mm": round(ir, 2)}
    if nb:
        iso["n_bolts"] = nb
    return qa[:3], iso


def _t_pipe_fitting(p: dict):
    od = p["outer_diameter"]
    wall = p["wall_thickness"]
    nb = p.get("n_bolts")
    qa = [
        _q("What is the outer diameter to wall thickness ratio?", _ratio(od, wall)),
        _q("What is the outer diameter in mm?", od, "ratio"),
    ]
    if nb:
        qa.append(_q("How many flange bolt holes?", nb, "integer"))
    iso = {"iso_1127": True, "outer_diameter_mm": round(od, 2), "wall_thickness_mm": round(wall, 2)}
    if nb:
        iso["n_bolts"] = nb
    return qa[:3], iso


def _pipe_elbow(p: dict):
    od = p.get("outer_radius", 20.0) * 2
    wall = p.get("wall_thickness", 2.0)
    bend_r = p.get("bend_radius", od)
    nb = p.get("n_bolts")
    qa = [
        _q("What is the bend radius to pipe OD ratio?", _ratio(bend_r, od)),
        _q("What is the pipe OD to wall thickness ratio?", _ratio(od, wall)),
    ]
    if nb:
        qa.append(_q("How many flange bolt holes?", nb, "integer"))
    iso = {"iso_1127": True, "iso_5252": True}
    return qa[:3], iso


def _hollow_tube(p: dict):
    ow = p["outer_width"]
    wall = p["wall_thickness"]
    l = p["length"]
    n_holes = p.get("n_mount_holes", 0)
    qa = [
        _q("What is the length to outer width ratio?", _ratio(l, ow)),
        _q("What is the outer width to wall thickness ratio?", _ratio(ow, wall)),
    ]
    if n_holes:
        qa.append(_q("How many mounting holes?", n_holes, "integer"))
    iso = {"iso_1127": True}
    return qa[:3], iso


def _nozzle(p: dict):
    r_in = p["inlet_radius"]
    r_out = p["outlet_radius"]
    l = p["length"]
    qa = [
        _q("What is the inlet-to-outlet radius ratio?", _ratio(r_in, r_out)),
        _q("What is the length to inlet diameter ratio?", _ratio(l, r_in * 2)),
    ]
    iso = {"iso_5167": True, "beta_ratio": round(min(r_in, r_out) / max(r_in, r_out), 4)}
    return qa, iso


# ══════════════════════════════════════════════════════════════════════════════
# SHAFTS & FITS
# ══════════════════════════════════════════════════════════════════════════════

def _stepped_shaft(p: dict):
    d_max = p.get("max_diameter", p.get("base_diameter", p.get("d1", 20.0)))
    l_tot = p.get("total_length", p.get("length", p.get("h1", 50.0)))
    n_steps = p.get("n_steps", 2)
    qa = [
        _q("What is the total length to max diameter ratio?", _ratio(l_tot, d_max)),
        _q("How many diameter steps does the shaft have?", n_steps, "integer"),
    ]
    iso = {"iso_286": True, "max_diameter_mm": round(d_max, 2), "total_length_mm": round(l_tot, 2)}
    return qa, iso


def _shaft_collar(p: dict):
    id_ = p.get("inner_diameter", p.get("bore_diameter", 10.0))
    od = p.get("outer_diameter", id_ * 1.8)
    qa = [
        _q("What is the outer to bore diameter ratio?", _ratio(od, id_)),
        _q("What is the bore diameter in mm?", id_, "ratio"),
    ]
    iso = {"iso_286": True, "bore_diameter_mm": round(id_, 2), "outer_diameter_mm": round(od, 2)}
    return qa, iso


def _lathe_turned_part(p: dict):
    d1 = p.get("d1", 30.0)
    d2 = p.get("d2", 20.0)
    h1 = p.get("h1", 40.0)
    h2 = p.get("h2", 20.0)
    has_bore = p.get("bore_diameter") is not None
    qa = [
        _q("What is the large-to-small diameter ratio?", _ratio(d1, d2)),
        _q("What is the total length to max diameter ratio?", _ratio(h1 + h2, max(d1, d2))),
        _q("Does this part have a central bore? (1=yes, 0=no)", 1.0 if has_bore else 0.0, "integer"),
    ]
    iso = {"iso_286": True}
    return qa, iso


def _tapered_boss(p: dict):
    d_base = p["base_diameter"]
    d_top = p["top_diameter"]
    h = p["height"]
    qa = [
        _q("What is the base to top diameter ratio?", _ratio(d_base, d_top)),
        _q("What is the height to base diameter ratio?", _ratio(h, d_base)),
    ]
    iso = {"iso_286": True, "taper_ratio": round(abs(d_base - d_top) / (2 * h), 4)}
    return qa, iso


def _spacer_ring(p: dict):
    od = p["outer_diameter"]
    wall = p["wall_thickness"]
    id_ = round(od - 2 * wall, 2)
    nb = p.get("n_holes", 0)
    qa = [
        _q("What is the outer to inner diameter ratio?", _ratio(od, id_)),
        _q("How many bolt holes?", nb, "integer"),
    ]
    iso = {"iso_286": True, "outer_diameter_mm": round(od, 2), "inner_diameter_mm": id_}
    return qa, iso


# ══════════════════════════════════════════════════════════════════════════════
# SPRINGS
# ══════════════════════════════════════════════════════════════════════════════

def _coil_spring(p: dict):
    n_active = p.get("n_active_coils", p.get("n_coils", 5))
    d_wire = p.get("wire_diameter", 2.0)
    d_mean = p.get("mean_coil_diameter", 20.0)
    qa = [
        _q("How many active coils does the spring have?", n_active, "integer"),
        _q("What is the spring index (mean coil D / wire D)?", _ratio(d_mean, d_wire)),
    ]
    iso = {"iso_2162": True, "n_active_coils": n_active, "spring_index": round(d_mean / d_wire, 3)}
    return qa, iso


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURAL PROFILES
# ══════════════════════════════════════════════════════════════════════════════

def _i_beam(p: dict):
    fw = p["flange_width"]
    h = p["total_height"]
    l = p["length"]
    nb = p.get("n_bolts", 0)
    qa = [
        _q("What is the total height to flange width ratio?", _ratio(h, fw)),
        _q("What is the length to total height ratio?", _ratio(l, h)),
    ]
    if nb:
        qa.append(_q("How many bolt holes per flange?", nb, "integer"))
    iso = {"iso_657_1": True, "total_height_mm": round(h, 1), "flange_width_mm": round(fw, 1)}
    return qa[:3], iso


def _u_channel(p: dict):
    ow = p["outer_width"]
    ah = p.get("arm_height", p.get("height", ow * 0.8))
    l = p["length"]
    qa = [
        _q("What is the arm height to flange width ratio?", _ratio(ah, ow)),
        _q("What is the length to outer width ratio?", _ratio(l, ow)),
    ]
    iso = {"iso_657_2": True, "outer_width_mm": round(ow, 1)}
    return qa, iso


def _t_slot_rail(p: dict):
    size = p["size"]
    l = p["length"]
    qa = [
        _q("What is the rail length to cross-section size ratio?", _ratio(l, size)),
        _q("What is the slot width in mm?", p.get("slot_opening", size * 0.45), "ratio"),
    ]
    iso = {"iso_299": True, "slot_size_mm": float(size)}
    return qa, iso


# ══════════════════════════════════════════════════════════════════════════════
# ROTATING MACHINERY
# ══════════════════════════════════════════════════════════════════════════════

def _impeller(p: dict):
    nb = p.get("n_blades", 5)
    od = p.get("outer_radius", p.get("tip_radius", 30.0)) * 2
    hub_d = p.get("hub_diameter", p.get("hub_radius", 10.0) * 2)
    qa = [
        _q("How many blades does this impeller have?", nb, "integer"),
        _q("What is the outer to hub diameter ratio?", _ratio(od, hub_d)),
    ]
    return qa, {"n_blades": nb}


def _propeller(p: dict):
    nb = p.get("n_blades", 3)
    bl = p.get("blade_length", 50.0)
    hub_d = p.get("hub_diameter", 20.0)
    qa = [
        _q("How many blades does this propeller have?", nb, "integer"),
        _q("What is the blade length to hub diameter ratio?", _ratio(bl, hub_d)),
    ]
    return qa, {}


def _fan_shroud(p: dict):
    fan_r = p.get("fan_radius", 40.0)
    plate = p.get("plate_side", fan_r * 2.5)
    qa = [
        _q("What is the plate side to fan radius ratio?", _ratio(plate, fan_r * 2)),
    ]
    return qa, {}


def _pulley(p: dict):
    rim_r = p["rim_radius"]
    bore_r = p["bore_radius"]
    n_sp = p.get("n_spokes", 0)
    ga = p.get("groove_angle", 38.0)
    qa = [
        _q("What is the rim to bore radius ratio?", _ratio(rim_r, bore_r)),
        _q("What is the groove angle in degrees?", ga, "ratio"),
    ]
    if n_sp:
        qa.append(_q("How many spokes does the pulley have?", n_sp, "integer"))
    iso = {"iso_22": True, "iso_4183": True, "groove_angle_deg": ga}
    return qa[:3], iso


def _handwheel(p: dict):
    od = p.get("outer_diameter", 200.0)
    bore = p.get("bore_diameter", 20.0)
    n_sp = p.get("n_spokes", 5)
    qa = [
        _q("How many spokes does the handwheel have?", n_sp, "integer"),
        _q("What is the outer to bore diameter ratio?", _ratio(od, bore)),
    ]
    iso = {"iso_4184": True, "outer_diameter_mm": round(od, 1)}
    return qa, iso


def _motor_end_cap(p: dict):
    od = p.get("outer_diameter", p.get("flange_diameter", 80.0))
    shaft_d = p["shaft_diameter"]
    nb = p.get("n_bolts", p.get("bolt_count", 4))
    qa = [
        _q("How many bolt holes does this end cap have?", nb, "integer"),
        _q("What is the outer to shaft diameter ratio?", _ratio(od, shaft_d)),
    ]
    iso = {"iec_60072": True, "n_bolts": nb}
    return qa, iso


def _cam(p: dict):
    base_r = p["base_radius"]
    ecc = p.get("eccentricity", 0.0)
    n_lobes = p.get("n_lobes", 0)
    bore_r = p.get("bore_diameter", base_r * 0.3)
    if n_lobes and n_lobes > 0:
        qa = [
            _q("How many lobes does this cam have?", n_lobes, "integer"),
            _q("What is the base radius to bore ratio?", _ratio(base_r, bore_r)),
        ]
    else:
        qa = [
            _q("What is the eccentricity to base radius ratio?", _ratio(ecc, base_r) if ecc > 0 else 1.0),
            _q("What is the base radius to bore radius ratio?", _ratio(base_r, bore_r)),
        ]
    return qa, {}


# ══════════════════════════════════════════════════════════════════════════════
# MACHINE ELEMENTS
# ══════════════════════════════════════════════════════════════════════════════

def _hinge(p: dict):
    nk = p["n_knuckles"]
    # hinge family uses leaf_width × leaf_height (not leaf_length)
    lw = p.get("leaf_width", p.get("leaf_length", 40.0))
    lh = p.get("leaf_height", p.get("leaf_length", lw * 2))
    qa = [
        _q("How many knuckles does this hinge have?", nk, "integer"),
        _q("What is the leaf height to width ratio?", _ratio(lh, lw)),
    ]
    iso = {"iso_3669": True, "n_knuckles": nk}
    return qa, iso


def _bearing_retainer_cap(p: dict):
    boss_od = p["boss_diameter"]
    bore_d = p["bore_diameter"]
    nb = p.get("n_bolts", 0)
    qa = [
        _q("What is the boss to bore diameter ratio?", _ratio(boss_od, bore_d)),
    ]
    if nb:
        qa.append(_q("How many bolt holes?", nb, "integer"))
    fod = p.get("flange_diameter")
    if fod:
        qa.append(_q("What is the flange to boss diameter ratio?", _ratio(fod, boss_od)))
    iso = {"iso_281": True, "bore_diameter_mm": round(bore_d, 2), "boss_diameter_mm": round(boss_od, 2)}
    return qa[:3], iso


def _piston(p: dict):
    r = p["radius"]
    h = p["height"]
    pin_d = p.get("pin_diameter", r * 0.4)
    qa = [
        _q("What is the height to diameter ratio?", _ratio(h, r * 2)),
        _q("What is the pin to piston diameter ratio?", _ratio(pin_d, r * 2)),
    ]
    iso = {"iso_6621": True}
    return qa, iso


def _connecting_rod(p: dict):
    big_r = p["big_end_radius"]
    small_r = p["small_end_radius"]
    cd = p["center_distance"]
    qa = [
        _q("What is the big-end to small-end bore radius ratio?", _ratio(big_r, small_r)),
        _q("What is the center distance to big-end diameter ratio?", _ratio(cd, big_r * 2)),
    ]
    return qa, {}


def _clevis(p: dict):
    arm_t = p["arm_thickness"]
    gap_w = p["gap_width"]
    pin_d = p.get("pin_diameter", gap_w * 0.6)
    qa = [
        _q("What is the gap width to arm thickness ratio?", _ratio(gap_w, arm_t)),
        _q("What is the pin to gap width ratio?", _ratio(pin_d, gap_w)),
    ]
    iso = {"iso_8140": True}
    return qa, iso


def _dovetail_slide(p: dict):
    wt = p["width_top"]
    wb = p["width_bottom"]
    angle = p.get("angle_deg", 45.0)
    qa = [
        _q("What is the top to bottom width ratio?", _ratio(wt, wb)),
        _q("What is the dovetail angle in degrees?", angle, "ratio"),
    ]
    return qa, {}


def _flat_link(p: dict):
    boss_r = p["boss_radius"]
    cc = p["cc_distance"]
    qa = [
        _q("What is the center-to-center distance to boss diameter ratio?", _ratio(cc, boss_r * 2)),
    ]
    return qa, {}


def _dog_bone(p: dict):
    boss_r = p["boss_radius"]
    cc = p["cc_distance"]
    waist_r = p.get("waist_radius", boss_r * 0.6)
    qa = [
        _q("What is the center-to-center to boss diameter ratio?", _ratio(cc, boss_r * 2)),
        _q("What is the boss to waist radius ratio?", _ratio(boss_r, waist_r)),
    ]
    return qa, {}


def _manifold_block(p: dict):
    nc = p["n_channels"]
    cd = p["channel_diameter"]
    qa = [
        _q("How many channels does this manifold have?", nc, "integer"),
        _q("What is the block length to channel diameter ratio?",
           _ratio(p.get("length", 60.0), cd)),
    ]
    iso = {"iso_4401": True, "n_channels": nc}
    return qa, iso


def _torus_link(p: dict):
    maj_r = p["major_radius"]
    min_r = p["minor_radius"]
    qa = [
        _q("What is the major to minor radius ratio?", _ratio(maj_r, min_r)),
    ]
    return qa, {}


# ══════════════════════════════════════════════════════════════════════════════
# PLATES & BRACKETS
# ══════════════════════════════════════════════════════════════════════════════

def _mounting_plate(p: dict):
    l = p.get("length", 80.0)
    w = p.get("width", 60.0)
    t = p.get("thickness", 5.0)
    qa = [
        _q("What is the length to width ratio?", _ratio(l, w)),
        _q("What is the length to thickness ratio?", _ratio(l, t)),
    ]
    return qa, {"iso_2768": True}


def _slotted_plate(p: dict):
    return _mounting_plate(p)


def _waffle_plate(p: dict):
    nx = p.get("n_ribs_x", p.get("nx", 4))
    ny = p.get("n_ribs_y", p.get("ny", 4))
    qa = [
        _q("How many ribs in the X direction?", nx, "integer"),
        _q("How many ribs in the Y direction?", ny, "integer"),
    ]
    return qa, {"iso_2768": True}


def _rib_plate(p: dict):
    rc = p.get("rib_count", p.get("n_ribs", 4))
    l = p.get("length", 100.0)
    bh = p.get("base_thickness", 5.0)
    rh = p.get("rib_height", 20.0)
    qa = [
        _q("How many ribs does this plate have?", rc, "integer"),
        _q("What is the rib height to base thickness ratio?", _ratio(rh, bh)),
    ]
    return qa, {"iso_2768": True}


def _sheet_metal_tray(p: dict):
    l = p["length"]
    w = p["width"]
    h = p["height"]
    nb = p.get("n_mount_holes", 0)
    qa = [
        _q("What is the length to width ratio?", _ratio(l, w)),
        _q("What is the tray height to length ratio?", _ratio(h, l)),
    ]
    if nb:
        qa.append(_q("How many mounting holes?", nb, "integer"))
    return qa[:3], {"iso_2768": True}


def _heat_sink(p: dict):
    nf = p.get("n_fins", 8)
    fh = p.get("fin_height", 15.0)
    bh = p.get("base_height", p.get("base_thickness", 4.0))
    nm = p.get("n_mount_holes", 0)
    qa = [
        _q("How many fins does the heat sink have?", nf, "integer"),
        _q("What is the fin height to base height ratio?", _ratio(fh, bh)),
    ]
    if nm:
        qa.append(_q("How many mounting holes?", nm, "integer"))
    return qa[:3], {}


def _l_bracket(p: dict):
    a1 = p.get("arm1_length", p.get("flange_length", 60.0))
    a2 = p.get("arm2_height", p.get("web_height", 60.0))
    has_hole = p.get("hole_diameter") is not None
    qa = [
        _q("What is the arm1 to arm2 length ratio?", _ratio(a1, a2)),
        _q("Does this bracket have mounting holes? (1=yes, 0=no)", 1.0 if has_hole else 0.0, "integer"),
    ]
    return qa, {}


def _z_bracket(p: dict):
    nb = p.get("n_base_holes", p.get("n_holes", 2))
    base_l = p.get("base_length", 60.0)
    arm_h = p.get("arm_height", 40.0)
    qa = [
        _q("How many base mounting holes?", nb, "integer"),
        _q("What is the base length to arm height ratio?", _ratio(base_l, arm_h)),
    ]
    return qa, {}


def _mounting_angle(p: dict):
    nb_base = p.get("n_base_holes", 2)
    nb_web = p.get("n_web_holes", 2)
    qa = [
        _q("How many base holes?", nb_base, "integer"),
        _q("How many web holes?", nb_web, "integer"),
    ]
    return qa, {}


def _gusseted_bracket(p: dict):
    fw = p.get("flange_width", 60.0)
    gh = p.get("gusset_height", 40.0)
    has_pocket = p.get("pocket_depth") is not None
    qa = [
        _q("What is the flange width to gusset height ratio?", _ratio(fw, gh)),
        _q("Does this bracket have a pocket? (1=yes, 0=no)", 1.0 if has_pocket else 0.0, "integer"),
    ]
    return qa, {}


def _enclosure(p: dict):
    l, w, h = p["length"], p["width"], p["height"]
    nm = p.get("n_mount_holes", 0)
    nv = p.get("n_vent_rows", 0)
    qa = [
        _q("What is the length to width ratio?", _ratio(l, w)),
    ]
    if nm:
        qa.append(_q("How many mounting holes?", nm, "integer"))
    if nv:
        qa.append(_q("How many vent rows?", nv, "integer"))
    return qa[:3], {}


def _rect_frame(p: dict):
    ol = p["outer_length"]
    ow = p["outer_width"]
    qa = [
        _q("What is the outer length to width ratio?", _ratio(ol, ow)),
    ]
    return qa, {}


# ══════════════════════════════════════════════════════════════════════════════
# PERFORATED PANELS & GRIDS
# ══════════════════════════════════════════════════════════════════════════════

def _vented_panel(p: dict):
    nx = p.get("nx", p.get("n_cols", 4))
    ny = p.get("ny", p.get("n_rows", 4))
    qa = [
        _q("How many hole columns?", nx, "integer"),
        _q("How many hole rows?", ny, "integer"),
    ]
    iso = {"iso_4783": True}
    return qa, iso


def _mesh_panel(p: dict):
    nc = p.get("n_cols", 6)
    nr = p.get("n_rows", 4)
    hd = p.get("hole_diameter", 5.0)
    pitch = p.get("pitch", hd * 2.0)
    qa = [
        _q("How many hole columns?", nc, "integer"),
        _q("How many hole rows?", nr, "integer"),
        _q("What is the pitch to hole diameter ratio?", _ratio(pitch, hd)),
    ]
    iso = {"iso_4783": True}
    return qa, iso


def _wire_grid(p: dict):
    nx = p.get("n_x", p.get("nx", 5))
    ny = p.get("n_y", p.get("ny", 5))
    qa = [
        _q("How many wires in the X direction?", nx, "integer"),
        _q("How many wires in the Y direction?", ny, "integer"),
    ]
    return qa, {}


def _cable_routing_panel(p: dict):
    nc = p.get("n_slot_cols", 3)
    nr = p.get("n_slot_rows", 2)
    nh = p.get("n_holes", 4)
    qa = [
        _q("How many slot columns?", nc, "integer"),
        _q("How many slot rows?", nr, "integer"),
        _q("How many fastener holes?", nh, "integer"),
    ]
    return qa, {}


def _pcb_standoff_plate(p: dict):
    n_post = p.get("mid_post_count", 4)
    nm = p.get("n_mount_holes", 4)  # corner mount holes
    l = p.get("length", 80.0)
    w = p.get("width", 60.0)
    qa = [
        _q("How many standoff posts?", n_post, "integer"),
        _q("What is the board length to width ratio?", _ratio(l, w)),
    ]
    return qa, {}


def _connector_faceplate(p: dict):
    nc = p.get("n_cutouts", 2)
    l = p.get("length", 80.0)
    w = p.get("width", 40.0)
    qa = [
        _q("How many connector cutouts?", nc, "integer"),
        _q("What is the plate length to width ratio?", _ratio(l, w)),
    ]
    return qa, {}


# ══════════════════════════════════════════════════════════════════════════════
# MISC / ORGANIC
# ══════════════════════════════════════════════════════════════════════════════

def _ball_knob(p: dict):
    ball_r = p.get("ball_radius", p.get("radius", 20.0))
    stem_r = p.get("stem_radius", ball_r * 0.3)
    stem_h = p.get("stem_height", ball_r * 1.2)
    qa = [
        _q("What is the ball to stem radius ratio?", _ratio(ball_r, stem_r)),
        _q("What is the stem height to ball radius ratio?", _ratio(stem_h, ball_r)),
    ]
    return qa, {}


def _knob(p: dict):
    base_r = p.get("base_radius", 20.0)
    top_r = p.get("top_radius", base_r * 0.7)
    h = p.get("total_height", base_r * 1.5)
    qa = [
        _q("What is the base to top radius ratio?", _ratio(base_r, top_r)),
        _q("What is the height to base radius ratio?", _ratio(h, base_r)),
    ]
    return qa, {}


def _dome_cap(p: dict):
    r = p["radius"]
    h = p.get("cyl_height", r * 0.5)
    nb = p.get("n_holes", 0)
    qa = [
        _q("What is the cylinder height to dome radius ratio?", _ratio(h, r)),
    ]
    if nb:
        qa.append(_q("How many holes on the dome?", nb, "integer"))
    return qa, {}


def _bellows(p: dict):
    nc = p.get("n_convolutions", 4)
    od = p.get("outer_radius", 30.0) * 2
    id_ = p.get("inner_radius", 20.0) * 2
    qa = [
        _q("How many convolutions does this bellows have?", nc, "integer"),
        _q("What is the outer to inner diameter ratio?", _ratio(od, id_)),
    ]
    iso = {"iso_10380": True}
    return qa, iso


def _capsule(p: dict):
    r = p["radius"]
    cyl_h = p.get("cyl_height", r * 2.0)
    qa = [
        _q("What is the cylinder height to end-cap radius ratio?", _ratio(cyl_h, r)),
    ]
    return qa, {}


def _star_blank(p: dict):
    np_ = p.get("n_points", 5)
    od = p.get("outer_radius", 40.0)
    id_ = p.get("inner_radius", 20.0)
    qa = [
        _q("How many points does this star have?", np_, "integer"),
        _q("What is the outer to inner radius ratio?", _ratio(od, id_)),
    ]
    return qa, {}


def _cruciform(p: dict):
    arm_l = p.get("arm_length", 40.0)
    arm_w = p.get("arm_width", 12.0)
    qa = [
        _q("What is the arm length to arm width ratio?", _ratio(arm_l, arm_w)),
    ]
    return qa, {}


def _ratchet_sector(p: dict):
    ns = p.get("n_slots", 4)
    arc_h = p.get("arc_holes", 3)
    angle = p.get("angle_deg", 60.0)
    qa = [
        _q("How many radial slots does this ratchet sector have?", ns, "integer"),
        _q("How many arc holes?", arc_h, "integer"),
        _q("What is the sector angle in degrees?", angle, "ratio"),
    ]
    return qa, {}


def _snap_clip(p: dict):
    cr = p["clip_radius"]
    wt = p["wall_thickness"]
    oa = p["opening_angle"]
    nb = p.get("n_flange_holes", 0)
    qa = [
        _q("What is the clip radius to wall thickness ratio?", _ratio(cr, wt)),
        _q("What is the opening angle in degrees?", oa, "ratio"),
    ]
    if nb:
        qa.append(_q("How many flange holes?", nb, "integer"))
    return qa[:3], {}


def _locator_block(p: dict):
    vd = p.get("v_depth", 10.0)
    vwt = p.get("v_width_top", 20.0)
    nb = p.get("n_holes", p.get("n_mount_holes", 2))
    qa = [
        _q("How many mounting holes?", nb, "integer"),
        _q("What is the V-slot depth to top width ratio?", _ratio(vd, vwt)),
    ]
    return qa, {}


def _bucket(p: dict):
    rb = p.get("r_bottom", 20.0)
    rt = p.get("r_top", 30.0)
    h = p.get("height", 40.0)
    qa = [
        _q("What is the top to bottom radius ratio?", _ratio(rt, rb)),
        _q("What is the height to bottom diameter ratio?", _ratio(h, rb * 2)),
    ]
    return qa, {}


def _table(p: dict):
    tl = p.get("top_length", 120.0)
    tw = p.get("top_width", 80.0)
    lh = p.get("leg_height", 70.0)
    qa = [
        _q("What is the tabletop length to width ratio?", _ratio(tl, tw)),
        _q("What is the leg height to tabletop length ratio?", _ratio(lh, tl)),
    ]
    return qa, {}


def _duct_elbow(p: dict):
    dw = p.get("duct_width", 40.0)
    dh = p.get("duct_height", 40.0)
    br = p.get("bend_radius", 60.0)
    qa = [
        _q("What is the bend radius to duct width ratio?", _ratio(br, dw)),
        _q("What is the duct height to width ratio?", _ratio(dh, dw)),
    ]
    return qa, {}


# ── registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Any] = {
    # gears
    "spur_gear":            _spur_gear,
    "helical_gear":         _helical_gear,
    "bevel_gear":           _bevel_gear,
    "worm_screw":           _worm_screw,
    "sprocket":             _sprocket,
    # fasteners
    "bolt":                 _bolt,
    "hex_nut":              _hex_nut,
    "hex_standoff":         _hex_standoff,
    "standoff":             _standoff,
    "threaded_adapter":     _threaded_adapter,
    "dowel_pin":            _dowel_pin,
    "circlip":              _circlip,
    # pipes & flanges
    "pipe_flange":          _pipe_flange,
    "round_flange":         _round_flange,
    "t_pipe_fitting":       _t_pipe_fitting,
    "pipe_elbow":           _pipe_elbow,
    "hollow_tube":          _hollow_tube,
    "nozzle":               _nozzle,
    # shafts & fits
    "stepped_shaft":        _stepped_shaft,
    "shaft_collar":         _shaft_collar,
    "lathe_turned_part":    _lathe_turned_part,
    "tapered_boss":         _tapered_boss,
    "spacer_ring":          _spacer_ring,
    # springs
    "coil_spring":          _coil_spring,
    # structural profiles
    "i_beam":               _i_beam,
    "u_channel":            _u_channel,
    "t_slot_rail":          _t_slot_rail,
    # rotating machinery
    "impeller":             _impeller,
    "propeller":            _propeller,
    "fan_shroud":           _fan_shroud,
    "pulley":               _pulley,
    "handwheel":            _handwheel,
    "motor_end_cap":        _motor_end_cap,
    "cam":                  _cam,
    # machine elements
    "hinge":                _hinge,
    "bearing_retainer_cap": _bearing_retainer_cap,
    "piston":               _piston,
    "connecting_rod":       _connecting_rod,
    "clevis":               _clevis,
    "dovetail_slide":       _dovetail_slide,
    "flat_link":            _flat_link,
    "dog_bone":             _dog_bone,
    "manifold_block":       _manifold_block,
    "torus_link":           _torus_link,
    # plates & brackets
    "mounting_plate":       _mounting_plate,
    "slotted_plate":        _slotted_plate,
    "waffle_plate":         _waffle_plate,
    "rib_plate":            _rib_plate,
    "sheet_metal_tray":     _sheet_metal_tray,
    "heat_sink":            _heat_sink,
    "l_bracket":            _l_bracket,
    "z_bracket":            _z_bracket,
    "mounting_angle":       _mounting_angle,
    "gusseted_bracket":     _gusseted_bracket,
    "enclosure":            _enclosure,
    "rect_frame":           _rect_frame,
    # panels & grids
    "vented_panel":         _vented_panel,
    "mesh_panel":           _mesh_panel,
    "wire_grid":            _wire_grid,
    "cable_routing_panel":  _cable_routing_panel,
    "pcb_standoff_plate":   _pcb_standoff_plate,
    "connector_faceplate":  _connector_faceplate,
    # misc
    "ball_knob":            _ball_knob,
    "knob":                 _knob,
    "dome_cap":             _dome_cap,
    "bellows":              _bellows,
    "capsule":              _capsule,
    "star_blank":           _star_blank,
    "cruciform":            _cruciform,
    "ratchet_sector":       _ratchet_sector,
    "snap_clip":            _snap_clip,
    "locator_block":        _locator_block,
    "bucket":               _bucket,
    "table":                _table,
    "duct_elbow":           _duct_elbow,
}
