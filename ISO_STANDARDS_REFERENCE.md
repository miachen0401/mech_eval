# ISO Standards Reference

Applied ISO standards in the MechEval CAD synthesis pipeline.

**Columns:**
- **Standard** — ISO number + edition
- **Title** — official short title
- **Scope** — what it governs
- **Code param** — param key in `sample_params()` / `iso_tags`
- **Constraint / formula** — how it is enforced in code
- **Family / subfamily** — families where it is active
- **Status** — ✅ enforced in sampler | ⚙️ tagged only (not yet enforced) | 🔲 planned

---

## Gears

| Standard | Title | Scope | Code param | Constraint / formula | Family | Status |
|----------|-------|-------|-----------|----------------------|--------|--------|
| **ISO 54:1996** | Cylindrical gears — modules | Preferred module series for cylindrical gears | `module` | Sampled from R20+R40 series: `{0.8, 1.0, 1.125, 1.25, 1.375, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0}` | `spur_gear`, `helical_gear`, `bevel_gear` | ✅ |
| **ISO 53:1998** | Cylindrical gears — basic rack tooth profile | Standard involute tooth geometry | `module`, `n_teeth`, `pressure_angle` | `da = m*(z+2)`, `df = m*(z−2.5)`, `d = m*z`, `α = 20°`, tip radius `= 0.38m` | `spur_gear`, `helical_gear` | ✅ geometry; ⚙️ compliance score |
| **ISO 1328-1:2013** | Cylindrical gears — flank tolerance classification | Accuracy grade 1 (finest) – 12 (coarsest) | `difficulty` → `iso_1328_grade` | Mapped: easy→10, medium→7, hard→4 | `spur_gear`, `helical_gear`, `bevel_gear` | ⚙️ tagged |
| **ISO 23509:2016** | Bevel and hypoid gear geometry | Bevel gear tooth geometry | `module`, `n_teeth`, `pitch_cone_angle` | `d = m*z`, cone angle sampled from valid range | `bevel_gear` | ⚙️ tagged |
| **ISO 1122-1:1998** | Vocabulary of gear terms — cylindrical gears | Worm gear terminology & geometry | `module`, `n_starts`, `lead_angle` | Lead angle `λ = arctan(n_starts / (z_worm * m))` | `worm_screw` | ⚙️ tagged |

### Gear QA questions (Task B/C)

| Family | Q1 | Q2 | Q3 |
|--------|----|----|-----|
| `spur_gear` | How many teeth? (integer) | Module mm? (ratio, ±5%) | Pitch circle diameter mm? (ratio, ±5%) |
| `helical_gear` | How many teeth? | Module mm? | Helix angle °? |
| `bevel_gear` | How many teeth? | Module mm? | Pitch cone angle °? |
| `worm_screw` | How many starts? (integer) | Axial module mm? | — |

---

## Fasteners

| Standard | Title | Scope | Code param | Constraint / formula | Family | Status |
|----------|-------|-------|-----------|----------------------|--------|--------|
| **ISO 261:1998** | Metric screw threads — general plan | Metric thread nominal diameters & pitches | `outer_diameter`, `thread_pitch` | Coarse-pitch series: M1–M300; `pitch` from standard table | `bolt` | ⚙️ tagged; 🔲 pitch table enforcement |
| **ISO 4032:2012** | Hexagon regular nuts — style 1 | Hex nut dimensions across-flats vs thread | `inner_diameter`, `across_flats` | `s ≈ 1.7×d` (across-flats approx) | `hex_nut` | ⚙️ tagged |
| **ISO 4766:2016** | Slotted set screws / standoffs | Threaded standoff OD & length | `outer_diameter`, `length` | Standard OD series M3–M20 | `hex_standoff` | ⚙️ tagged; 🔲 OD series enforcement |
| **ISO 4762:2004** | Hexagon socket head cap screws | Socket head geometry | — | Not yet parameterized | — | 🔲 planned |

### Fastener QA questions

| Family | Q1 | Q2 | Q3 |
|--------|----|----|-----|
| `bolt` | Length/diameter ratio? (ratio) | Shank diameter mm? | Thread pitch mm? |
| `hex_nut` | Thread diameter mm? | Across-flats width mm? | — |
| `hex_standoff` | Length/diameter ratio? | Body diameter mm? | — |

---

## Pipes & Flanges

| Standard | Title | Scope | Code param | Constraint / formula | Family | Status |
|----------|-------|-------|-----------|----------------------|--------|--------|
| **ISO 1127:1992** | Stainless steel tubes — dimensions & tolerances | Tube OD/wall thickness series | `outer_diameter`, `wall_thickness` | OD from DN series; `wall_ratio = wall/OD` in `[0.04, 0.25]` | `t_pipe_fitting`, `pipe_elbow`, `hollow_tube` | ⚙️ tagged; 🔲 DN series enforcement |
| **ISO 7005-1:2011** | Metallic flanges (steel) | Flange OD, PCD, bolt count vs PN class | `flange_od`, `bolt_pcd`, `n_bolts` | PN16/PN25/PN40 series; `flange_od / pipe_od ≥ 1.5` | `pipe_flange`, `round_flange` | ⚙️ tagged |
| **ISO 10423:2009** | Wellhead equipment — flanges | High-pressure flange geometry | — | Not parameterized | — | 🔲 future |

### Pipe/Flange QA questions

| Family | Q1 | Q2 | Q3 |
|--------|----|----|-----|
| `pipe_flange` | How many bolt holes? (integer) | Flange OD / pipe OD ratio? | — |
| `t_pipe_fitting` | Wall thickness / OD ratio? | Outer diameter mm? | Bolt hole count? (integer) |

---

## Shafts & Fits

| Standard | Title | Scope | Code param | Constraint / formula | Family | Status |
|----------|-------|-------|-----------|----------------------|--------|--------|
| **ISO 286-1:2010** | Limits & fits — standard tolerances | IT grades (IT01–IT18) on shaft/hole | `outer_diameter`, `inner_diameter`, `bore_diameter` | Diameter steps from ISO 286 table; tolerance grade maps to difficulty | `stepped_shaft`, `shaft_collar`, `hex_standoff` | ⚙️ tagged; 🔲 IT grade enforcement |
| **ISO 773:1969** | Rectangular keys & keyways | Keyway width/height vs shaft diameter | `keyway_width`, `keyway_height`, `bore_diameter` | `w × h` from standard table: d=6→2×2, d=10→3×3, d=22→6×6 ... | `spur_gear` (hard variant), `stepped_shaft` | 🔲 table enforcement |

### Shaft QA questions

| Family | Q1 | Q2 |
|--------|----|----|
| `stepped_shaft` | Length / max diameter ratio? | Number of diameter steps? (integer) |
| `shaft_collar` | OD / bore diameter ratio? | Bore diameter mm? |

---

## Springs

| Standard | Title | Scope | Code param | Constraint / formula | Family | Status |
|----------|-------|-------|-----------|----------------------|--------|--------|
| **ISO 2162-1:1993** | Springs — vocabulary | Coil spring terminology & definitions | `n_active_coils`, `wire_diameter`, `mean_coil_diameter` | Spring index `C = D_mean / d_wire ∈ [4, 20]` (practical range) | `coil_spring` | ⚙️ tagged |
| **ISO 26909:2009** | Springs — vocabulary (update) | Replaces ISO 2162 for terminology | Same as above | — | `coil_spring` | ⚙️ tagged |

### Spring QA questions

| Family | Q1 | Q2 |
|--------|----|----|
| `coil_spring` | How many active coils? (integer) | Spring index (D_mean / d_wire)? |

---

## General Tolerances & Plates

| Standard | Title | Scope | Code param | Constraint / formula | Family | Status |
|----------|-------|-------|-----------|----------------------|--------|--------|
| **ISO 2768-1:1989** | General tolerances — linear dimensions | Default manufacturing tolerances for unspecified dims | `length`, `width`, `thickness` | Class f/m/c/v maps to difficulty; no geometry constraint, metadata only | `mounting_plate`, `slotted_plate`, `waffle_plate`, `sheet_metal_tray` | ⚙️ tagged |

### Plate QA questions

| Family | Q1 | Q2 |
|--------|----|----|
| `mounting_plate` | Length / width ratio? | Slenderness (length/thickness)? |
| `waffle_plate` | Rib count in X? (integer) | Rib count in Y? (integer) |

---

## Compliance Metrics (bench/metrics)

| Metric | Formula | Families | Notes |
|--------|---------|---------|-------|
| `iso53_compliance` | `1 - mean_rel_err(da, df, d)` vs ISO 53 formulas | `spur_gear`, `helical_gear` | Detects "visually correct but industrially invalid" |
| `qa_score_single` | `min(pred, gt) / max(pred, gt)` | All QA families | Symmetric ratio, no threshold needed |
| `qa_score` | Mean of `qa_score_single` over all pairs | All QA families | 0–1, higher = better |

---

## Enforcement Status Summary

| Status | Meaning |
|--------|---------|
| ✅ **enforced** | Sampler already draws from standard series / formula enforced in `validate_params` |
| ⚙️ **tagged** | `iso_tags` field populated; geometry approximately correct but not strictly constrained |
| 🔲 **planned** | Standard identified, constraint not yet implemented |

### Priority backlog (🔲 → ✅)

1. `bolt`: ISO 261 coarse-pitch table (`outer_diameter` → standard pitch)
2. `hex_standoff`: ISO 4766 OD series
3. `spur_gear` (hard): ISO 773 keyway table (`bore_diameter` → `keyway_width × height`)
4. `t_pipe_fitting`: ISO 1127 DN series for OD values
5. `pipe_flange`: ISO 7005 PN-class bolt patterns

---

*Code references:*
- QA templates + iso_tags: `scripts/data_generation/cad_synth/pipeline/qa_generator.py`
- ISO 54 module sampling: `families/spur_gear.py:114`, `families/helical_gear.py:32`, `families/bevel_gear.py:59`
- Compliance score: `bench/metrics/__init__.py:iso53_compliance()`
