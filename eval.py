"""MechEval — CAD generation benchmark.

Loads dataset from HuggingFace, calls a VLM, executes generated CadQuery code,
computes IoU / Chamfer / Feature-F1, and reports aggregated metrics.

Usage:
    # GPT-4o on IID split
    python bench/eval.py --model gpt-4o --split test_iid --out results.jsonl

    # All splits, 1 sample per family
    python bench/eval.py --model gpt-4o --split all --per-family 1 --out results.jsonl

    # Local Cadrille checkpoint
    python bench/eval.py --model local:./checkpoints/cadrille-sft --split all --out results.jsonl

    # Resume interrupted run
    python bench/eval.py --model gpt-4o --split test_iid --resume --out results.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

LD = os.environ.get("LD_LIBRARY_PATH", "/workspace/.local/lib")

from bench.dataloader import load_hf, load_done_stems, stratified_sample
from bench.metrics import compute_iou, compute_chamfer, extract_features, feature_f1
from bench.models import call_vlm

# ── CadQuery execution ────────────────────────────────────────────────────────

_PREAMBLE = """
import cadquery as cq
try:
    import OCP.TopoDS as _td
    if not hasattr(_td.TopoDS_Shape, 'HashCode'):
        _td.TopoDS_Shape.HashCode = lambda self, upper: self.__hash__() % upper
except Exception:
    pass
show_object = lambda *a, **kw: None
"""

_SUFFIX = """
import sys as _sys
try:
    cq.exporters.export(result, _sys.argv[1])
except Exception as _e:
    raise RuntimeError(f"export failed: {_e}")
"""


def _clean(code: str) -> str:
    return "\n".join(
        l for l in code.splitlines()
        if l.strip() not in ("import cadquery as cq", "import cadquery")
    )


def exec_cq(code: str, timeout: int = 60) -> tuple[str | None, str | None]:
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
        out = f.name
    script = _PREAMBLE + _clean(code) + _SUFFIX
    env = {**os.environ, "LD_LIBRARY_PATH": LD}
    try:
        r = subprocess.run(
            [sys.executable, "-c", script, out],
            env=env, timeout=timeout, capture_output=True,
            cwd=tempfile.gettempdir(),
        )
        if r.returncode != 0:
            return None, r.stderr.decode(errors="replace")[-500:]
        if not Path(out).exists() or Path(out).stat().st_size < 100:
            return None, "step missing or empty"
        return out, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


# ── Per-sample eval ───────────────────────────────────────────────────────────

def eval_sample(row: dict, model: str, api_key: str | None) -> dict:
    gt_features = json.loads(row["feature_tags"]) if isinstance(row["feature_tags"], str) else row["feature_tags"]
    res = {
        "stem": row["stem"], "family": row["family"],
        "difficulty": row["difficulty"], "base_plane": row["base_plane"],
        "split": row["split"], "feature_count": row["feature_count"],
        "gt_features": gt_features, "model": model,
        "exec_ok": 0, "iou": 0.0, "chamfer": float("inf"),
        "feature_f1": 0.0, "detail_score": 0.0,
        "gen_features": {}, "error": None,
    }

    t0 = time.time()
    gen_code, err = call_vlm(model, row["composite_png"], api_key)
    res["vlm_latency_s"] = round(time.time() - t0, 2)
    if not gen_code:
        res["error"] = f"vlm_fail: {err}"
        return res
    res["gen_code"] = gen_code

    gen_step, exec_err = exec_cq(gen_code)
    gen_feats = extract_features(gen_code)
    res["gen_features"] = gen_feats
    res["feature_f1"] = round(feature_f1(gen_feats, gt_features), 4)

    if not gen_step:
        res["error"] = f"exec_fail: {exec_err}"
        res["detail_score"] = round(0.6 * res["feature_f1"], 4)
        return res

    res["exec_ok"] = 1

    gt_step, gt_err = exec_cq(row["gt_code"])
    if not gt_step:
        res["error"] = f"gt_exec_fail: {gt_err}"
        res["detail_score"] = round(0.6 * res["feature_f1"], 4)
        Path(gen_step).unlink(missing_ok=True)
        return res

    iou, iou_err = compute_iou(gt_step, gen_step)
    cd,  cd_err  = compute_chamfer(gt_step, gen_step)
    res["iou"]     = round(iou, 4)
    res["chamfer"] = round(cd, 6) if cd != float("inf") else float("inf")
    if iou_err: res["iou_error"] = iou_err
    if cd_err:  res["cd_error"]  = cd_err
    res["detail_score"] = round(0.4 * iou + 0.6 * res["feature_f1"], 4)

    Path(gen_step).unlink(missing_ok=True)
    Path(gt_step).unlink(missing_ok=True)
    return res


# ── Report ────────────────────────────────────────────────────────────────────

def report(results: list[dict]) -> None:
    total = len(results)
    if not total:
        print("No results.")
        return
    exec_ok = [r for r in results if r["exec_ok"]]
    ious    = [r["iou"] for r in exec_ok]
    cds     = [r["chamfer"] for r in exec_ok if r.get("chamfer", float("inf")) != float("inf")]
    f1s     = [r["feature_f1"] for r in results]
    details = [r["detail_score"] for r in results]

    print(f"\n{'='*60}")
    print(f"Model: {results[0].get('model','?')}  |  N={total}")
    print(f"{'='*60}")
    print(f"Exec%:        {len(exec_ok)/total*100:.1f}%  ({len(exec_ok)}/{total})")
    print(f"IoU (exec'd): {sum(ious)/len(ious):.3f}  (n={len(ious)})" if ious else "IoU: —")
    print(f"CD  (exec'd): {sum(cds)/len(cds):.4f}  (n={len(cds)})  [lower=better]" if cds else "CD: —")
    print(f"Feat-F1:      {sum(f1s)/len(f1s):.3f}")
    print(f"Detail↑:      {sum(details)/len(details):.3f}")

    by_split = defaultdict(list)
    for r in results:
        by_split[r["split"]].append(r)
    print(f"\n{'Split':<22} {'N':>5} {'Exec%':>7} {'IoU':>6} {'F1':>6} {'Detail':>7}")
    print("-" * 57)
    for sp, rs in sorted(by_split.items()):
        ex  = [x for x in rs if x["exec_ok"]]
        iou = sum(x["iou"] for x in ex) / len(ex) if ex else 0.0
        f1  = sum(x["feature_f1"] for x in rs) / len(rs)
        det = sum(x["detail_score"] for x in rs) / len(rs)
        print(f"{sp:<22} {len(rs):>5} {len(ex)/len(rs)*100:>6.1f}% {iou:>6.3f} {f1:>6.3f} {det:>7.3f}")

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
    print("=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="MechEval — CAD generation benchmark")
    ap.add_argument("--model",      default="gpt-4o")
    ap.add_argument("--split",      default="test_iid",
                    choices=["test_iid", "test_ood_family", "test_ood_plane", "all"])
    ap.add_argument("--repo",       default="Hula0401/cad_synth_bench")
    ap.add_argument("--limit",      type=int, default=0, help="0=all")
    ap.add_argument("--per-family", type=int, default=0, help="stratified N per family")
    ap.add_argument("--out",        default="results.jsonl")
    ap.add_argument("--api-key",    default=None)
    ap.add_argument("--resume",     action="store_true")
    args = ap.parse_args()

    token   = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY1")

    print(f"Loading {args.repo} ...")
    rows = load_hf(args.repo, args.split, token=token)

    if args.per_family:
        rows = stratified_sample(rows, args.per_family)
    elif args.limit:
        rows = rows[:args.limit]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.resume:
        done = load_done_stems(out_path)
        rows = [r for r in rows if r["stem"] not in done]
        print(f"Resuming: {len(done)} done, {len(rows)} remaining")

    print(f"Evaluating {len(rows)} samples  model={args.model}  split={args.split}")

    results = []
    with open(out_path, "a") as f_out:
        for i, row in enumerate(rows):
            print(f"[{i+1}/{len(rows)}] {row['stem']} ...", end=" ", flush=True)
            res = eval_sample(row, args.model, api_key)
            results.append(res)
            f_out.write(json.dumps(res) + "\n")
            f_out.flush()
            status = f"iou={res['iou']:.3f} f1={res['feature_f1']:.3f} exec={res['exec_ok']}"
            if res.get("error"):
                status += f"  ERR={res['error'][:60]}"
            print(status)

    if args.resume and out_path.exists():
        with open(out_path) as f:
            results = [json.loads(l) for l in f if l.strip()]
    report(results)


if __name__ == "__main__":
    main()
