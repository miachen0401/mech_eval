"""Feature extraction reliability test.

Samples N items per family from bench_1k_apr14, runs two extraction methods
against GT feature_tags, and reports per-method / per-feature / per-family
precision, recall, F1 and failure modes.

Methods compared:
  ast   - regex on GT CadQuery code  (fast, what run_eval currently uses)
  step  - OCC surface analysis on GT STEP file  (geometry-based)

Usage:
    LD_LIBRARY_PATH=/workspace/.local/lib uv run python3 \
        bench/vlm_bench/feature_reliability_test.py \
        [--run bench_1k_apr14] [--per-family 3] [--out /tmp/feat_rel.jsonl]
"""

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "data_generation" / "generated_data" / "fusion360"

FEATURES = ["has_hole", "has_fillet", "has_chamfer"]

# ── AST regex (same as run_eval.py) ──────────────────────────────────────────

_AST_PATTERNS = {
    "has_hole":    re.compile(r"\b(hole|cutThruAll|cboreHole|cskHole)\s*\(", re.I),
    "has_fillet":  re.compile(r"\bfillet\s*\(", re.I),
    "has_chamfer": re.compile(r"\bchamfer\s*\(", re.I),
    "has_slot":    re.compile(r"\bslot2D\s*\(", re.I),
}


def extract_ast(code: str) -> dict[str, bool]:
    return {k: bool(pat.search(code)) for k, pat in _AST_PATTERNS.items()}


# ── STEP geometry extraction ─────────────────────────────────────────────────

_STEP_EXTRACT_SCRIPT = r"""
# Light STEP feature extraction.
#
# has_hole    : cylindrical faces with REVERSED orientation (inner wall) + r > 0.5mm
# has_fillet  : cylindrical FORWARD faces with r < FILLET_MAX_ABS (3 mm absolute)
# has_chamfer : planar faces whose normal is NOT axis-aligned + area < area_thresh
# has_slot    : None (skip; AST handles this)
# n_solids    : number of disconnected solid bodies (for cc_match)
# surface_area: total surface area in mm² (for sa_error; normalize externally)
#
# Key simplification vs v1: OCC Face.Orientation() replaces BRepLProp normal
# analysis.  REVERSED = natural normal is flipped = inner surface of a bore.

import sys, math, json

try:
    import OCP.OCP.TopoDS as _td
    if not hasattr(_td.TopoDS_Shape, 'HashCode'):
        _td.TopoDS_Shape.HashCode = lambda self, upper: self.__hash__() % upper
except Exception:
    pass

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.TopAbs import TopAbs_REVERSED
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID

FILLET_MAX_ABS = 3.0   # mm; convex cylinder r < this = fillet candidate
MIN_BORE_R     = 0.5   # mm; ignore micro-cylinders (tessellation artefacts)

def _is_axis_aligned(d, tol=0.05):
    for i in range(3):
        v = [0.0]*3; v[i] = 1.0
        if abs(d.X()*v[0] + d.Y()*v[1] + d.Z()*v[2]) > 1.0 - tol:
            return True
    return False

step_path = sys.argv[1]
shape = cq.importers.importStep(step_path)
bb = shape.val().BoundingBox()
bbox_diag = math.sqrt(bb.xlen**2 + bb.ylen**2 + bb.zlen**2)
bbox_area  = bb.xlen * bb.ylen + bb.ylen * bb.zlen + bb.zlen * bb.xlen
chamfer_area_thresh = bbox_area * 0.02   # oblique face < 2% of bbox surface area

cyl_inner_r = []   # inner (reversed) cylinders: hole candidates
cyl_fillet_r = []  # outer small cylinders: fillet candidates
oblique_areas = [] # oblique planar faces: chamfer candidates
total_sa = 0.0
n_faces = 0

for face in shape.faces().objects:
    n_faces += 1
    fw = face.wrapped
    ad = BRepAdaptor_Surface(fw)
    t  = ad.GetType()

    # Surface area contribution
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(fw, props)
    face_area = props.Mass()
    total_sa += face_area

    is_reversed = (fw.Orientation() == TopAbs_REVERSED)

    if t == GeomAbs_Cylinder:
        r = ad.Cylinder().Radius()
        if is_reversed:
            # Inner wall of a bore / hollow
            if r >= MIN_BORE_R:
                cyl_inner_r.append(r)
        else:
            # Outer convex cylinder; small radius → fillet blend
            if r <= FILLET_MAX_ABS:
                cyl_fillet_r.append(r)

    elif t == GeomAbs_Plane:
        n = ad.Plane().Axis().Direction()
        if not _is_axis_aligned(n) and face_area < chamfer_area_thresh:
            oblique_areas.append(face_area)

# Count distinct solid bodies (connected components at solid level)
explorer = TopExp_Explorer(shape.val().wrapped, TopAbs_SOLID)
n_solids = 0
while explorer.More():
    n_solids += 1
    explorer.Next()
n_solids = max(n_solids, 1)

result = {
    "has_hole":    len(cyl_inner_r) > 0,
    "has_fillet":  len(cyl_fillet_r) >= 2,  # require ≥2 fillet faces (1 can be artefact)
    "has_chamfer": len(oblique_areas) >= 2,  # require ≥2 oblique planes
    "has_slot":    None,
    "n_solids":    n_solids,
    "surface_area_mm2": round(total_sa, 3),
    "diag": {
        "bbox_diag": round(bbox_diag, 2),
        "n_faces":   n_faces,
        "cyl_inner_r":   sorted(round(r,2) for r in cyl_inner_r),
        "cyl_fillet_r":  sorted(round(r,2) for r in cyl_fillet_r),
        "n_oblique":     len(oblique_areas),
    }
}
print(json.dumps(result))
"""


def extract_step(step_path: str) -> tuple[dict[str, bool], dict]:
    """Extract features + cc/sa from STEP via subprocess."""
    import subprocess
    import os

    LD = os.environ.get("LD_LIBRARY_PATH", "/workspace/.local/lib")
    r = subprocess.run(
        [sys.executable, "-c", _STEP_EXTRACT_SCRIPT, step_path],
        capture_output=True, timeout=30,
        env={**os.environ, "LD_LIBRARY_PATH": LD},
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[-300:])
    data = json.loads(r.stdout.decode().strip())
    diag = data.pop("diag", {})
    return data, diag


# ── CC match + surface area error ────────────────────────────────────────────

def cc_match(gt_data: dict, gen_data: dict) -> float:
    """1.0 if same number of solid bodies, else 0.0."""
    return 1.0 if gt_data.get("n_solids", 1) == gen_data.get("n_solids", 1) else 0.0


def sa_error(gt_data: dict, gen_data: dict) -> float | None:
    """Relative surface area error |SA_gen - SA_gt| / SA_gt (lower = better).

    Both areas are in raw mm² — scale-dependent. For benchmark use,
    normalize both shapes first; this function is intended for GT-vs-GT
    reliability checks where scale is shared.
    """
    sa_gt  = gt_data.get("surface_area_mm2")
    sa_gen = gen_data.get("surface_area_mm2")
    if not sa_gt or not sa_gen:
        return None
    return abs(sa_gen - sa_gt) / sa_gt


# ── Metrics ──────────────────────────────────────────────────────────────────

def compute_metrics(results: list[dict], method: str) -> dict:
    """Compute per-feature precision/recall/F1 across all samples for one method."""
    per_feat = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "skipped": 0})

    for r in results:
        gt = r["gt"]
        pred = r[f"pred_{method}"]
        for feat in FEATURES:
            gt_val = gt.get(feat, False)
            pred_val = pred.get(feat)
            if pred_val is None:
                per_feat[feat]["skipped"] += 1
                continue
            if pred_val and gt_val:
                per_feat[feat]["tp"] += 1
            elif pred_val and not gt_val:
                per_feat[feat]["fp"] += 1
            elif not pred_val and gt_val:
                per_feat[feat]["fn"] += 1
            else:
                per_feat[feat]["tn"] += 1

    out = {}
    for feat, c in per_feat.items():
        tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        acc  = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) > 0 else 0.0
        out[feat] = {
            "precision": round(prec, 3),
            "recall":    round(rec, 3),
            "f1":        round(f1, 3),
            "accuracy":  round(acc, 3),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "skipped": c["skipped"],
        }
    return out


def per_family_summary(results: list[dict], method: str) -> dict:
    """Per-family F1 for a method."""
    by_family = defaultdict(list)
    for r in results:
        by_family[r["family"]].append(r)
    out = {}
    for fam, rows in sorted(by_family.items()):
        m = compute_metrics(rows, method)
        avg_f1 = sum(v["f1"] for v in m.values()) / len(m) if m else 0.0
        n_errors = sum(1 for r in rows if r.get(f"err_{method}"))
        out[fam] = {
            "n": len(rows),
            "avg_f1": round(avg_f1, 3),
            "errors": n_errors,
            "per_feat": {f: m[f]["f1"] for f in FEATURES if f in m},
        }
    return out


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="bench_1k_apr14")
    ap.add_argument("--per-family", type=int, default=3, help="samples per family")
    ap.add_argument("--out", default="/tmp/feat_reliability.jsonl")
    ap.add_argument("--step-only", action="store_true", help="skip AST, only run STEP")
    ap.add_argument("--ast-only", action="store_true", help="skip STEP, only run AST")
    args = ap.parse_args()

    # Load all meta files for the run
    meta_files = sorted(DATA.glob(f"*/verified_{args.run}/meta.json"))
    print(f"Found {len(meta_files)} samples for run '{args.run}'")

    # Group by family, sample per-family
    by_family = defaultdict(list)
    for mf in meta_files:
        m = json.loads(mf.read_text())
        by_family[m["family"]].append(mf)

    selected = []
    for fam, files in sorted(by_family.items()):
        chosen = files[:args.per_family]
        selected.extend(chosen)
    print(f"Selected {len(selected)} samples from {len(by_family)} families "
          f"({args.per_family}/family)\n")

    results = []
    errors_ast = 0
    errors_step = 0

    for i, mf in enumerate(selected):
        m = json.loads(mf.read_text())
        run_dir = mf.parent
        family = m["family"]
        stem = m["stem"]
        gt_tags = m["feature_tags"]
        # Keep only FEATURES keys
        gt = {f: bool(gt_tags.get(f, False)) for f in FEATURES}

        code_path = run_dir / "code.py"
        step_path = run_dir / "gen.step"

        row = {
            "stem": stem,
            "family": family,
            "difficulty": m.get("difficulty", "?"),
            "gt": gt,
            "pred_ast": {},
            "pred_step": {},
            "err_ast": None,
            "err_step": None,
        }

        # AST method
        if not args.step_only:
            if code_path.exists():
                code = code_path.read_text()
                row["pred_ast"] = extract_ast(code)
            else:
                row["err_ast"] = "code.py missing"
                errors_ast += 1

        # STEP method
        if not args.ast_only:
            if step_path.exists():
                try:
                    feats, diag = extract_step(str(step_path))
                    row["pred_step"] = feats
                    row["step_diag"] = diag
                    row["n_solids_gt"]     = feats.get("n_solids", 1)
                    row["surface_area_gt"] = feats.get("surface_area_mm2")
                except Exception as e:
                    row["err_step"] = str(e)[:200]
                    errors_step += 1
            else:
                row["err_step"] = "gen.step missing"
                errors_step += 1

        results.append(row)

        # Progress
        if (i + 1) % 20 == 0 or (i + 1) == len(selected):
            print(f"  [{i+1}/{len(selected)}] ast_errs={errors_ast} step_errs={errors_step}")

    # Save raw results
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"\nRaw results → {out_path}")

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("FEATURE EXTRACTION RELIABILITY REPORT")
    print("=" * 70)

    methods = []
    if not args.step_only:
        methods.append("ast")
    if not args.ast_only:
        methods.append("step")

    # GT class distribution
    print("\n── GT Feature Distribution ─────────────────────────────────────────")
    for feat in FEATURES:
        pos = sum(1 for r in results if r["gt"].get(feat))
        print(f"  {feat:<15} {pos:3d}/{len(results)} ({100*pos/len(results):.0f}% positive)")

    # Per-method overall metrics
    for method in methods:
        print(f"\n── Method: {method.upper()} ─────────────────────────────────────────────")
        m = compute_metrics(results, method)
        errs = sum(1 for r in results if r.get(f"err_{method}"))
        print(f"  Errors/skipped: {errs}/{len(results)}")
        print(f"  {'Feature':<15} {'Prec':>6} {'Rec':>6} {'F1':>6} {'Acc':>6}  "
              f"{'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  skip")
        print(f"  {'-'*15} {'-'*6} {'-'*6} {'-'*6} {'-'*6}  "
              f"{'-'*4} {'-'*4} {'-'*4} {'-'*4}  ----")
        for feat in FEATURES:
            c = m.get(feat, {})
            if not c:
                continue
            print(f"  {feat:<15} {c['precision']:>6.3f} {c['recall']:>6.3f} "
                  f"{c['f1']:>6.3f} {c['accuracy']:>6.3f}  "
                  f"{c['tp']:>4} {c['fp']:>4} {c['fn']:>4} {c['tn']:>4}  {c['skipped']}")

    # Per-family comparison
    if len(methods) == 2:
        print("\n── Per-Family F1 Comparison (AST vs STEP) ──────────────────────────")
        fam_ast  = per_family_summary(results, "ast")
        fam_step = per_family_summary(results, "step")
        all_fams = sorted(set(fam_ast) | set(fam_step))
        print(f"  {'Family':<25} {'N':>3}  {'AST-F1':>7}  {'STEP-F1':>8}  {'Δ':>6}")
        print(f"  {'-'*25} {'-'*3}  {'-'*7}  {'-'*8}  {'-'*6}")
        for fam in all_fams:
            a = fam_ast.get(fam, {})
            s = fam_step.get(fam, {})
            af1 = a.get("avg_f1", 0.0)
            sf1 = s.get("avg_f1", 0.0)
            n   = a.get("n", s.get("n", 0))
            delta = sf1 - af1
            flag = "  <<<" if abs(delta) > 0.15 else ""
            print(f"  {fam:<25} {n:>3}  {af1:>7.3f}  {sf1:>8.3f}  {delta:>+6.3f}{flag}")

    # Failure analysis
    print("\n── Failure Cases ────────────────────────────────────────────────────")
    for method in methods:
        print(f"\n  [{method.upper()}] False Negatives (GT=True, pred=False):")
        for feat in FEATURES:
            fns = [r for r in results
                   if r["gt"].get(feat)
                   and r[f"pred_{method}"].get(feat) is False]
            if fns:
                fam_counts = defaultdict(int)
                for r in fns:
                    fam_counts[r["family"]] += 1
                top = sorted(fam_counts.items(), key=lambda x: -x[1])[:5]
                print(f"    {feat}: {len(fns)} FN  → families: "
                      + ", ".join(f"{f}×{n}" for f, n in top))

        print(f"\n  [{method.upper()}] False Positives (GT=False, pred=True):")
        for feat in FEATURES:
            fps = [r for r in results
                   if not r["gt"].get(feat)
                   and r[f"pred_{method}"].get(feat) is True]
            if fps:
                fam_counts = defaultdict(int)
                for r in fps:
                    fam_counts[r["family"]] += 1
                top = sorted(fam_counts.items(), key=lambda x: -x[1])[:5]
                print(f"    {feat}: {len(fps)} FP  → families: "
                      + ", ".join(f"{f}×{n}" for f, n in top))

    # ── AST vs STEP disagreement analysis ────────────────────────────────────
    if "ast" in methods and "step" in methods:
        print("\n── AST vs STEP Disagreement Analysis ───────────────────────────────")
        for feat in FEATURES:
            # 4 cells: both_correct, ast_only_correct, step_only_correct, both_wrong
            both_right = []   # ast=gt, step=gt
            ast_only   = []   # ast=gt, step≠gt
            step_only  = []   # step=gt, ast≠gt
            both_wrong = []   # ast≠gt, step≠gt

            for r in results:
                gt_val   = r["gt"].get(feat)
                ast_val  = r["pred_ast"].get(feat)
                step_val = r["pred_step"].get(feat)
                if ast_val is None or step_val is None:
                    continue
                ast_ok  = (ast_val == gt_val)
                step_ok = (step_val == gt_val)
                row_info = (r["family"], gt_val, ast_val, step_val)
                if ast_ok and step_ok:
                    both_right.append(row_info)
                elif ast_ok and not step_ok:
                    ast_only.append(row_info)
                elif step_ok and not ast_ok:
                    step_only.append(row_info)
                else:
                    both_wrong.append(row_info)

            n = len(both_right) + len(ast_only) + len(step_only) + len(both_wrong)
            print(f"\n  {feat}  (n={n})")
            print(f"    Both correct  : {len(both_right):3d} ({100*len(both_right)/n:.0f}%)")
            print(f"    AST only good : {len(ast_only):3d} ({100*len(ast_only)/n:.0f}%)  "
                  f"← STEP wrong here")
            print(f"    STEP only good: {len(step_only):3d} ({100*len(step_only)/n:.0f}%)  "
                  f"← AST wrong here")
            print(f"    Both wrong    : {len(both_wrong):3d} ({100*len(both_wrong)/n:.0f}%)")

            # Show families where AST fails but STEP gets it right (step_only)
            if step_only:
                from collections import Counter
                fam_gt = Counter()
                for fam, gt, ast, step in step_only:
                    fam_gt[f"{fam}(gt={gt},ast={ast},step={step})"] += 1
                # Group by family
                fam_c = Counter(fam for fam, *_ in step_only)
                top = fam_c.most_common(5)
                print(f"    STEP rescues AST → top families: "
                      + ", ".join(f"{f}×{n}" for f, n in top))

            # Show families where STEP fails but AST gets it right (ast_only)
            if ast_only:
                fam_c = Counter(fam for fam, *_ in ast_only)
                top = fam_c.most_common(5)
                print(f"    AST rescues STEP → top families: "
                      + ", ".join(f"{f}×{n}" for f, n in top))

            # Show families where both fail
            if both_wrong:
                fam_c = Counter(fam for fam, *_ in both_wrong)
                top = fam_c.most_common(5)
                # Separate FP and FN
                fn = [(f, gt, a, s) for f, gt, a, s in both_wrong if gt and not a and not s]
                fp = [(f, gt, a, s) for f, gt, a, s in both_wrong if not gt and a and s]
                print(f"    Both wrong — FN:{len(fn)} FP:{len(fp)}  "
                      + "families: " + ", ".join(f"{f}×{n}" for f, n in top))

        # Oracle: what if we take OR of AST and STEP for has_hole?
        print("\n── Oracle: AST OR STEP (union) for has_hole ────────────────────────")
        for feat in FEATURES:
            tp = fp = fn = tn = 0
            for r in results:
                gt_val   = r["gt"].get(feat)
                ast_val  = r["pred_ast"].get(feat)
                step_val = r["pred_step"].get(feat)
                if ast_val is None or step_val is None:
                    continue
                pred = ast_val or step_val   # OR
                if pred and gt_val:     tp += 1
                elif pred and not gt_val: fp += 1
                elif not pred and gt_val: fn += 1
                else:                   tn += 1
            prec = tp/(tp+fp) if (tp+fp) else 0
            rec  = tp/(tp+fn) if (tp+fn) else 0
            f1   = 2*prec*rec/(prec+rec) if (prec+rec) else 0
            print(f"  {feat:<15} OR → prec={prec:.3f} rec={rec:.3f} F1={f1:.3f}  "
                  f"(AST alone: see above, STEP alone: see above)")

        print("\n── Oracle: AST AND STEP (intersection) for high-precision ─────────")
        for feat in FEATURES:
            tp = fp = fn = tn = 0
            for r in results:
                gt_val   = r["gt"].get(feat)
                ast_val  = r["pred_ast"].get(feat)
                step_val = r["pred_step"].get(feat)
                if ast_val is None or step_val is None:
                    continue
                pred = ast_val and step_val   # AND
                if pred and gt_val:     tp += 1
                elif pred and not gt_val: fp += 1
                elif not pred and gt_val: fn += 1
                else:                   tn += 1
            prec = tp/(tp+fp) if (tp+fp) else 0
            rec  = tp/(tp+fn) if (tp+fn) else 0
            f1   = 2*prec*rec/(prec+rec) if (prec+rec) else 0
            print(f"  {feat:<15} AND → prec={prec:.3f} rec={rec:.3f} F1={f1:.3f}")

    # ── CC / SA distribution on GT (sanity check) ─────────────────────────
    if not args.ast_only:
        cc_rows = [r for r in results if r.get("n_solids_gt") is not None]
        sa_rows = [r for r in results if r.get("surface_area_gt") is not None]
        if cc_rows:
            from collections import Counter
            cc_dist = Counter(r["n_solids_gt"] for r in cc_rows)
            print("\n── GT Connected Components Distribution ────────────────────────────")
            for k, v in sorted(cc_dist.items()):
                print(f"  n_solids={k}: {v} samples ({100*v/len(cc_rows):.0f}%)")
        if sa_rows:
            import statistics
            sas = [r["surface_area_gt"] for r in sa_rows]
            print("\n── GT Surface Area Distribution (mm²) ──────────────────────────────")
            print(f"  min={min(sas):.0f}  median={statistics.median(sas):.0f}  "
                  f"max={max(sas):.0f}  mean={statistics.mean(sas):.0f}")
            # Per-family median SA (top 10 by SA)
            by_fam_sa = defaultdict(list)
            for r in sa_rows:
                by_fam_sa[r["family"]].append(r["surface_area_gt"])
            top_sa = sorted(by_fam_sa.items(),
                            key=lambda x: statistics.median(x[1]), reverse=True)[:10]
            print("  Top-10 families by median SA:")
            for fam, vals in top_sa:
                print(f"    {fam:<25} median={statistics.median(vals):.0f} mm²  "
                      f"n={len(vals)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
