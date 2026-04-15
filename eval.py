"""VLM Benchmark Evaluation Harness.

Loads bench dataset from HF (Hula0401/test_bench), calls a VLM API with
composite renders, executes the generated CadQuery code, computes IoU vs GT,
and reports per-sample + aggregated metrics.

Metrics:
  exec_ok      - code executes without error (0/1)
  iou          - volumetric IoU vs GT STEP (0-1)
  feature_f1   - F1 of detected feature tags vs GT
  detail_score - 0.4*iou + 0.6*feature_f1 (primary ranking metric)

Usage:
    # GPT-4o on test-iid split
    uv run python3 bench/vlm_bench/run_eval.py \
        --model gpt-4o \
        --split test_iid \
        --limit 50 \
        --out /workspace/tmp/eval_results/gpt4o_iid.jsonl

    # All splits
    uv run python3 bench/vlm_bench/run_eval.py \
        --model gpt-4o \
        --split all \
        --out /workspace/tmp/eval_results/gpt4o_all.jsonl

    # Local Cadrille SFT checkpoint
    uv run python3 bench/vlm_bench/run_eval.py \
        --model local:./checkpoints/cadrille-sft \
        --split test_iid \
        --out /workspace/tmp/eval_results/cadrille_sft_iid.jsonl

    # Local Cadrille RL checkpoint (HF model ID also works)
    uv run python3 bench/vlm_bench/run_eval.py \
        --model local:Hula0401/cadrille \
        --split all \
        --out /workspace/tmp/eval_results/cadrille_rl_all.jsonl
"""

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

LD = os.environ.get("LD_LIBRARY_PATH", "/workspace/.local/lib")

SYSTEM_PROMPT = """You are an expert CAD engineer. You will be shown a 2×2 composite image of an industrial part rendered from 4 viewpoints (front, right, top, isometric).

Generate executable CadQuery Python code that recreates this part. Requirements:
- Use only standard CadQuery operations (Workplane, extrude, revolve, sweep, union, cut, fillet, chamfer, hole, etc.)
- The final result must be stored in a variable named `result`
- Do NOT include show_object() or any display calls
- Do NOT include import statements — cadquery is already imported as `import cadquery as cq`
- Output ONLY the Python code, no explanation

Example structure:
result = (
    cq.Workplane("XY")
    .circle(10)
    .extrude(5)
)"""

# System prompt matching Cadrille SFT training data (sft_img2cq.jsonl)
CADRILLE_SYSTEM_PROMPT = (
    "You are a CadQuery expert. Given a 2×2 grid of normalized multi-view renders "
    "of a mechanical part (four diagonal viewpoints: [1,1,1], [-1,-1,-1], [-1,1,-1], "
    "[1,-1,1]), write CadQuery Python code that reproduces the geometry. "
    "Output ONLY Python code."
)

USER_PROMPT = "Generate CadQuery code to recreate this industrial part shown in the 4-view composite render."


# ── Feature extraction from code ────────────────────────────────────────────

_FEATURE_PATTERNS = {
    "has_hole":    re.compile(r"\b(hole|cutThruAll|cboreHole|cskHole)\s*\(", re.I),
    "has_fillet":  re.compile(r"\bfillet\s*\(", re.I),
    "has_chamfer": re.compile(r"\bchamfer\s*\(", re.I),
    "has_slot":    re.compile(r"\bslot2D\s*\(", re.I),
}


def extract_features(code: str) -> dict[str, bool]:
    return {k: bool(pat.search(code)) for k, pat in _FEATURE_PATTERNS.items()}


def feature_f1(pred: dict, gt: dict) -> float:
    """Micro F1 over feature tag keys."""
    keys = list(gt.keys())
    if not keys:
        return 1.0
    tp = sum(1 for k in keys if pred.get(k) and gt.get(k))
    fp = sum(1 for k in keys if pred.get(k) and not gt.get(k))
    fn = sum(1 for k in keys if not pred.get(k) and gt.get(k))
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0


# ── Code execution ───────────────────────────────────────────────────────────

_EXEC_PREAMBLE = """
import cadquery as cq
try:
    import OCP.TopoDS as _td
    if not hasattr(_td.TopoDS_Shape, 'HashCode'):
        _td.TopoDS_Shape.HashCode = lambda self, upper: self.__hash__() % upper
except Exception:
    pass
show_object = lambda *a, **kw: None  # suppress display calls
"""

_EXEC_SUFFIX = """
import sys as _sys
_out = _sys.argv[1]
try:
    cq.exporters.export(result, _out)
except Exception as _e:
    raise RuntimeError(f"export failed: {_e}")
"""


def _prepare_code(code: str) -> str:
    """Strip existing cadquery import (preamble adds it) and return clean code."""
    lines = []
    for line in code.splitlines():
        stripped = line.strip()
        # Skip duplicate cq import
        if stripped in ("import cadquery as cq", "import cadquery"):
            continue
        lines.append(line)
    return "\n".join(lines)


def exec_cq_code(code: str, timeout: int = 60) -> tuple[str | None, str | None]:
    """Execute CadQuery code. Returns (step_path, error)."""
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
        step_path = f.name

    script = _EXEC_PREAMBLE + _prepare_code(code) + _EXEC_SUFFIX
    env = {**os.environ, "LD_LIBRARY_PATH": LD}
    try:
        r = subprocess.run(
            [sys.executable, "-c", script, step_path],
            env=env,
            timeout=timeout,
            capture_output=True,
            cwd=str(Path(tempfile.gettempdir())),
        )
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace")[-500:]
            return None, err
        if not Path(step_path).exists() or Path(step_path).stat().st_size < 100:
            return None, "step file missing or empty"
        return step_path, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as exc:
        return None, str(exc)


# ── Geometry normalization + IoU/CD ──────────────────────────────────────────
#
# Renders are normalized (bbox center→[0.5,0.5,0.5], longest axis→[0,1]³)
# before being shown to the VLM — the model has no info about absolute scale.
# All geometry metrics must use the same normalization before comparison;
# otherwise a correct shape at the wrong scale scores IoU≈0.
#
# Normalization matches the render pipeline (bbox center→[0.5,0.5,0.5], longest→[0,1]³).

def _load_normalized_mesh(step_path: str):
    """Load STEP → tessellate → normalize bbox center→[0.5,0.5,0.5], longest→[0,1]³.

    Same transform used by the render pipeline so IoU/CD are comparable
    to what the VLM sees. No dependency on internal pipeline code.
    """
    import trimesh
    import numpy as np
    import cadquery as cq

    shape = cq.importers.importStep(step_path)
    solid = shape.val()
    if solid is None:
        solids = shape.solids().vals()
        if not solids:
            raise ValueError(f"no solids in {step_path}")
        solid = solids[0]

    verts_raw, tris_raw = solid.tessellate(0.05)
    verts = np.array([[v.x, v.y, v.z] for v in verts_raw], dtype=np.float64)
    tris  = np.array([[t[0], t[1], t[2]] for t in tris_raw], dtype=np.int64)

    if len(verts) == 0 or len(tris) == 0:
        raise ValueError(f"empty tessellation for {step_path}")

    lo, hi  = verts.min(axis=0), verts.max(axis=0)
    center  = (lo + hi) / 2.0
    longest = (hi - lo).max()
    if longest < 1e-9:
        raise ValueError("degenerate geometry")
    verts = (verts - center) / longest + 0.5   # → [0, 1]³

    return trimesh.Trimesh(vertices=verts, faces=tris, process=False)


def compute_iou(gt_step: str, gen_step: str) -> tuple[float, str | None]:
    """Voxel IoU in normalized [0,1]³ space (scale-invariant).

    Both meshes are normalized via the same transform used for rendering
    (bbox center → [0.5,0.5,0.5], longest axis → [0,1]³), so models that
    generate the right shape at the wrong absolute scale are not penalized.
    """
    try:
        import numpy as np

        gt_mesh  = _load_normalized_mesh(gt_step)
        gen_mesh = _load_normalized_mesh(gen_step)

        res = 64  # voxel grid resolution (pitch = 1/64 ≈ 0.016)
        gt_vox  = gt_mesh.voxelized(pitch=1.0/res).fill()
        gen_vox = gen_mesh.voxelized(pitch=1.0/res).fill()

        def _to_dense(vox, size=res+4):
            m = vox.matrix.astype(bool)
            out = np.zeros((size, size, size), dtype=bool)
            s = np.array(m.shape)
            o = ((size - s) // 2).clip(0)
            e = (o + s).clip(max=size)
            out[o[0]:e[0], o[1]:e[1], o[2]:e[2]] = m[:e[0]-o[0], :e[1]-o[1], :e[2]-o[2]]
            return out

        gt_d  = _to_dense(gt_vox)
        gen_d = _to_dense(gen_vox)

        inter = np.logical_and(gt_d, gen_d).sum()
        union = np.logical_or(gt_d, gen_d).sum()
        if union == 0:
            return 0.0, "union empty"
        return float(inter / union), None
    except Exception as e:
        return 0.0, str(e)[:100]


def compute_chamfer(gt_step: str, gen_step: str, n_points: int = 2048) -> tuple[float, str | None]:
    """Chamfer Distance in normalized [0,1]³ space (scale-invariant, lower=better)."""
    try:
        import trimesh
        import numpy as np
        from scipy.spatial import cKDTree

        gt_mesh  = _load_normalized_mesh(gt_step)
        gen_mesh = _load_normalized_mesh(gen_step)

        gt_pts  = trimesh.sample.sample_surface(gt_mesh,  n_points)[0]
        gen_pts = trimesh.sample.sample_surface(gen_mesh, n_points)[0]

        d_gt2gen = cKDTree(gen_pts).query(gt_pts)[0]
        d_gen2gt = cKDTree(gt_pts).query(gen_pts)[0]
        cd = float(np.mean(d_gt2gen**2) + np.mean(d_gen2gt**2))
        return cd, None
    except Exception as e:
        return float("inf"), str(e)[:100]


# ── VLM call ─────────────────────────────────────────────────────────────────

def image_to_b64(pil_img) -> str:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def call_openai(model: str, b64_img: str, api_key: str) -> tuple[str | None, str | None]:
    import openai
    client = openai.OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64_img}",
                        "detail": "high",
                    }},
                ]},
            ],
            max_tokens=2048,
            temperature=0.0,
        )
        code = resp.choices[0].message.content.strip()
        # Strip markdown fences
        code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.M)
        code = re.sub(r"```\s*$", "", code, flags=re.M)
        return code.strip(), None
    except Exception as e:
        return None, str(e)[:200]


# ── Local Qwen2-VL inference (Cadrille SFT / RL) ─────────────────────────────
#
# Model path format:  local:<hf_id_or_local_path>
#   e.g.  local:./checkpoints/cadrille-sft
#         local:Hula0401/cadrille
#
# The model is loaded once and cached as a singleton for the whole eval run.

_local_model_cache: dict = {}  # path -> {"model": ..., "processor": ...}


def _load_local_model(model_path: str) -> dict:
    if model_path in _local_model_cache:
        return _local_model_cache[model_path]

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor
    import json as _json

    print(f"\nLoading local model from: {model_path} ...", flush=True)
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Detect model type from config to pick the right class
    try:
        import os as _os
        _cfg_path = _os.path.join(model_path, "config.json") if _os.path.isdir(model_path) else None
        if _cfg_path and _os.path.exists(_cfg_path):
            with open(_cfg_path) as _f:
                _cfg = _json.load(_f)
            _model_type = _cfg.get("model_type", "")
        else:
            _model_type = ""
    except Exception:
        _model_type = ""

    if _model_type == "qwen2_5_vl":
        from transformers import Qwen2_5_VLForConditionalGeneration
        _cls = Qwen2_5_VLForConditionalGeneration
    else:
        from transformers import Qwen2VLForConditionalGeneration
        _cls = Qwen2VLForConditionalGeneration

    model = _cls.from_pretrained(model_path, torch_dtype=dtype).to(device)
    model.eval()
    processor = AutoProcessor.from_pretrained(model_path)
    _local_model_cache[model_path] = {"model": model, "processor": processor, "device": device}
    print("Model loaded.", flush=True)
    return _local_model_cache[model_path]


def call_cadrille(
    model_path: str,
    pil_img,
    max_new_tokens: int = 2048,
    temperature: float = 0.0,
) -> tuple[str | None, str | None]:
    """Run inference with a local Qwen2-VL checkpoint (Cadrille SFT or RL)."""
    try:
        import torch
        from qwen_vl_utils import process_vision_info
    except ImportError as e:
        return None, f"missing dep: {e} — run: pip install qwen-vl-utils"

    try:
        state = _load_local_model(model_path)
        model = state["model"]
        processor = state["processor"]

        messages = [
            {"role": "system", "content": CADRILLE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_img},
                    {"type": "text", "text": "Generate CadQuery code for this part."},
                ],
            },
        ]

        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(state["device"])

        gen_kwargs: dict = {"max_new_tokens": max_new_tokens}
        if temperature > 0.0:
            gen_kwargs["temperature"] = temperature
            gen_kwargs["do_sample"] = True
        else:
            gen_kwargs["do_sample"] = False

        with torch.no_grad():
            generated_ids = model.generate(**inputs, **gen_kwargs)

        trimmed = generated_ids[0][len(inputs["input_ids"][0]) :]
        code = processor.decode(trimmed, skip_special_tokens=True).strip()
        # Strip markdown fences if present
        code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.M)
        code = re.sub(r"```\s*$", "", code, flags=re.M)
        return code.strip(), None
    except Exception as e:
        return None, str(e)[:300]


def call_vlm(model: str, pil_img, api_key: str | None) -> tuple[str | None, str | None]:
    if model.startswith("local:"):
        model_path = model[len("local:"):]
        return call_cadrille(model_path, pil_img)
    b64 = image_to_b64(pil_img)
    if model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY1")
        return call_openai(model, b64, key)
    raise ValueError(f"Unsupported model: {model}. Use 'local:<path>' for local models.")


# ── Evaluation loop ──────────────────────────────────────────────────────────

def eval_sample(row: dict, model: str, api_key: str | None) -> dict:
    stem = row["stem"]
    gt_code = row["gt_code"]
    gt_features = json.loads(row["feature_tags"]) if isinstance(row["feature_tags"], str) else row["feature_tags"]
    pil_img = row["composite_png"]

    result = {
        "stem": stem,
        "family": row["family"],
        "difficulty": row["difficulty"],
        "base_plane": row["base_plane"],
        "split": row["split"],
        "feature_count": row["feature_count"],
        "gt_features": gt_features,
        "model": model,
        "exec_ok": 0,
        "iou": 0.0,
        "chamfer": float("inf"),
        "feature_f1": 0.0,
        "detail_score": 0.0,
        "gen_features": {},
        "error": None,
    }

    # 1. Generate code from VLM
    t0 = time.time()
    gen_code, err = call_vlm(model, pil_img, api_key)
    result["vlm_latency_s"] = round(time.time() - t0, 2)
    if not gen_code:
        result["error"] = f"vlm_fail: {err}"
        return result

    result["gen_code"] = gen_code

    # 2. Execute generated code → STEP
    gen_step, exec_err = exec_cq_code(gen_code)
    if not gen_step:
        result["error"] = f"exec_fail: {exec_err}"
        gen_feats = extract_features(gen_code)
        result["gen_features"] = gen_feats
        result["feature_f1"] = feature_f1(gen_feats, gt_features)
        result["detail_score"] = round(0.6 * result["feature_f1"], 4)
        return result

    result["exec_ok"] = 1

    # 3. Execute GT code → GT STEP
    gt_step, gt_err = exec_cq_code(gt_code)
    if not gt_step:
        result["error"] = f"gt_exec_fail: {gt_err}"
        # Still compute feature metrics
        gen_feats = extract_features(gen_code)
        result["gen_features"] = gen_feats
        result["feature_f1"] = feature_f1(gen_feats, gt_features)
        result["detail_score"] = round(0.6 * result["feature_f1"], 4)
        Path(gen_step).unlink(missing_ok=True)
        return result

    # 4. Geometry metrics (both in normalized [0,1]³ space)
    iou, iou_err = compute_iou(gt_step, gen_step)
    cd,  cd_err  = compute_chamfer(gt_step, gen_step)
    result["iou"]     = round(iou, 4)
    result["chamfer"] = round(cd, 6) if cd != float("inf") else float("inf")
    if iou_err:
        result["iou_error"] = iou_err
    if cd_err:
        result["cd_error"] = cd_err

    # 5. Feature F1
    gen_feats = extract_features(gen_code)
    result["gen_features"] = gen_feats
    result["feature_f1"] = round(feature_f1(gen_feats, gt_features), 4)

    # 6. Detail score
    result["detail_score"] = round(0.4 * iou + 0.6 * result["feature_f1"], 4)

    # Cleanup
    Path(gen_step).unlink(missing_ok=True)
    Path(gt_step).unlink(missing_ok=True)

    return result


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(results: list[dict]) -> None:
    total = len(results)
    if not total:
        print("No results.")
        return

    exec_ok  = [r for r in results if r["exec_ok"]]
    ious     = [r["iou"] for r in exec_ok]
    f1s      = [r["feature_f1"] for r in results]
    details  = [r["detail_score"] for r in results]

    print(f"\n{'='*60}")
    print(f"Model: {results[0].get('model','?')}  |  N={total}")
    print(f"{'='*60}")
    print(f"Exec%:        {len(exec_ok)/total*100:.1f}%  ({len(exec_ok)}/{total})")
    iou_avg = sum(ious)/len(ious) if ious else 0.0
    cds  = [r["chamfer"] for r in exec_ok if r.get("chamfer", float("inf")) != float("inf")]
    cd_avg = sum(cds)/len(cds) if cds else float("inf")
    print(f"IoU (exec'd): {iou_avg:.3f}  (n={len(ious)})")
    print(f"CD  (exec'd): {cd_avg:.4f}  (n={len(cds)})  [normalized, lower=better]")
    print(f"Feat-F1:      {sum(f1s)/len(f1s):.3f}")
    print(f"Detail↑:      {sum(details)/len(details):.3f}")

    # By split
    by_split = defaultdict(list)
    for r in results:
        by_split[r["split"]].append(r)
    print(f"\n{'Split':<20} {'N':>5} {'Exec%':>7} {'IoU':>6} {'F1':>6} {'Detail':>7}")
    print("-" * 55)
    for sp, rs in sorted(by_split.items()):
        ex  = [x for x in rs if x["exec_ok"]]
        iou = sum(x["iou"] for x in ex) / len(ex) if ex else 0.0
        f1  = sum(x["feature_f1"] for x in rs) / len(rs)
        det = sum(x["detail_score"] for x in rs) / len(rs)
        print(f"{sp:<20} {len(rs):>5} {len(ex)/len(rs)*100:>6.1f}% {iou:>6.3f} {f1:>6.3f} {det:>7.3f}")

    # By difficulty
    by_diff = defaultdict(list)
    for r in results:
        by_diff[r["difficulty"]].append(r)
    print(f"\n{'Difficulty':<12} {'N':>5} {'Exec%':>7} {'IoU':>6} {'Detail':>7}")
    print("-" * 42)
    for d in ["easy", "medium", "hard"]:
        rs = by_diff.get(d, [])
        if not rs: continue
        ex  = [x for x in rs if x["exec_ok"]]
        iou = sum(x["iou"] for x in ex) / len(ex) if ex else 0.0
        det = sum(x["detail_score"] for x in rs) / len(rs)
        print(f"{d:<12} {len(rs):>5} {len(ex)/len(rs)*100:>6.1f}% {iou:>6.3f} {det:>7.3f}")

    # Feature recall breakdown
    feat_keys = ["has_hole", "has_fillet", "has_chamfer", "has_slot"]
    gt_has  = {k: sum(1 for r in results if r["gt_features"].get(k)) for k in feat_keys}
    gen_has = {k: sum(1 for r in results if r["gen_features"].get(k)) for k in feat_keys}
    tp_cnt  = {k: sum(1 for r in results if r["gt_features"].get(k) and r["gen_features"].get(k)) for k in feat_keys}
    print(f"\n{'Feature':<14} {'GT%':>6} {'Recall':>8} {'Prec':>8}")
    print("-" * 40)
    for k in feat_keys:
        if gt_has[k] == 0:
            continue
        recall = tp_cnt[k] / gt_has[k]
        prec   = tp_cnt[k] / gen_has[k] if gen_has[k] > 0 else 0.0
        print(f"{k:<14} {gt_has[k]/total*100:>5.0f}% {recall:>8.3f} {prec:>8.3f}")
    print("=" * 60)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model",   default="gpt-4o")
    ap.add_argument("--split",   default="test_iid",
                    choices=["test_iid", "test_ood_family", "test_ood_plane", "all"])
    ap.add_argument("--limit",   type=int, default=0, help="0=all")
    ap.add_argument("--per-family", type=int, default=0,
                    help="stratified: take N samples per family (overrides --limit)")
    ap.add_argument("--out",     default="/workspace/tmp/eval_results/results.jsonl")
    ap.add_argument("--repo",    default="Hula0401/test_bench")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--resume",  action="store_true", help="skip already-done stems")
    args = ap.parse_args()

    from datasets import load_dataset
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY1")

    print(f"Loading {args.repo} ...")
    ds = load_dataset(args.repo, token=token)

    if args.split == "all":
        rows = []
        for sp in ["test_iid", "test_ood_family", "test_ood_plane"]:
            rows.extend(ds[sp])
    else:
        rows = list(ds[args.split])

    if args.per_family:
        from collections import defaultdict
        by_fam: dict[str, list] = defaultdict(list)
        for r in rows:
            by_fam[r["family"]].append(r)
        rows = [r for fam_rows in by_fam.values() for r in fam_rows[:args.per_family]]
    elif args.limit:
        rows = rows[:args.limit]

    # Resume: skip done stems
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_stems: set[str] = set()
    if args.resume and out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    done_stems.add(json.loads(line)["stem"])
                except Exception:
                    pass
        rows = [r for r in rows if r["stem"] not in done_stems]
        print(f"Resuming: {len(done_stems)} done, {len(rows)} remaining")

    print(f"Evaluating {len(rows)} samples with model={args.model} split={args.split}")

    results = []
    with open(out_path, "a") as f_out:
        for i, row in enumerate(rows):
            print(f"[{i+1}/{len(rows)}] {row['stem']} ...", end=" ", flush=True)
            res = eval_sample(row, args.model, api_key)
            results.append(res)
            f_out.write(json.dumps(res) + "\n")
            f_out.flush()
            status = f"iou={res['iou']:.3f} feat_f1={res['feature_f1']:.3f} exec={res['exec_ok']}"
            if res.get("error"):
                status += f" ERR={res['error'][:60]}"
            print(status)

    # Also report previously done results
    if args.resume and done_stems:
        with open(out_path) as f:
            all_results = [json.loads(l) for l in f if l.strip()]
        report(all_results)
    else:
        report(results)


if __name__ == "__main__":
    main()
