import pytest
from agent_cloud_backend.skills.manifest import (
    SkillManifest,
    SkillManifestError,
    parse_skill_md,
)

VALID = """---
name: example-greeting
description: "Print a greeting."
requires:
  bins: [bash]
version: "1.2.3"
---

# example-greeting
body
"""


def test_parse_valid():
    m = parse_skill_md(VALID)
    assert m == SkillManifest(
        name="example-greeting",
        description="Print a greeting.",
        requires={"bins": ["bash"]},
        version="1.2.3",
    )


def test_defaults_when_optional_missing():
    m = parse_skill_md('---\nname: a\ndescription: d\n---\nx\n')
    assert m.requires == {}
    assert m.version == "0.0.0"


def test_missing_frontmatter():
    with pytest.raises(SkillManifestError):
        parse_skill_md("# no frontmatter\n")


def test_bad_yaml():
    with pytest.raises(SkillManifestError):
        parse_skill_md("---\nname: [unclosed\n---\nx\n")


@pytest.mark.parametrize(
    "name",
    ["", "Bad Name", "../evil", "a/b", "..", "UPPER", "with space", "a" * 65],
)
def test_invalid_names_rejected(name):
    with pytest.raises(SkillManifestError):
        parse_skill_md(f'---\nname: "{name}"\ndescription: d\n---\nx\n')


def test_missing_description():
    with pytest.raises(SkillManifestError):
        parse_skill_md("---\nname: ok\n---\nx\n")


def test_requires_must_be_mapping():
    with pytest.raises(SkillManifestError):
        parse_skill_md("---\nname: ok\ndescription: d\nrequires: [bash]\n---\nx\n")


def test_bundled_registry_skill_creator_parses():
    from pathlib import Path

    import agent_cloud_backend

    root = Path(agent_cloud_backend.__file__).parent / "skill_registry" / "skill-creator"
    m = parse_skill_md((root / "SKILL.md").read_text())
    assert m.name == "skill-creator"
