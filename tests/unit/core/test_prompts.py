from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from skillagent.config import Settings
from skillagent.prompts import PromptLoader


@pytest.fixture
def root(tmp_path: Path) -> Path:
    router = tmp_path / "router"
    router.mkdir()
    (router / "v1.md").write_text("Route: $prompt", encoding="utf-8")
    (router / "v2.md").write_text('Route v2 {"json": true} → ${prompt} در $lang', encoding="utf-8")
    (router / "v10.md").write_text("ten $prompt", encoding="utf-8")
    (router / "notes.md").write_text("ignored", encoding="utf-8")
    (tmp_path / "translator").mkdir()
    (tmp_path / "translator" / "v1.md").write_bytes(b"line1\r\nline2 $text\r\n")
    return tmp_path


def test_available_sorted_numerically(root: Path) -> None:
    assert PromptLoader(root).available("router") == [1, 2, 10]
    assert PromptLoader(root).available("missing") == []


def test_highest_version_by_default(root: Path) -> None:
    assert PromptLoader(root).load("router").version == 10


def test_pinned_version(root: Path) -> None:
    loader = PromptLoader(root, pinned={"router": 2})
    assert loader.load("router").version == 2
    assert loader.load("router", version=1).version == 1  # explicit wins over pin


def test_pins_from_settings(root: Path) -> None:
    loader = PromptLoader.from_settings(Settings(prompt_versions="router=1"), root=root)
    assert loader.load("router").text == "Route: $prompt"


def test_render_and_sha(root: Path) -> None:
    template = PromptLoader(root).load("router", 2)
    assert template.render(prompt="hi", lang="فارسی") == 'Route v2 {"json": true} → hi در فارسی'
    assert template.sha == hashlib.sha256(template.text.encode()).hexdigest()[:12]


def test_render_missing_variable_raises(root: Path) -> None:
    with pytest.raises(KeyError, match="lang"):
        PromptLoader(root).load("router", 2).render(prompt="hi")


def test_crlf_normalized_for_stable_hash(root: Path) -> None:
    template = PromptLoader(root).load("translator")
    assert template.text == "line1\nline2 $text\n"


def test_unknown_name_lists_available(root: Path) -> None:
    with pytest.raises(
        FileNotFoundError, match=r"no prompt named 'nope'.*\['router', 'translator'\]"
    ):
        PromptLoader(root).load("nope")


def test_unknown_version_lists_versions(root: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"no version 3; available versions: \[1, 2, 10\]"):
        PromptLoader(root).load("router", 3)


def test_invalid_name_rejected(root: Path) -> None:
    with pytest.raises(ValueError, match="invalid prompt name"):
        PromptLoader(root).load("../secrets")


def test_default_root_is_package_dir() -> None:
    loader = PromptLoader()
    assert loader.root.name == "prompts"
    assert (loader.root / "__init__.py").is_file()
