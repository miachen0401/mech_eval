"""Geometry and feature metrics."""
from __future__ import annotations

import re
import math

LD = __import__("os").environ.get("LD_LIBRARY_PATH", "/workspace/.local/lib")

# ── Feature extraction ────────────────────────────────────────────────────────

_FEATURE_PATTERNS = {
    "has_hole":    re.compile(r"\b(hole|cutThruAll|cboreHole|cskHole)\s*\(", re.I),
    "has_fillet":  re.compile(r"\bfillet\s*\(", re.I),
    "has_chamfer": re.compile(r"\bchamfer\s*\(", re.I),
}


def extract_features(code: str) -> dict[str, bool]:
    return {k: bool(pat.search(code)) for k, pat in _FEATURE_PATTERNS.items()}


def feature_f1(pred: dict, gt: dict) -> float:
    keys = list(gt.keys())
    if not keys:
        return 1.0
    tp = sum(1 for k in keys if pred.get(k) and gt.get(k))
    fp = sum(1 for k in keys if pred.get(k) and not gt.get(k))
    fn = sum(1 for k in keys if not pred.get(k) and gt.get(k))
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0


# ── Geometry normalization ────────────────────────────────────────────────────

def _load_normalized_mesh(step_path: str):
    """Load STEP → tessellate → normalize bbox center→[0.5,0.5,0.5], longest→[0,1]³."""
    import numpy as np
    import trimesh
    import cadquery as cq

    shape = cq.importers.importStep(step_path)
    solid = shape.val()
    if solid is None:
        solids = shape.solids().vals()
        if not solids:
            raise ValueError(f"no solids in {step_path}")
        solid = solids[0]

    verts_raw, tris_raw = solid.tessellate(0.05)
    verts = __import__("numpy").array([[v.x, v.y, v.z] for v in verts_raw], dtype=float)
    tris  = __import__("numpy").array([[t[0], t[1], t[2]] for t in tris_raw], dtype=__import__("numpy").int64)

    if len(verts) == 0 or len(tris) == 0:
        raise ValueError(f"empty tessellation for {step_path}")

    lo, hi  = verts.min(axis=0), verts.max(axis=0)
    center  = (lo + hi) / 2.0
    longest = (hi - lo).max()
    if longest < 1e-9:
        raise ValueError("degenerate geometry")
    verts = (verts - center) / longest + 0.5

    return trimesh.Trimesh(vertices=verts, faces=tris, process=False)


def compute_iou(gt_step: str, gen_step: str) -> tuple[float, str | None]:
    try:
        import numpy as np
        gt_mesh  = _load_normalized_mesh(gt_step)
        gen_mesh = _load_normalized_mesh(gen_step)

        res = 64
        gt_vox  = gt_mesh.voxelized(pitch=1.0/res).fill()
        gen_vox = gen_mesh.voxelized(pitch=1.0/res).fill()

        def _dense(vox, size=res+4):
            m = vox.matrix.astype(bool)
            out = np.zeros((size, size, size), dtype=bool)
            s = np.array(m.shape)
            o = ((size - s) // 2).clip(0)
            e = (o + s).clip(max=size)
            out[o[0]:e[0], o[1]:e[1], o[2]:e[2]] = m[:e[0]-o[0], :e[1]-o[1], :e[2]-o[2]]
            return out

        gt_d, gen_d = _dense(gt_vox), _dense(gen_vox)
        inter = __import__("numpy").logical_and(gt_d, gen_d).sum()
        union = __import__("numpy").logical_or(gt_d, gen_d).sum()
        return (float(inter / union), None) if union else (0.0, "union empty")
    except Exception as e:
        return 0.0, str(e)[:100]


# ── QA scoring ────────────────────────────────────────────────────────────────

def qa_score_single(pred: float, qa: dict) -> float:
    """Score one QA answer against ground truth.

    All types use ratio accuracy: min(pred, gt) / max(pred, gt)
    - pred=24, gt=26 → 24/26 = 0.923
    - pred=26, gt=24 → 24/26 = 0.923  (symmetric)
    - pred=26, gt=26 → 1.000  (exact)
    Returns 0.0 if either value is non-positive.
    """
    gt   = qa["answer"]
    pred = float(pred)
    if gt <= 0 or pred <= 0:
        return 0.0
    return round(min(pred, gt) / max(pred, gt), 4)


def qa_score(pred_answers: list[float], qa_pairs: list[dict]) -> float:
    """Mean score across all QA pairs. Returns 0.0 if no pairs."""
    if not qa_pairs:
        return 0.0
    scores = [
        qa_score_single(pred, qa)
        for pred, qa in zip(pred_answers, qa_pairs)
    ]
    return round(sum(scores) / len(scores), 4)


# ── ISO compliance metrics ─────────────────────────────────────────────────────

def iso53_compliance(m_pred: float, z_pred: float,
                     da_pred: float, df_pred: float, d_pred: float) -> float:
    """ISO 53 spur gear compliance score [0,1].

    Checks three diameter relationships:
      tip  diameter da = m*(z+2)
      root diameter df = m*(z-2.5)
      pitch diameter d  = m*z
    """
    z = round(z_pred)
    if m_pred <= 0 or z < 5:
        return 0.0
    da_gt = m_pred * (z + 2)
    df_gt = m_pred * (z - 2.5)
    d_gt  = m_pred * z
    e1 = abs(da_pred - da_gt) / da_gt
    e2 = abs(df_pred - df_gt) / max(df_gt, 1e-6)
    e3 = abs(d_pred  - d_gt)  / d_gt
    return max(0.0, 1.0 - (e1 + e2 + e3) / 3)


def compute_chamfer(gt_step: str, gen_step: str, n_points: int = 2048) -> tuple[float, str | None]:
    try:
        import numpy as np
        import trimesh
        from scipy.spatial import cKDTree

        gt_mesh  = _load_normalized_mesh(gt_step)
        gen_mesh = _load_normalized_mesh(gen_step)
        gt_pts   = trimesh.sample.sample_surface(gt_mesh,  n_points)[0]
        gen_pts  = trimesh.sample.sample_surface(gen_mesh, n_points)[0]
        d1 = cKDTree(gen_pts).query(gt_pts)[0]
        d2 = cKDTree(gt_pts).query(gen_pts)[0]
        return float(np.mean(d1**2) + np.mean(d2**2)), None
    except Exception as e:
        return float("inf"), str(e)[:100]
