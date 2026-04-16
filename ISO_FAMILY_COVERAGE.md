# ISO Coverage by Family

*74 existing families + new family candidates*

**Legend:**
- ✅ Already in `qa_generator.py` + enforced in sampler
- ⚙️ Tagged only (iso_tags) — geometry approx correct, not strictly constrained
- 🔲 Applicable standard identified, not yet implemented
- ➕ New family candidate (no current family)
- — No applicable ISO standard

---

## Coverage Summary

| Category | Families | With ISO | Coverage |
|----------|---------|---------|---------|
| Gears | 4 | 4 | 100% ✅ |
| Fasteners | 3 | 3 | 100% ✅ |
| Pipes & Flanges | 4 | 4 | 100% ✅ |
| Shafts | 2 | 2 | 100% ✅ |
| Springs | 1 | 1 | 100% ✅ |
| Structural profiles | 3 | 0 | 0% 🔲 |
| Bearings & seals | 2 | 0 | 0% 🔲 |
| Machine elements | 8 | 0 | 0% 🔲 |
| Sheet metal / plates | 6 | 2 | 33% ⚙️ |
| Rotating machinery | 4 | 0 | 0% 🔲 |
| Enclosures / panels | 6 | 0 | 0% — |
| Misc mechanical | 10 | 0 | 0% — |
| Furniture / organic | 4 | 0 | 0% — |
| **Total** | **57 mapped** | **16** | **28%** |

---

## All 74 Families

### Gears ✅

| Family | ISO Standards | Key params constrained | Status |
|--------|--------------|----------------------|--------|
| `spur_gear` | ISO 53 (tooth profile), ISO 54 (modules), ISO 1328 (accuracy) | `module` from R20/R40 series; `da=m(z+2)`, `df=m(z-2.5)` | ✅ |
| `helical_gear` | ISO 53, ISO 54, ISO 1328 | Same + helix angle | ✅ |
| `bevel_gear` | ISO 23509 (geometry), ISO 54, ISO 1328 | `module` from R20/R40 | ✅ |
| `worm_screw` | ISO 1122 (terminology), ISO 54 | `module`, `n_starts`, lead angle | ✅ |

---

### Fasteners ✅

| Family | ISO Standards | Key params constrained | Status |
|--------|--------------|----------------------|--------|
| `bolt` | ISO 261 (metric threads), ISO 4014 (hex bolts) | `outer_diameter`, `thread_pitch`, `length` | ✅ QA; 🔲 pitch table |
| `hex_nut` | ISO 4032 (style 1 nuts) | `inner_diameter`, `across_flats ≈ 1.7d` | ✅ QA; 🔲 exact table |
| `hex_standoff` | ISO 4766 (set screws/standoffs) | `outer_diameter`, `length` | ✅ QA |
| `standoff` | ISO 4766 | Same as hex_standoff | 🔲 |
| `threaded_adapter` | ISO 261 | inner/outer thread diameters | 🔲 |

---

### Pipes & Flanges ✅

| Family | ISO Standards | Key params constrained | Status |
|--------|--------------|----------------------|--------|
| `pipe_flange` | ISO 7005-1 (steel flanges), ISO 1127 | `flange_od`, `bolt_pcd`, `n_bolts`, PN class | ✅ QA |
| `round_flange` | ISO 7005-1 | Same | ✅ QA |
| `t_pipe_fitting` | ISO 1127 (tube dimensions) | `outer_diameter`, `wall_thickness` | ✅ QA |
| `pipe_elbow` | ISO 1127, ISO 5252 (pipe bends) | `outer_radius`, `wall_thickness`, `bend_radius` | 🔲 |
| `hollow_tube` | ISO 1127 (round) / EN 10219 (rect) | `outer_width`, `wall_thickness` | 🔲 |
| `nozzle` | ISO 5167-3 (nozzles for flow measurement) | `inlet_radius`, `outlet_radius`, `length`, `beta = outlet/inlet` | 🔲 |

---

### Shafts & Fits ✅

| Family | ISO Standards | Key params constrained | Status |
|--------|--------------|----------------------|--------|
| `stepped_shaft` | ISO 286-1 (tolerances), ISO 286-2 (tables) | diameter steps, IT grade from difficulty | ✅ QA |
| `shaft_collar` | ISO 286-1 | `bore_diameter`, `outer_diameter` | ✅ QA |
| `lathe_turned_part` | ISO 286-1, ISO 1302 (surface texture) | `d1`, `d2`, groove dims | 🔲 |
| `tapered_boss` | ISO 296 (Morse tapers), ISO 286 | `base_diameter`, `top_diameter`, taper ratio | 🔲 |

---

### Springs ✅

| Family | ISO Standards | Key params constrained | Status |
|--------|--------------|----------------------|--------|
| `coil_spring` | ISO 2162-1 (vocabulary), ISO 26909 | `n_active_coils`, spring index `C = D/d ∈ [4,20]` | ✅ QA |

---

### Structural Profiles 🔲 (0/3 covered — easy wins)

| Family | Applicable ISO | Key params to constrain | Priority |
|--------|---------------|------------------------|---------|
| `i_beam` | **ISO 657-1** (hot-rolled I-sections), EN 10034 | Standard IPE series: 80/100/120/.../600; `h`, `b`, `tw`, `tf` from table | ⭐ High |
| `u_channel` | **ISO 657-2** (hot-rolled channels / UPE/UPN) | Standard UPN series; `h`, `b`, `tw`, `tf` from table | ⭐ High |
| `t_slot_rail` | **ISO 299** (T-slots for machine tools), DIN 650 | Slot sizes: 8/10/12/14/16/18/20/22/25 mm series | ⭐ High |

---

### Bearings & Seals 🔲 (0/2 covered)

| Family | Applicable ISO | Key params to constrain | Priority |
|--------|---------------|------------------------|---------|
| `bearing_retainer_cap` | **ISO 281** (dynamic load ratings), ISO 15 (radial ball bearings — bore series) | `bore_diameter` from ISO 15 bore code table: 10/12/15/17/20/25/30/35/40/45/50mm | ⭐ High |
| `spacer_ring` | **ISO 286-1**, ISO 15 (bearing bore series) | `inner_diameter` matches bearing bore, `outer_diameter`, IT grade | Medium |

---

### Machine Elements 🔲 (0/8 covered)

| Family | Applicable ISO | Key params to constrain | Priority |
|--------|---------------|------------------------|---------|
| `hinge` | **ISO 3669** (butt hinges), DIN 3417 | `leaf_length`, `leaf_width`, `n_knuckles`, `pin_diameter` | Medium |
| `pulley` | **ISO 22** (V-belt pulleys), ISO 4183 | groove angle 34°/36°/38°, groove depth, pitch diameter series | ⭐ High |
| `cam` | — (no ISO for generic cams) | — | — |
| `clevis` | **ISO 8140** (clevis joints for cylinders), ISO 6020 | `arm_thickness`, `gap_width`, `pin_diameter` | Medium |
| `connecting_rod` | — (SAE J120, not ISO) | — | — |
| `dovetail_slide` | **ISO 2806** (NC axis geometry), DIN 650 | Angle: 45°/55°/60° standard values | Low |
| `piston` | **ISO 6621-2** (piston rings — grooves) | `groove_width`, `groove_depth` from ring size table | Medium |
| `handwheel` | **ISO 4184** (handwheels), DIN 950 | `outer_diameter` from standard series: 80/100/125/160/200/250/315/400mm | Medium |
| `ratchet_sector` | — | — | — |
| `manifold_block` | **ISO 4401** (hydraulic valve mounting surfaces) | `channel_diameter` from NG (nominal size) series: 6/10/16/25/32 | Low |

---

### Rotating Machinery 🔲 (0/4 covered)

| Family | Applicable ISO | Key params to constrain | Priority |
|--------|---------------|------------------------|---------|
| `impeller` | — (ISO/TR 17108 for fans, not rigid geometry) | `n_blades` (integer QA) | — |
| `propeller` | — (ITTC marine, not ISO) | `n_blades` (integer QA) | — |
| `fan_shroud` | — | `n_vanes` (integer QA) | — |
| `motor_end_cap` | **IEC 60072-1** (frame numbers — shaft & flange dims) | `bolt_pcd`, `n_bolts`, `shaft_diameter` from frame table | Medium |

---

### Sheet Metal & Plates ⚙️ (2/6 covered)

| Family | Applicable ISO | Key params to constrain | Status |
|--------|---------------|------------------------|--------|
| `mounting_plate` | ISO 2768-1 (general tolerances) | `length`, `width`, `thickness` — class m/f/c | ⚙️ tagged |
| `slotted_plate` | ISO 2768-1 | Same | ⚙️ tagged |
| `waffle_plate` | ISO 2768-1 | `n_ribs_x`, `n_ribs_y` (integer QA) | ⚙️ |
| `rib_plate` | ISO 2768-1 | `rib_count` (integer QA) | 🔲 |
| `sheet_metal_tray` | **ISO 2768-2** (straightness/flatness) | `sheet_thickness` from standard gauge table | 🔲 |
| `heat_sink` | — (JEDEC, not ISO) | `n_fins` (integer QA) | — |

---

### Enclosures & Panels — (0/6, limited ISO applicability)

| Family | Applicable ISO | Notes |
|--------|---------------|-------|
| `enclosure` | IEC 60529 (IP rating) | IP class not geometry-derivable from image |
| `vented_panel` | ISO 4783 (perforated plates) | Hole diameter / pitch ratio = useful QA |
| `mesh_panel` | ISO 4783 | Hole count rows × cols (integer QA) |
| `cable_routing_panel` | — | |
| `connector_faceplate` | IEC 61076 (connectors) | Not rigid geometry |
| `pcb_standoff_plate` | IEC 60194 (PCB design) | Post count (integer QA) |

---

### Misc Mechanical — (0/10)

| Family | Applicable ISO | Notes |
|--------|---------------|-------|
| `flat_link` | ISO 10823 (chain links) | `cc_distance`, `bore_radius` → pitch ratio |
| `dog_bone` | — | |
| `cruciform` | — | |
| `star_blank` | — | `n_points` (integer QA) |
| `locator_block` | — | |
| `gusseted_bracket` | — | |
| `l_bracket`, `z_bracket`, `mounting_angle` | ISO 2768-1 | General tolerance tagging |
| `rect_frame` | — | |
| `snap_clip` | — | |

---

### Furniture / Organic — (0/4)

| Family | Notes |
|--------|-------|
| `chair`, `table` | No mechanical ISO |
| `capsule`, `dome_cap`, `ball_knob`, `knob`, `bucket`, `torus_link`, `bellows` | No applicable ISO |

---

## New Family Candidates (Easy ISO wins)

These families don't exist yet but map cleanly to a single ISO standard with few parameters:

| Family | ISO | Key params | Complexity | Value |
|--------|-----|-----------|-----------|-------|
| **`circlip`** (retaining ring) | ISO 464, DIN 471/472 | shaft_d → ring OD/ID/thickness from table; shaft vs bore variant | Low | ⭐⭐⭐ |
| **`woodruff_key`** | ISO 3912 | shaft_d → key width × height × radius from table | Low | ⭐⭐⭐ |
| **`flat_washer`** | ISO 7089/7090 | nominal_d → OD × thickness from table; plain/spring | Low | ⭐⭐ |
| **`dowel_pin`** | ISO 8734 | `diameter` from series (1/1.5/2/2.5/3/4/5/6/8/10/12mm), `length` | Low | ⭐⭐⭐ |
| **`sprocket`** | ISO 606 (roller chain) | `n_teeth`, `pitch` (6.35/8/9.525/12.7/15.875/19.05/25.4mm), `bore_d` | Medium | ⭐⭐⭐ |
| **`v_belt_pulley`** | ISO 4183, ISO 22 | `pitch_diameter`, groove angle (34°/36°/38°), `n_grooves` | Medium | ⭐⭐⭐ |
| **`o_ring_groove`** | ISO 3601-2 | `shaft_d` → groove OD/width/depth from table | Low | ⭐⭐ |
| **`pin_joint`** | ISO 8135 (knuckle joints) | `pin_d`, `fork_width`, `eye_width` | Low | ⭐⭐ |

**Top 3 to build first:**
1. `sprocket` — visually distinctive, ISO 606 fully specifies geometry from `n_teeth` + `pitch`
2. `circlip` — ultra-simple geometry, pure ISO table lookup
3. `dowel_pin` — simplest possible ISO family, good for QA baseline

---

## Action Plan

### Immediate (QA-generator only, no geometry change needed)
Add to `qa_generator.py`:
- `vented_panel` / `mesh_panel`: hole count rows/cols (integer QA)
- `star_blank`: n_points (integer QA)
- `rib_plate`: rib count (integer QA)
- `enclosure`: n_mount_holes, n_vent_holes (integer QA)
- `motor_end_cap`: n_bolts (integer), bolt_pcd/OD ratio
- `flat_link` / `dog_bone`: center-to-center / boss ratio
- `hinge`: n_knuckles (integer)
- `handwheel`: n_spokes (integer), OD mm

### Short term (sampler constraint only)
- `i_beam`: snap to IPE series
- `u_channel`: snap to UPN series
- `t_slot_rail`: snap to 8/10/12/14/16/18/20/25mm slot series
- `bearing_retainer_cap`: snap bore to ISO 15 bearing series
- `handwheel`: snap OD to DIN 950 series
- `pulley`: constrain groove angle to 34°/36°/38°

### Medium term (new families)
- `sprocket` (ISO 606)
- `circlip` / `woodruff_key` (ISO 3912 / DIN 471)
- `dowel_pin` (ISO 8734)
