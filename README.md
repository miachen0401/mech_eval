# MechEval

**A Comprehensive Benchmark for Industrial CAD Generation**

73 mechanical part families · 3 difficulty levels · IID + OOD splits

## Dataset

```python
from datasets import load_dataset
ds = load_dataset("Hula0401/cad_synth_bench")
```

## Evaluate Your Model

```bash
pip install openai cadquery trimesh scipy datasets pillow

# GPT-4o on IID split
python eval.py --model gpt-4o --split test_iid --out results.jsonl

# Local Qwen2-VL checkpoint
python eval.py --model local:./your-checkpoint --split all --out results.jsonl
```

## Metrics

| Metric | Description |
|--------|-------------|
| `exec%` | % of samples that execute without error |
| `IoU` | Volumetric IoU vs GT (scale-invariant) |
| `CD` | Chamfer Distance (lower=better) |
| `Feature-F1` | F1 over structural features (hole/fillet/chamfer/slot) |
| `Detail↑` | `0.4×IoU + 0.6×Feature-F1` (primary ranking metric) |

## Splits

| Split | Criteria |
|-------|----------|
| `test_iid` | Standard families, XY base plane |
| `test_ood_family` | Unseen families (bellows, impeller, propeller, …) |
| `test_ood_plane` | Standard families on XZ/YZ planes |
