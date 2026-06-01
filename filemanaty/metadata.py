"""Embedded workflow-metadata extraction for generated media.

Two isolated layers:
  * Format extractors (Layer A, added in later tasks) turn a file into raw
    embedded chunks -> ``{workflow, prompt, other}``.
  * ``summarize`` (Layer B) is the only graph-walking code; it reads ComfyUI's
    API-format ``prompt`` chunk and produces the human card fields, degrading any
    field it can't find to ``None`` and never raising.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("filemanaty")

# Refuse to ingest a single embedded chunk larger than this (defense against a
# pathological file blowing up the JSON response). Per-field, in bytes/chars.
MAX_RAW_BYTES = 8 * 1024 * 1024

_EMPTY_FIELDS = {"positive": None, "negative": None, "seed": None, "model": None, "loras": []}


def _coerce_json(value: str) -> Any:
    """Parse a string as JSON; if it isn't JSON, return the original string."""
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _build_envelope(raw_fields: dict[str, str]) -> dict[str, Any]:
    """Turn a {key: str} map of embedded text into the {workflow, prompt, other} envelope."""
    env: dict[str, Any] = {"workflow": None, "prompt": None, "other": {}}
    for key, value in raw_fields.items():
        if not isinstance(value, str):
            continue
        if len(value) > MAX_RAW_BYTES:
            log.info("filemanaty: metadata field %r too large (%d chars), skipping", key, len(value))
            continue
        lk = key.lower()
        if lk == "workflow":
            env["workflow"] = _coerce_json(value)
        elif lk == "prompt":
            env["prompt"] = _coerce_json(value)
        else:
            env["other"][key] = value
    return env


def _is_link(v: Any) -> bool:
    """An API-format input link is a 2-element [node_id, slot] list."""
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int))


def _node(prompt: dict, node_id: Any) -> Optional[dict]:
    node = prompt.get(str(node_id))
    return node if isinstance(node, dict) else None


def _text_from_link(prompt: dict, link: Any) -> Optional[str]:
    """Follow a positive/negative link to its CLIPTextEncode source and read ``text``."""
    if not _is_link(link):
        return None
    node = _node(prompt, link[0])
    if node is None or "CLIPTextEncode" not in str(node.get("class_type", "")):
        return None
    text = node.get("inputs", {}).get("text")
    return text if isinstance(text, str) else None


def summarize(prompt: Any) -> dict[str, Any]:
    """Best-effort human card from an API-format prompt graph. Never raises."""
    fields: dict[str, Any] = dict(_EMPTY_FIELDS)
    fields["loras"] = []  # fresh list, not the shared _EMPTY_FIELDS one
    if not isinstance(prompt, dict):
        return fields

    # Find the sampler: a node carrying both positive+negative links and a seed.
    # Prefer a KSampler-named node when several match.
    sampler: Optional[dict] = None
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if "positive" in inputs and "negative" in inputs and ("seed" in inputs or "noise_seed" in inputs):
            sampler = node
            if "KSampler" in str(node.get("class_type", "")):
                break

    if sampler is not None:
        inputs = sampler["inputs"]
        seed = inputs.get("seed", inputs.get("noise_seed"))
        if isinstance(seed, int) and not isinstance(seed, bool):
            fields["seed"] = seed
        fields["positive"] = _text_from_link(prompt, inputs.get("positive"))
        fields["negative"] = _text_from_link(prompt, inputs.get("negative"))

    # Model + LoRAs: scan every node (first checkpoint wins; LoRAs accumulate).
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if fields["model"] is None and "CheckpointLoader" in ct:
            name = inputs.get("ckpt_name")
            if isinstance(name, str):
                fields["model"] = name
        if "LoraLoader" in ct:
            name = inputs.get("lora_name")
            if isinstance(name, str) and name not in fields["loras"]:
                fields["loras"].append(name)

    return fields


def _extract_png(path: Path) -> Optional[dict]:
    from PIL import Image
    with Image.open(path) as img:
        text = dict(getattr(img, "text", {}) or {})
    if not text:
        return None
    return _build_envelope(text)


def extract(path: Path) -> Optional[dict]:
    """Public entry: read embedded chunks from a media file -> envelope or None.

    Dispatches by file suffix. Never raises — any extractor error logs and yields
    None so a bad file can never break the caller.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".png":
            return _extract_png(path)
    except Exception as exc:  # noqa: BLE001 - extraction must never propagate
        log.info("filemanaty: metadata extraction failed for %s: %s", path.name, exc)
    return None
