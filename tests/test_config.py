"""Tests for filemanaty.config."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from filemanaty.config import (
    Config,
    FilesConfig,
    RootConfig,
    ThumbnailsConfig,
    WriteConfig,
    load_config,
)


def test_default_config_has_outputs_and_inputs_roots(tmp_path):
    """When no config file exists, auto-mount ComfyUI's input + output dirs."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    cfg = load_config(
        config_path=tmp_path / "does-not-exist.json",
        default_output_dir=outputs,
        default_input_dir=inputs,
    )

    assert isinstance(cfg, Config)
    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]
    assert cfg.roots[0].path == outputs.resolve()
    assert cfg.roots[1].path == inputs.resolve()
    assert ".png" in cfg.files.image_extensions
    assert cfg.thumbnails.max_dimension == 320


def test_load_valid_json_config(tmp_path):
    """A valid JSON file overrides defaults."""
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    custom = tmp_path / "custom"
    custom.mkdir()
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"roots": [{"id": "custom", "label": "Custom", "path": "'
        + str(custom).replace("\\", "/")
        + '"}],'
        '"files": {"allow_hidden": true, "image_extensions": [".png"]},'
        '"thumbnails": {"enabled": false, "max_dimension": 128}}'
    )

    cfg = load_config(
        config_path=config_file,
        default_output_dir=output_dir,
        default_input_dir=output_dir,
    )

    assert [r.id for r in cfg.roots] == ["custom"]
    assert cfg.roots[0].path == custom.resolve()
    assert cfg.files.image_extensions == (".png",)
    assert cfg.thumbnails.max_dimension == 128


def test_roots_are_writable_by_default(tmp_path):
    """A root with no 'writable' key is writable (preserves v0.2.0 behavior)."""
    custom = tmp_path / "custom"
    custom.mkdir()
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(
        {"roots": [{"id": "custom", "label": "Custom", "path": str(custom)}]}))

    cfg = load_config(config_path=config_file, default_output_dir=tmp_path, default_input_dir=tmp_path)
    assert cfg.roots[0].writable is True


def test_root_writable_false_is_respected(tmp_path):
    """A root may be marked read-only with 'writable': false."""
    ro = tmp_path / "ro"
    ro.mkdir()
    rw = tmp_path / "rw"
    rw.mkdir()
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"roots": [
        {"id": "ro", "label": "RO", "path": str(ro), "writable": False},
        {"id": "rw", "label": "RW", "path": str(rw), "writable": True},
    ]}))

    cfg = load_config(config_path=config_file, default_output_dir=tmp_path, default_input_dir=tmp_path)
    by_id = {r.id: r for r in cfg.roots}
    assert by_id["ro"].writable is False
    assert by_id["rw"].writable is True


def test_default_config_roots_are_writable(tmp_path):
    """Auto-mounted output/input roots are writable."""
    (tmp_path / "o").mkdir()
    (tmp_path / "i").mkdir()
    cfg = load_config(config_path=tmp_path / "nope.json",
                      default_output_dir=tmp_path / "o", default_input_dir=tmp_path / "i")
    assert all(r.writable for r in cfg.roots)


def test_malformed_json_falls_back_to_defaults(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("this is not json")

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]  # fell back to defaults
    assert "malformed config" in caplog.text


def test_structural_error_falls_back_to_defaults(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"roots": "not a list"}')

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]
    assert "invalid config" in caplog.text


def test_non_dict_files_falls_back(tmp_path, caplog):
    """Regression: a non-dict 'files' value used to crash with AttributeError."""
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"files": 42}')

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]


def test_non_int_max_dimension_falls_back(tmp_path, caplog):
    """Regression: max_dimension='big' used to crash with ValueError."""
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"thumbnails": {"max_dimension": "big"}}')

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]


def _write_cfg(path, doc):
    path.write_text(json.dumps(doc))


def test_invalid_root_id_falls_back_to_defaults(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    _write_cfg(cfg_file, {"roots": [{"id": "Has Space", "label": "x", "path": str(outputs)}]})

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]  # defaults
    assert "invalid config" in caplog.text


def test_missing_root_path_falls_back(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    _write_cfg(cfg_file, {
        "roots": [{"id": "ghost", "label": "Ghost", "path": str(tmp_path / "no-such-dir")}]
    })

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]  # defaults
    assert "invalid config" in caplog.text


def test_empty_roots_list_accepted_with_warning(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    _write_cfg(cfg_file, {"roots": []})

    with caplog.at_level("WARNING", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert cfg.roots == ()
    assert "no roots configured" in caplog.text


def test_duplicate_root_ids_rejected(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    _write_cfg(cfg_file, {"roots": [
        {"id": "x", "label": "a", "path": str(outputs)},
        {"id": "x", "label": "b", "path": str(outputs)},
    ]})

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]
    assert "invalid config" in caplog.text


def test_max_dimension_out_of_range_rejected(tmp_path, caplog):
    outputs = tmp_path / "outputs"; outputs.mkdir()
    cfg_file = tmp_path / "config.json"
    _write_cfg(cfg_file, {
        "roots": [{"id": "o", "label": "O", "path": str(outputs)}],
        "thumbnails": {"max_dimension": 9999},
    })

    with caplog.at_level("ERROR", logger="filemanaty"):
        cfg = load_config(cfg_file, outputs, outputs)

    assert [r.id for r in cfg.roots] == ["outputs", "inputs"]


def test_write_defaults_to_1024(tmp_path):
    cfg_path = tmp_path / "config.json"  # absent -> defaults
    cfg = load_config(cfg_path, tmp_path, tmp_path)
    assert cfg.write.max_upload_mb == 1024


def test_write_parsed_from_file(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"roots": [], "write": {"max_upload_mb": 50}}))
    cfg = load_config(cfg_path, tmp_path, tmp_path)
    assert cfg.write.max_upload_mb == 50


def test_write_rejects_nonpositive_falls_back(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"roots": [], "write": {"max_upload_mb": 0}}))
    cfg = load_config(cfg_path, tmp_path, tmp_path)
    # invalid config -> loader falls back to defaults (existing behavior)
    assert cfg.write.max_upload_mb == 1024


def test_legacy_allow_hidden_in_config_silently_ignored(tmp_path: Path):
    """Pre-v0.3.0 configs may carry `files.allow_hidden`; the parser ignores it cleanly."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "roots": [{"id": "r", "label": "R", "path": str(tmp_path)}],
        "files": {"allow_hidden": True},
    }))
    cfg = load_config(cfg_path, default_output_dir=tmp_path, default_input_dir=tmp_path)
    assert len(cfg.roots) == 1
    assert not hasattr(cfg.files, "allow_hidden")


def test_legacy_thumbnails_enabled_in_config_silently_ignored(tmp_path: Path):
    """Pre-v0.3.0 configs may carry `thumbnails.enabled`; the parser ignores it cleanly."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "roots": [{"id": "r", "label": "R", "path": str(tmp_path)}],
        "thumbnails": {"enabled": False},
    }))
    cfg = load_config(cfg_path, default_output_dir=tmp_path, default_input_dir=tmp_path)
    assert len(cfg.roots) == 1
    assert not hasattr(cfg.thumbnails, "enabled")
