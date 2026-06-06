from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillManifestError(ValueError):
    """SKILL.md 缺失/不合法。"""


@dataclass
class SkillManifest:
    name: str
    description: str
    requires: dict = field(default_factory=dict)
    version: str = "0.0.0"


def parse_skill_md(text: str) -> SkillManifest:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillManifestError("SKILL.md missing YAML frontmatter")
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise SkillManifestError(f"invalid YAML frontmatter: {e}") from e
    if not isinstance(data, dict):
        raise SkillManifestError("frontmatter must be a mapping")

    name = data.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name) or ".." in name:
        raise SkillManifestError(f"invalid or missing skill name: {name!r}")

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillManifestError("missing skill description")

    requires = data.get("requires", {})
    if not isinstance(requires, dict):
        raise SkillManifestError("requires must be a mapping if present")

    version = data.get("version", "0.0.0")
    if not isinstance(version, str):
        raise SkillManifestError("version must be a string")

    return SkillManifest(
        name=name, description=description, requires=requires, version=version
    )
