"""Dataset loading — HuggingFace or local run directory."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path


def load_hf(repo: str, split: str, token: str | None = None) -> list[dict]:
    """Load one or all splits from an HF dataset repo."""
    from datasets import load_dataset

    ds = load_dataset(repo, token=token)
    if split == "all":
        rows = []
        for sp in ["test_iid", "test_ood_family", "test_ood_plane"]:
            if sp in ds:
                rows.extend(ds[sp])
        return rows
    return list(ds[split])


def stratified_sample(rows: list[dict], per_family: int) -> list[dict]:
    by_fam: dict[str, list] = defaultdict(list)
    for r in rows:
        by_fam[r["family"]].append(r)
    return [r for fam_rows in by_fam.values() for r in fam_rows[:per_family]]


def load_done_stems(out_path: Path) -> set[str]:
    done: set[str] = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["stem"])
                except Exception:
                    pass
    return done
