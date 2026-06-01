"""Unit tests for embedded-metadata extraction (filemanaty/metadata.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from filemanaty import metadata

# A standard ComfyUI API-format prompt: KSampler -> 2x CLIPTextEncode, a
# checkpoint loader, and one LoRA. This is the "everything present" graph.
STD_PROMPT = {
    "3": {"class_type": "KSampler", "inputs": {
        "seed": 42, "steps": 20, "model": ["4", 0],
        "positive": ["6", 0], "negative": ["7", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "sdxl_base.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a fluffy cat"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality"}},
    "10": {"class_type": "LoraLoader", "inputs": {"lora_name": "add_detail.safetensors"}},
}


def test_summarize_standard_graph_extracts_all_fields():
    assert metadata.summarize(STD_PROMPT) == {
        "positive": "a fluffy cat",
        "negative": "blurry, low quality",
        "seed": 42,
        "model": "sdxl_base.safetensors",
        "loras": ["add_detail.safetensors"],
    }


def test_summarize_missing_checkpoint_degrades_model_to_none():
    prompt = {k: v for k, v in STD_PROMPT.items() if k != "4"}
    fields = metadata.summarize(prompt)
    assert fields["model"] is None
    assert fields["positive"] == "a fluffy cat"
    assert fields["seed"] == 42


def test_summarize_custom_graph_degrades_all_to_none():
    custom = {"1": {"class_type": "SomeCustomNode", "inputs": {"foo": "bar"}}}
    assert metadata.summarize(custom) == {
        "positive": None, "negative": None, "seed": None, "model": None, "loras": []}


def test_summarize_none_returns_empty_fields():
    assert metadata.summarize(None) == {
        "positive": None, "negative": None, "seed": None, "model": None, "loras": []}


def test_build_envelope_parses_workflow_and_prompt_json():
    raw = {"workflow": json.dumps({"nodes": []}), "prompt": json.dumps(STD_PROMPT),
           "Software": "ComfyUI"}
    env = metadata._build_envelope(raw)
    assert env["workflow"] == {"nodes": []}
    assert env["prompt"] == STD_PROMPT
    assert env["other"] == {"Software": "ComfyUI"}


def test_build_envelope_keeps_non_json_as_raw_string():
    env = metadata._build_envelope({"workflow": "not json {"})
    assert env["workflow"] == "not json {"


def test_build_envelope_skips_oversized_field():
    huge = "x" * (metadata.MAX_RAW_BYTES + 1)
    env = metadata._build_envelope({"prompt": huge})
    assert env["prompt"] is None


from PIL import Image
from PIL.PngImagePlugin import PngInfo


def _make_png(path: Path, *, workflow=None, prompt=None) -> None:
    info = PngInfo()
    if workflow is not None:
        info.add_text("workflow", json.dumps(workflow))
    if prompt is not None:
        info.add_text("prompt", json.dumps(prompt))
    Image.new("RGB", (8, 8), "red").save(path, "PNG", pnginfo=info)


def test_extract_png_with_workflow_and_prompt(tmp_path):
    p = tmp_path / "gen.png"
    _make_png(p, workflow={"nodes": []}, prompt=STD_PROMPT)
    env = metadata.extract(p)
    assert env is not None
    assert env["workflow"] == {"nodes": []}
    assert env["prompt"] == STD_PROMPT


def test_extract_png_without_text_returns_none(tmp_path):
    p = tmp_path / "plain.png"
    Image.new("RGB", (8, 8), "blue").save(p, "PNG")
    assert metadata.extract(p) is None


def test_extract_unknown_extension_returns_none(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    assert metadata.extract(p) is None
