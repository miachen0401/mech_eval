# Benchmark Plan

现在 `bench/` 里实现的是你这版最小 benchmark 流程：

1. 固定一份 test set
2. 对 test set 跑模型，保存 `valid / iou / cd`
3. 统计 overall 和 per-family baseline

## 文件

- `bench/build_test_manifest.py`
  从 `data/data_generation/synth_parts.csv` 里按 family 分层抽样，固定一份 test manifest。

- `bench/score_benchmark.py`
  读取预测结果，统计：
  - `valid_rate`
  - `mean_iou`
  - `mean_cd`
  - `per-family valid_rate / mean_iou / mean_cd`

## 1. 固定 Test Set

最简单是每个 family 留 20% 做 test。

```bash
uv run python bench/build_test_manifest.py \
  --source-csv data/data_generation/synth_parts.csv \
  --test-ratio 0.2 \
  --out bench/test_manifest.jsonl
```

输出的每条 manifest 至少包含：

- `sample_id`
- `stem`
- `family`
- `difficulty`
- `input_views`
- `gt_code`
- `gt_step`
- `gt_mesh`

## 2. 预测结果格式

`bench/score_benchmark.py` 读取 JSON 或 JSONL。每条最少需要：

- `sample_id`
- `valid`
- `iou`
- `cd`

推荐格式：

```json
{
  "sample_id": "sample_000123",
  "valid": true,
  "iou": 0.87,
  "cd": 0.09,
  "pred_code": "runs/model_a/sample_000123.py",
  "pred_mesh": "runs/model_a/sample_000123.stl"
}
```

如果预测文件里没有 `family` / `difficulty`，脚本会用 manifest 里的信息补齐。

## 3. 计分

运行：

```bash
uv run python bench/score_benchmark.py \
  runs/model_a/predictions.jsonl \
  --manifest bench/test_manifest.jsonl \
  --out bench/model_a_summary.json
```

它会输出两类结果。

Overall：

| metric | score |
| --- | --- |
| valid_rate | 执行成功率 |
| mean_iou | 平均 IoU |
| mean_cd | 平均 Chamfer Distance |

Per family：

| family | count | valid_rate | mean_iou | mean_cd |
| --- | --- | --- | --- | --- |

这样可以很快看出哪些 family 最弱。

## 4. 为什么这样做

这版 benchmark 先只回答三个问题：

- 代码能不能跑
- 几何是不是大体对
- 哪些 family 明显更弱

先把 baseline 跑通，比一开始就上复杂 feature score 更重要。

## 5. 后面可以继续加

如果这套 baseline 跑顺了，后面可以继续加：

- difficulty 分层统计
- weakest family / hardest case 排名
- 多模型横向对比
- 更细的 feature-level score
