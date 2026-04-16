"""VLM model wrappers — OpenAI and local Qwen2-VL / Qwen2.5-VL."""
from __future__ import annotations

import base64
import io
import os
import re

SYSTEM_PROMPT = """You are an expert CAD engineer. You will be shown a 2×2 composite image of an industrial mechanical part rendered from 4 fixed viewpoints:
- Top-left:     front view   (camera at [0, -1,  0], looking along +Y)
- Top-right:    right view   (camera at [1,  0,  0], looking along -X)
- Bottom-left:  top view     (camera at [0,  0,  1], looking along -Z)
- Bottom-right: isometric view (camera at [1, -1,  1], normalized)

All renders are normalized: the part fills roughly the same bounding box across views.

Your task: generate executable CadQuery Python code that recreates this part geometry.

Requirements:
- Use standard CadQuery operations: Workplane, extrude, revolve, sweep, loft, union, cut, fillet, chamfer, hole, shell, etc.
- Store the final solid in a variable named `result`
- Do NOT include import statements (cadquery is pre-imported as `import cadquery as cq`)
- Do NOT include show_object() or any display calls
- Always make your best attempt — even for complex shapes, approximate geometry is better than refusing
- Output ONLY executable Python code, no explanation or markdown

Example:
result = (
    cq.Workplane("XY")
    .circle(10)
    .extrude(5)
    .faces(">Z").hole(4)
)"""

CADRILLE_SYSTEM_PROMPT = (
    "You are a CadQuery expert. Given a 2×2 grid of normalized multi-view renders "
    "of a mechanical part (four diagonal viewpoints: [1,1,1], [-1,-1,-1], [-1,1,-1], "
    "[1,-1,1]), write CadQuery Python code that reproduces the geometry. "
    "Output ONLY Python code."
)

USER_PROMPT = "Generate CadQuery code to recreate this industrial part shown in the 4-view composite render."

_local_cache: dict = {}


def _strip_fences(code: str) -> str:
    code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.M)
    code = re.sub(r"```\s*$", "", code, flags=re.M)
    return code.strip()


def image_to_b64(pil_img) -> str:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── OpenAI ────────────────────────────────────────────────────────────────────

def call_openai(model: str, b64_img: str, api_key: str) -> tuple[str | None, str | None]:
    import openai
    client = openai.OpenAI(api_key=api_key)
    try:
        # gpt-5.x uses max_completion_tokens; older models use max_tokens
        tok_param = "max_completion_tokens" if model.startswith("gpt-5") else "max_tokens"
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
            **{tok_param: 2048},
            temperature=0.0,
        )
        return _strip_fences(resp.choices[0].message.content), None
    except Exception as e:
        return None, str(e)[:200]


# ── Local Qwen2-VL / Qwen2.5-VL ──────────────────────────────────────────────

def _load_local(model_path: str) -> dict:
    if model_path in _local_cache:
        return _local_cache[model_path]

    import json as _json
    import torch
    from transformers import AutoProcessor

    print(f"\nLoading {model_path} ...", flush=True)
    dtype  = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    device = "cuda" if torch.cuda.is_available() else "cpu"

    model_type = ""
    cfg_path = os.path.join(model_path, "config.json") if os.path.isdir(model_path) else None
    if cfg_path and os.path.exists(cfg_path):
        try:
            model_type = _json.load(open(cfg_path)).get("model_type", "")
        except Exception:
            pass

    if model_type == "qwen2_5_vl":
        from transformers import Qwen2_5_VLForConditionalGeneration
        cls = Qwen2_5_VLForConditionalGeneration
    else:
        from transformers import Qwen2VLForConditionalGeneration
        cls = Qwen2VLForConditionalGeneration

    model = cls.from_pretrained(model_path, torch_dtype=dtype).to(device)
    model.eval()
    processor = AutoProcessor.from_pretrained(model_path)
    _local_cache[model_path] = {"model": model, "processor": processor, "device": device}
    print("Model loaded.", flush=True)
    return _local_cache[model_path]


def call_local(model_path: str, pil_img, max_new_tokens: int = 2048,
               temperature: float = 0.0) -> tuple[str | None, str | None]:
    try:
        import torch
        from qwen_vl_utils import process_vision_info
    except ImportError as e:
        return None, f"missing dep: {e}"

    try:
        state     = _load_local(model_path)
        model     = state["model"]
        processor = state["processor"]
        device    = state["device"]

        messages = [
            {"role": "system", "content": CADRILLE_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image", "image": pil_img},
                {"type": "text",  "text": "Generate CadQuery code for this part."},
            ]},
        ]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(text=[text], images=image_inputs, videos=video_inputs,
                           padding=True, return_tensors="pt").to(device)

        gen_kw: dict = {"max_new_tokens": max_new_tokens}
        if temperature > 0:
            gen_kw.update({"temperature": temperature, "do_sample": True})
        else:
            gen_kw["do_sample"] = False

        with torch.no_grad():
            out = model.generate(**inputs, **gen_kw)
        code = processor.decode(out[0][len(inputs["input_ids"][0]):], skip_special_tokens=True)
        return _strip_fences(code), None
    except Exception as e:
        return None, str(e)[:300]


# ── Dispatch ──────────────────────────────────────────────────────────────────

def call_vlm(model: str, pil_img, api_key: str | None) -> tuple[str | None, str | None]:
    if model.startswith("local:"):
        return call_local(model[len("local:"):], pil_img)
    b64 = image_to_b64(pil_img)
    if model.startswith(("gpt", "o1", "o3")):
        key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY1")
        return call_openai(model, b64, key)
    raise ValueError(f"Unsupported model: {model}. Use 'local:<path>' for local models.")
