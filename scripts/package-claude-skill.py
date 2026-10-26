#!/usr/bin/env python3
"""Build a portable ZIP of the UI UX Pro Max Claude skill.

The archive follows Claude's custom-skill layout:
  ui-ux-pro-max/SKILL.md
  ui-ux-pro-max/{data,references,scripts}/...

Only runtime files are packaged; tests and test fixtures are excluded.
No third-party Python packages are required.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".claude" / "skills" / "ui-ux-pro-max"
SKILL_NAME = "ui-ux-pro-max"
PORTABLE_DESCRIPTION = "Create and review web, mobile, and desktop UI. Use for layout, design systems, accessibility, responsive behavior, typography, color, interaction, animation, charts, and stack-specific code."
REQUIRED_FILES = (
    "SKILL.md",
    "scripts/search.py",
    "scripts/core.py",
    "scripts/design_system.py",
    "data/styles.csv",
    "data/stacks/react.csv",
    "references/quick-reference.md",
    "references/pro-rules.md",
)
EXCLUDED_PARTS = {"tests", "__pycache__"}
EXCLUDED_NAMES = {".coverage"}


def skill_metadata(skill_text: str) -> tuple[str, str]:
    """Read the required name and description fields from YAML frontmatter."""
    parts = skill_text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError("SKILL.md must begin with YAML frontmatter delimited by ---")
    frontmatter = parts[1]
    name_match = re.search(r"^name:\s*([^\s#]+)\s*$", frontmatter, re.MULTILINE)
    description_match = re.search(r'^description:\s*["\'](.*?)["\']\s*$', frontmatter, re.MULTILINE)
    if not name_match or not description_match:
        raise ValueError("SKILL.md frontmatter must define name and a quoted description")
    return name_match.group(1), description_match.group(1)


def collect_runtime_files() -> list[Path]:
    if not (SKILL_DIR / "SKILL.md").is_file():
        raise FileNotFoundError(f"Missing skill entry point: {SKILL_DIR / 'SKILL.md'}")

    files: list[Path] = []
    for root_name in ("data", "references", "scripts"):
        root = SKILL_DIR / root_name
        if not root.is_dir():
            raise FileNotFoundError(f"Missing required skill directory: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(SKILL_DIR)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.name in EXCLUDED_NAMES or path.suffix in {".pyc", ".pyo"}:
                continue
            files.append(path)

    files.append(SKILL_DIR / "SKILL.md")
    license_file = ROOT / "LICENSE"
    if not license_file.is_file():
        raise FileNotFoundError(f"Missing license file: {license_file}")
    files.append(license_file)

    # A missing reference must fail the build instead of shipping a broken skill.
    available = {
        p.relative_to(SKILL_DIR).as_posix()
        for p in files
        if SKILL_DIR in p.parents
    }
    missing = [name for name in REQUIRED_FILES if name not in available]
    if missing:
        raise FileNotFoundError("Required skill files are missing: " + ", ".join(missing))
    return sorted(set(files), key=lambda p: str(p))


def with_portable_description(skill_text: str) -> str:
    """Shorten only the ZIP copy's metadata to fit Claude.ai's custom-skill limit."""
    lines = skill_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        raise ValueError("SKILL.md frontmatter is missing its closing ---")
    for index in range(1, closing):
        if lines[index].startswith("description:"):
            lines[index] = f'description: "{PORTABLE_DESCRIPTION}"'
            break
    else:
        raise ValueError("SKILL.md frontmatter is missing description")
    return "\n".join(lines) + "\n"


def build_zip(output: Path) -> tuple[int, int]:
    source_skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    source_name, _ = skill_metadata(source_skill_text)
    if source_name != SKILL_NAME:
        raise ValueError(f"Skill name {source_name!r} must match folder name {SKILL_NAME!r}")

    skill_text = with_portable_description(source_skill_text)
    name, description = skill_metadata(skill_text)
    if name != SKILL_NAME:
        raise ValueError(f"Packaged skill name {name!r} must match folder name {SKILL_NAME!r}")
    if len(description) > 200:
        raise ValueError(
            f"Packaged skill description is {len(description)} characters; Claude's limit is 200"
        )

    files = collect_runtime_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for source in files:
            if source == ROOT / "LICENSE":
                archive_name = f"{SKILL_NAME}/LICENSE.txt"
            else:
                archive_name = (Path(SKILL_NAME) / source.relative_to(SKILL_DIR)).as_posix()
            if source == SKILL_DIR / "SKILL.md":
                archive.writestr(archive_name, skill_text.encode("utf-8"))
            else:
                archive.write(source, archive_name)

    with zipfile.ZipFile(output, "r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise zipfile.BadZipFile(f"Corrupt ZIP member: {corrupt}")
        names = set(archive.namelist())
        for relative in REQUIRED_FILES:
            expected = f"{SKILL_NAME}/{relative}"
            if expected not in names:
                raise ValueError(f"Archive validation failed: missing {expected}")
        if not any(name.startswith(f"{SKILL_NAME}/data/") for name in names):
            raise ValueError("Archive validation failed: skill data was not included")
        packaged_skill = archive.read(f"{SKILL_NAME}/SKILL.md").decode("utf-8")
        packaged_name, packaged_description = skill_metadata(packaged_skill)
        if packaged_name != SKILL_NAME or len(packaged_description) > 200:
            raise ValueError("Archive validation failed: invalid Claude custom-skill metadata")

    return len(files), output.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "ui-ux-pro-max-claude-skill.zip",
        help="ZIP output path (default: dist/ui-ux-pro-max-claude-skill.zip)",
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    try:
        count, size = build_zip(output)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Created {output}")
    print(f"Packaged {count} files; ZIP size {size:,} bytes")
    print(f"Archive root: {SKILL_NAME}/SKILL.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
