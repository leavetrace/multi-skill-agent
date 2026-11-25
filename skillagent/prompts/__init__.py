"""Versioned prompt files: `skillagent/prompts/<name>/v<N>.md` (CONTRACTS §7).

Prompts are files, not string constants, so eval can pin `router=1` vs `router=2` and
report the exact text hash that produced each number.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from skillagent.config import Settings

__all__ = ["PromptLoader", "PromptTemplate"]

_VERSION_FILE = re.compile(r"v(\d+)\.md")
_PROMPT_NAME = re.compile(r"[a-z0-9_]+")
_DEFAULT_ROOT = Path(__file__).resolve().parent


class PromptTemplate(BaseModel):
    name: str
    version: int
    text: str
    sha: str  # first 12 hex chars of sha256(text)

    def render(self, **vars: str) -> str:
        """`string.Template.substitute`: a missing variable raises KeyError instead of
        silently shipping a literal `$var` to the model."""
        return Template(self.text).substitute(**vars)


class PromptLoader:
    def __init__(self, root: Path | None = None, pinned: dict[str, int] | None = None) -> None:
        self.root = root or _DEFAULT_ROOT
        self.pinned = dict(pinned or {})
        self._cache: dict[tuple[str, int], PromptTemplate] = {}

    @classmethod
    def from_settings(cls, settings: Settings, root: Path | None = None) -> PromptLoader:
        return cls(root=root, pinned=settings.prompt_versions)

    def available(self, name: str) -> list[int]:
        """Sorted versions present for `name` (empty if the prompt does not exist)."""
        folder = self._folder(name)
        if not folder.is_dir():
            return []
        versions = (_VERSION_FILE.fullmatch(p.name) for p in folder.iterdir() if p.is_file())
        return sorted(int(m.group(1)) for m in versions if m)

    def load(self, name: str, version: int | None = None) -> PromptTemplate:
        """Explicit `version`, else the pinned one, else the highest available."""
        versions = self.available(name)
        if not versions:
            raise FileNotFoundError(
                f"no prompt named {name!r} under {self.root}; available: {self._names()}"
            )
        chosen = version if version is not None else self.pinned.get(name, versions[-1])
        if chosen not in versions:
            raise FileNotFoundError(
                f"prompt {name!r} has no version {chosen}; available versions: {versions}"
            )
        key = (name, chosen)
        if key not in self._cache:
            raw = (self._folder(name) / f"v{chosen}.md").read_text(encoding="utf-8")
            text = raw.replace("\r\n", "\n")  # same hash on Windows (autocrlf) and Linux
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            self._cache[key] = PromptTemplate(name=name, version=chosen, text=text, sha=sha)
        return self._cache[key]

    def _folder(self, name: str) -> Path:
        if not _PROMPT_NAME.fullmatch(name):
            raise ValueError(f"invalid prompt name {name!r}; use lowercase letters, digits, '_'")
        return self.root / name

    def _names(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and _PROMPT_NAME.fullmatch(p.name) and self.available(p.name)
        )
