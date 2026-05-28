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
    assert cfg.files.allow_hidden is False
    assert ".png" in cfg.files.image_extensions
    assert cfg.thumbnails.enabled is True
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
    assert cfg.files.allow_hidden is True
    assert cfg.files.image_extensions == (".png",)
    assert cfg.thumbnails.enabled is False
    assert cfg.thumbnails.max_dimension == 128


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
