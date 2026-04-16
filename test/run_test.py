"""MechEval end-to-end test run.

Steps (each checks the previous completed):
  1. fetch   — stream N samples from HF → save composite.png + meta.json to disk
  2. render  — verify local images exist (no re-download needed)
  3. eval    — run gpt-4o one sample at a time from local files; optionally save gen code + render

Memory-safe: streams HF one row at a time, never holds full dataset in RAM.

Usage:
    python bench/test/run_test.py --limit 10
    python bench/test/run_test.py --limit 10 --save-code --save-render
    python bench/test/run_test.py --step fetch --limit 10
    python bench/test/run_test.py --step eval   # skip fetch if already done
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[2]
DATA  = Path(__file__).parent / "data"
RESULTS = Path(__file__).parent / "results"
LD    = os.environ.get("LD_LIBRARY_PATH", "/workspace/.local/lib")

sys.path.insert(0, str(ROOT))


# ── Step 1: Fetch ─────────────────────────────────────────────────────────────

def step_fetch(repo: str, split: str, limit: int, token: str | None,
               per_family: int = 0) -> list[Path]:
    """Download N samples from HF → save to disk. Returns list of meta.json paths.

    per_family>0: stratified — take N per family (up to limit total).
    """
    from collections import defaultdict
    from datasets import load_dataset

    DATA.mkdir(parents=True, exist_ok=True)
    label = f"limit={limit}" + (f" per_family={per_family}" if per_family else "")
    print(f"\n[1/3] FETCH  {repo}  split={split}  {label}")

    # Load only what we need to avoid filling RAM
    fetch_n = limit * 10 if per_family else limit
    ds = load_dataset(repo, split=split, token=token).select(range(min(fetch_n, 9999)))

    saved, skipped = [], 0
    fam_counts: dict[str, int] = defaultdict(int)
    for row in ds:
        if len(saved) >= limit:
            break
        if per_family and fam_counts[row["family"]] >= per_family:
            continue
        stem = row["stem"]
        sample_dir = DATA / stem
        meta_path  = sample_dir / "meta.json"

        if meta_path.exists():
            fam_counts[row["family"]] += 1
            saved.append(meta_path)
            skipped += 1
            continue

        sample_dir.mkdir(parents=True, exist_ok=True)

        # Save composite image (PIL object — don't keep in memory)
        img = row["composite_png"]
        img.save(sample_dir / "composite.png")
        img.close()
        del img

        # Save metadata (no image bytes)
        meta = {k: v for k, v in row.items() if k != "composite_png"}
        meta_path.write_text(json.dumps(meta, indent=2))

        fam_counts[row["family"]] += 1
        saved.append(meta_path)
        print(f"  saved {stem}")

    print(f"  fetch done: {len(saved)} samples ({skipped} already cached)")
    return saved


# ── Step 2: Verify renders ────────────────────────────────────────────────────

def step_render(meta_paths: list[Path]) -> list[Path]:
    """Check composite.png exists for each sample. Fail fast if missing."""
    print(f"\n[2/3] RENDER  verify {len(meta_paths)} local images")
    ok = []
    for mp in meta_paths:
        img_path = mp.parent / "composite.png"
        if not img_path.exists():
            print(f"  MISSING {mp.parent.name}/composite.png — re-run with --step fetch")
            sys.exit(1)
        ok.append(mp)
    print(f"  all {len(ok)} images present")
    return ok


# ── Step 3: Eval ──────────────────────────────────────────────────────────────

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


def _exec_cq(code: str, timeout: int = 120) -> tuple[str | None, str | None]:
    lines = [l for l in code.splitlines()
             if l.strip() not in ("import cadquery as cq", "import cadquery")]
    script = _PREAMBLE + "\n".join(lines) + _SUFFIX
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
        out = f.name
    env = {**os.environ, "LD_LIBRARY_PATH": LD}
    try:
        r = subprocess.run(
            [sys.executable, "-c", script, out],
            env=env, timeout=timeout, capture_output=True,
            cwd=tempfile.gettempdir(),
        )
        if r.returncode != 0:
            return None, r.stderr.decode(errors="replace")[-400:]
        if not Path(out).exists() or Path(out).stat().st_size < 100:
            return None, "step missing or empty"
        return out, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


def _call_openai(model: str, img_path: Path, api_key: str) -> tuple[str | None, str | None]:
    import base64, re, openai
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    sys.path.insert(0, str(ROOT))
    from bench.models import SYSTEM_PROMPT, USER_PROMPT
    client = openai.OpenAI(api_key=api_key)
    try:
        tok_param = "max_completion_tokens" if model.startswith("gpt-5") else "max_tokens"
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64}", "detail": "high"
                    }},
                ]},
            ],
            **{tok_param: 2048},
            temperature=0.0,
        )
        code = resp.choices[0].message.content
        code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.M)
        code = re.sub(r"```\s*$", "", code, flags=re.M)
        return code.strip(), None
    except Exception as e:
        return None, str(e)[:200]


def _render_step(step_path: str, out_png: Path) -> bool:
    """Render a STEP file to a composite PNG using the cad_synth renderer."""
    try:
        from scripts.data_generation.cad_synth.pipeline.exporter import render_views
        render_views(step_path, out_png.parent, composite_name=out_png.name)
        return True
    except Exception:
        return False


def step_eval(meta_paths: list[Path], model: str, api_key: str,
              save_code: bool, save_render: bool) -> list[dict]:
    from bench.metrics import compute_iou, compute_chamfer, extract_features, feature_f1

    print(f"\n[3/3] EVAL  model={model}  samples={len(meta_paths)}"
          f"  save_code={save_code}  save_render={save_render}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    out_jsonl = RESULTS / "results.jsonl"

    # Load already-done stems
    done: set[str] = set()
    if out_jsonl.exists():
        for line in out_jsonl.read_text().splitlines():
            try:
                done.add(json.loads(line)["stem"])
            except Exception:
                pass

    results = []
    with open(out_jsonl, "a") as fout:
        for i, mp in enumerate(meta_paths):
            meta = json.loads(mp.read_text())
            stem = meta["stem"]

            if stem in done:
                print(f"  [{i+1}/{len(meta_paths)}] {stem}  SKIP (already done)")
                continue

            img_path = mp.parent / "composite.png"
            gt_features = json.loads(meta["feature_tags"]) if isinstance(meta["feature_tags"], str) else meta["feature_tags"]

            res = {
                "stem": stem, "family": meta["family"],
                "difficulty": meta["difficulty"], "base_plane": meta["base_plane"],
                "model": model, "exec_ok": 0,
                "iou": 0.0, "chamfer": float("inf"),
                "feature_f1": 0.0, "detail_score": 0.0,
                "gt_features": gt_features, "gen_features": {}, "error": None,
            }

            # Call VLM (reads image from disk, not memory)
            t0 = time.time()
            gen_code, err = _call_openai(model, img_path, api_key)
            res["vlm_latency_s"] = round(time.time() - t0, 2)

            if not gen_code:
                res["error"] = f"vlm_fail: {err}"
                _write(fout, res, results)
                print(f"  [{i+1}/{len(meta_paths)}] {stem}  VLM FAIL")
                continue

            if save_code:
                (RESULTS / stem).mkdir(exist_ok=True)
                (RESULTS / stem / "gen_code.py").write_text(gen_code)

            # Execute generated code
            gen_step, exec_err = _exec_cq(gen_code)
            gen_feats = extract_features(gen_code)
            res["gen_features"] = gen_feats
            res["feature_f1"] = round(feature_f1(gen_feats, gt_features), 4)

            if not gen_step:
                res["error"] = f"exec_fail: {exec_err}"
                res["detail_score"] = round(0.6 * res["feature_f1"], 4)
                _write(fout, res, results)
                print(f"  [{i+1}/{len(meta_paths)}] {stem}  EXEC FAIL  f1={res['feature_f1']:.3f}")
                continue

            res["exec_ok"] = 1

            # Execute GT code
            gt_step, gt_err = _exec_cq(meta["gt_code"])
            if not gt_step:
                res["error"] = f"gt_exec_fail: {gt_err}"
                res["detail_score"] = round(0.6 * res["feature_f1"], 4)
                Path(gen_step).unlink(missing_ok=True)
                _write(fout, res, results)
                print(f"  [{i+1}/{len(meta_paths)}] {stem}  GT FAIL")
                continue

            # Geometry metrics
            iou, _ = compute_iou(gt_step, gen_step)
            cd,  _ = compute_chamfer(gt_step, gen_step)
            res["iou"]          = round(iou, 4)
            res["chamfer"]      = round(cd, 6) if cd != float("inf") else float("inf")
            res["detail_score"] = round(0.4 * iou + 0.6 * res["feature_f1"], 4)

            if save_render:
                render_out = RESULTS / stem / "gen_render.png"
                render_out.parent.mkdir(exist_ok=True)
                _render_step(gen_step, render_out)

            Path(gen_step).unlink(missing_ok=True)
            Path(gt_step).unlink(missing_ok=True)

            _write(fout, res, results)
            print(f"  [{i+1}/{len(meta_paths)}] {stem}  "
                  f"exec=1  iou={iou:.3f}  f1={res['feature_f1']:.3f}  "
                  f"detail={res['detail_score']:.3f}")

    return results


def _write(f, res: dict, results: list) -> None:
    results.append(res)
    f.write(json.dumps(res) + "\n")
    f.flush()


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    if not results:
        return
    total   = len(results)
    exec_ok = [r for r in results if r["exec_ok"]]
    ious    = [r["iou"] for r in exec_ok]
    f1s     = [r["feature_f1"] for r in results]
    details = [r["detail_score"] for r in results]

    print(f"\n{'='*50}")
    print(f"  N={total}  model={results[0].get('model','?')}")
    print(f"  Exec%   : {len(exec_ok)/total*100:.1f}%")
    print(f"  IoU     : {sum(ious)/len(ious):.3f}" if ious else "  IoU     : —")
    print(f"  Feat-F1 : {sum(f1s)/len(f1s):.3f}")
    print(f"  Detail↑ : {sum(details)/len(details):.3f}")
    print(f"  Results : {RESULTS / 'results.jsonl'}")
    print(f"{'='*50}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="MechEval test run")
    ap.add_argument("--repo",        default="Hula0401/cad_synth_bench")
    ap.add_argument("--split",       default="test_iid")
    ap.add_argument("--limit",       type=int, default=10)
    ap.add_argument("--per-family",  type=int, default=0, help="stratified: N per family")
    ap.add_argument("--model",       default="gpt-4o")
    ap.add_argument("--step",        choices=["fetch", "render", "eval", "all"], default="all")
    ap.add_argument("--save-code",   action="store_true", help="save gen_code.py per sample")
    ap.add_argument("--save-render", action="store_true", help="save gen_render.png per sample")
    ap.add_argument("--api-key",     default=None)
    args = ap.parse_args()

    token   = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY1")

    if not api_key and args.step in ("eval", "all"):
        sys.exit("OPENAI_API_KEY not set")

    # Step 1
    if args.step in ("fetch", "all"):
        meta_paths = step_fetch(args.repo, args.split, args.limit, token,
                                per_family=args.per_family)
    else:
        meta_paths = sorted(DATA.glob("*/meta.json"))[:args.limit]
        if not meta_paths:
            sys.exit("No local data found. Run with --step fetch first.")

    # Step 2
    if args.step in ("render", "eval", "all"):
        meta_paths = step_render(meta_paths)

    # Step 3
    if args.step in ("eval", "all"):
        results = step_eval(meta_paths, args.model, api_key,
                            args.save_code, args.save_render)
        print_summary(results)


if __name__ == "__main__":
    main()
