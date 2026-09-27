#!/usr/bin/env python3
"""Build personalized AP Psychology review guides from the master Typst document.

Pipeline
--------
1. ``typst.query(master, "<knowledge>", field="value")`` collects the metadata
   of every knowledge entry (id, topic, unit, tags, difficulty) in the master's
   pedagogical order.
2. ``content_db.json`` (auto-regenerated when missing or stale) supplies each
   entry's raw body text, extracted from the source files by
   ``extract_bodies.py``.
3. The profile filters the entries. Filter categories (ids / units / tags /
   difficulty) combine with AND; the values *within* one category combine with
   OR. ``exclude_ids`` removes entries at the end.
4. A standalone guide is emitted under ``out/`` as a self-contained bundle:
   the generated ``.typ`` plus build-managed copies of ``lib.typ`` and
   ``review_guide.typ``, so a plain ``typst compile`` works inside that folder.

Example
-------
    python build.py --master ../main.typ \\
                    --profile profiles/example_student.json \\
                    --output ../out/student_review.typ

The build never mutates source files: it only writes ``out/`` and (when stale)
``content_db.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import typst

from extract_bodies import (
    Entry,
    ExtractionError,
    build_db,
    extract_directory,
    validate_body,
    write_db,
)

# Keep in sync with UNIT_NAMES in lib.typ (an array there, a dict here).
UNIT_NAMES: dict[int, str] = {
    0: "Research Design (Research Methods)",
    1: "Biological Bases of Behavior",
    2: "Cognition",
    3: "Development and Learning",
    4: "Social Psychology and Personality",
    5: "Mental and Physical Health",
}

VALID_DIFFICULTIES = ("core", "standard", "advanced")

_TEMPLATE_LIB_IMPORT = re.compile(r'#import\s+"[^"]*lib\.typ"\s*:\s*\*')


class BuildError(RuntimeError):
    """Raised for any user-facing build failure (bad profile, query failure...)."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class KnowledgeEntry:
    """A queryable knowledge item: metadata (from the master) + body (from the db)."""

    id: str
    topic: str
    unit: int
    tags: tuple[str, ...]
    difficulty: str
    body: str


@dataclass
class Profile:
    """Student profile: an optional selection of filters (all optional)."""

    name: str = "Student"
    title: str | None = None
    ids: tuple[str, ...] = ()
    units: tuple[int, ...] = ()
    tags: tuple[str, ...] = ()
    difficulty: tuple[str, ...] = ()
    exclude_ids: tuple[str, ...] = ()
    path: Path | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> "Profile":
        """Validate a profile dictionary and return a Profile."""
        if not isinstance(data, dict):
            raise BuildError(f"profile {path} must contain a JSON object")

        def strings(key: str) -> tuple[str, ...]:
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise BuildError(f"profile field {key!r} must be a list of strings")
            return tuple(value)

        units_raw = data.get("units", [])
        if not isinstance(units_raw, list) or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in units_raw
        ):
            raise BuildError("profile field 'units' must be a list of integers (0-5)")
        for unit in units_raw:
            if unit not in UNIT_NAMES:
                raise BuildError(f"profile field 'units' contains unknown unit {unit!r} (expected 0-5)")

        difficulty = strings("difficulty")
        for level in difficulty:
            if level not in VALID_DIFFICULTIES:
                raise BuildError(
                    f"profile field 'difficulty' contains {level!r}; expected one of {VALID_DIFFICULTIES}"
                )

        name = data.get("name", "Student")
        title = data.get("title")
        if not isinstance(name, str) or not name.strip():
            raise BuildError("profile field 'name' must be a non-empty string")
        if title is not None and not isinstance(title, str):
            raise BuildError("profile field 'title' must be a string")

        return cls(
            name=name,
            title=title,
            ids=strings("ids"),
            units=tuple(units_raw),
            tags=strings("tags"),
            difficulty=difficulty,
            exclude_ids=strings("exclude_ids"),
            path=path,
        )

    @classmethod
    def empty(cls) -> "Profile":
        """A profile with no filters: selects the full knowledge base."""
        return cls(name="Full Knowledge Base", title="AP Psychology — Complete Review")


# ---------------------------------------------------------------------------
# Step 1: query the master
# ---------------------------------------------------------------------------
def query_master(master: Path) -> list[dict[str, Any]]:
    """Run typst.query on the master and return raw metadata dictionaries."""
    if not master.is_file():
        raise BuildError(f"master file not found: {master}")
    try:
        raw = typst.query(str(master), "<knowledge>", field="value")
    except Exception as exc:  # noqa: BLE001 - surface compiler errors verbatim
        raise BuildError(f"could not query master {master}: {exc}") from exc
    try:
        items = json.loads(raw) if isinstance(raw, str) else list(raw)
    except json.JSONDecodeError as exc:
        raise BuildError(f"unexpected query output from {master}: {exc}") from exc

    entries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not {"id", "topic", "unit", "tags", "difficulty"} <= set(item):
            raise BuildError(f"malformed <knowledge> metadata in {master}: {item!r}")
        entries.append(item)
    if not entries:
        raise BuildError(
            f"no <knowledge> metadata found in {master}; check that unit files are included"
        )
    return entries


# ---------------------------------------------------------------------------
# Step 2: content database (auto-refresh when stale)
# ---------------------------------------------------------------------------
def _db_is_stale(db_path: Path, units_dir: Path) -> bool:
    """True when content_db.json is missing or older than any unit source file."""
    if not db_path.is_file():
        return True
    db_mtime = db_path.stat().st_mtime
    newest_source = max(p.stat().st_mtime for p in units_dir.rglob("*.typ"))
    return newest_source > db_mtime


def ensure_db(master: Path, force: bool = False) -> tuple[dict[str, str], bool]:
    """Load content_db.json, regenerating it first when missing or stale.

    Returns (db, regenerated).
    """
    root = master.parent
    units_dir = root / "units"
    db_path = root / "content_db.json"
    if force or _db_is_stale(db_path, units_dir):
        try:
            entries = extract_directory(units_dir)
        except ExtractionError as exc:
            raise BuildError(f"body extraction failed: {exc}") from exc
        write_db(build_db(entries), db_path)
        return build_db(entries), True
    return json.loads(db_path.read_text(encoding="utf-8")), False


def merge_entries(metadata: list[dict[str, Any]], db: dict[str, str], master: Path) -> list[KnowledgeEntry]:
    """Join queried metadata with extracted bodies."""
    entries: list[KnowledgeEntry] = []
    for item in metadata:
        entry_id = str(item["id"])
        if entry_id not in db:
            raise BuildError(
                f"entry {entry_id!r} exists in the master but has no body in content_db.json; "
                "delete content_db.json (or pass --force-extract) and rebuild"
            )
        tags = item["tags"]
        entries.append(
            KnowledgeEntry(
                id=entry_id,
                topic=str(item["topic"]),
                unit=int(item["unit"]),
                tags=tuple(str(t) for t in tags),
                difficulty=str(item["difficulty"]),
                body=db[entry_id],
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Step 3: profile filtering
# ---------------------------------------------------------------------------
def select_entries(entries: list[KnowledgeEntry], profile: Profile) -> list[KnowledgeEntry]:
    """Apply the profile filters (AND across categories, OR within one)."""
    by_id = {e.id: e for e in entries}
    unknown_ids = [i for i in profile.ids if i not in by_id]
    unknown_excludes = [i for i in profile.exclude_ids if i not in by_id]
    if unknown_ids or unknown_excludes:
        available = "\n  ".join(sorted(by_id))
        raise BuildError(
            "profile references unknown id(s): "
            + ", ".join(unknown_ids + unknown_excludes)
            + f"\nKnown ids ({len(by_id)}):\n  {available}"
        )

    chosen = entries
    if profile.ids:
        wanted = set(profile.ids)
        chosen = [e for e in chosen if e.id in wanted]
    if profile.units:
        units = set(profile.units)
        chosen = [e for e in chosen if e.unit in units]
    if profile.tags:
        tags = set(profile.tags)
        chosen = [e for e in chosen if tags.intersection(e.tags)]
    if profile.difficulty:
        levels = set(profile.difficulty)
        chosen = [e for e in chosen if e.difficulty in levels]
    if profile.exclude_ids:
        excluded = set(profile.exclude_ids)
        chosen = [e for e in chosen if e.id not in excluded]
    return chosen


# ---------------------------------------------------------------------------
# Step 4: render the standalone guide
# ---------------------------------------------------------------------------
def _typst_str(value: str) -> str:
    """Escape a Python string as a Typst string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tags_literal(tags: tuple[str, ...]) -> str:
    """Render a Typst array literal for tags, with a trailing comma."""
    inner = "".join(_typst_str(t) + ", " for t in tags)
    return "(" + inner + ")"


def render_guide(entries: list[KnowledgeEntry], profile: Profile, total: int) -> str:
    """Render the complete standalone .typ review guide."""
    title = profile.title or f"AP Psychology Review — {profile.name}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = []
    lines.append("// " + "=" * 76)
    lines.append("// AUTO-GENERATED by build/build.py — DO NOT EDIT BY HAND.")
    lines.append(f"// Generated: {now} | Profile: {_typst_str(profile.name)} | Entries: {len(entries)} of {total}")
    lines.append("// Rebuild with: python build/build.py --master <master> --profile <profile.json>")
    lines.append("//")
    lines.append("// This folder is a self-contained bundle: lib.typ and review_guide.typ are")
    lines.append("// build-managed copies, so `typst compile <this file>` works right here.")
    lines.append("// " + "=" * 76)
    lines.append('#import "lib.typ": *')
    lines.append('#import "review_guide.typ": review_guide')
    lines.append("")
    lines.append("#show: review_guide.with(")
    lines.append(f"  title: {_typst_str(title)},")
    lines.append(f"  student: {_typst_str(profile.name)},")
    lines.append(f"  ids: {_tags_literal(tuple(e.id for e in entries))}")
    lines.append(")")
    lines.append("")

    # Group consecutive entries by unit (entries arrive in master order).
    groups: list[tuple[int, list[KnowledgeEntry]]] = []
    for entry in entries:
        if not groups or groups[-1][0] != entry.unit:
            groups.append((entry.unit, []))
        groups[-1][1].append(entry)

    for unit, group_entries in groups:
        unit_name = UNIT_NAMES.get(unit, f"Unit {unit}")
        lines.append(f"= Unit {unit} — {unit_name}")
        lines.append("")
        for entry in group_entries:
            validate_body(entry.body, f"entry {entry.id!r}")
            lines.append(
                f"#review_entry(id: {_typst_str(entry.id)}, topic: {_typst_str(entry.topic)}, "
                f"unit: {entry.unit}, tags: {_tags_literal(entry.tags)}, "
                f"difficulty: {_typst_str(entry.difficulty)})["
            )
            lines.append(entry.body)
            lines.append("]")
            lines.append("")
    return "\n".join(lines)


def write_bundle(output: Path, guide_text: str, lib_path: Path, template_path: Path) -> None:
    """Write the guide plus build-managed copies of lib.typ and the template.

    Typst forbids imports that escape the project root (the output file's
    folder by default), so the bundle copies make `typst compile` work with
    no extra flags.
    """
    if not lib_path.is_file():
        raise BuildError(f"lib.typ not found next to the master (expected {lib_path})")
    if not template_path.is_file():
        raise BuildError(f"review guide template not found (expected {template_path})")
    template_source = template_path.read_text(encoding="utf-8")
    bundle_template = _TEMPLATE_LIB_IMPORT.sub('#import "lib.typ": *', template_source, count=1)
    if bundle_template == template_source:
        raise BuildError(
            f"could not rewrite the lib import in {template_path}; "
            "the template must import lib.typ via a quoted path"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(guide_text, encoding="utf-8")
    (output.parent / "lib.typ").write_text(lib_path.read_text(encoding="utf-8"), encoding="utf-8")
    (output.parent / "review_guide.typ").write_text(bundle_template, encoding="utf-8")


def maybe_compile(output: Path, do_compile: bool) -> None:
    """Optionally compile the generated guide to PDF, surfacing warnings."""
    if not do_compile:
        return
    try:
        pdf_path = output.with_suffix(".pdf")
        _, warnings = typst.compile_with_warnings(str(output), output=str(pdf_path))
    except Exception as exc:  # noqa: BLE001 - surface compiler errors verbatim
        raise BuildError(f"generated guide failed to compile: {exc}") from exc
    if warnings:
        print(f"compiled with {len(warnings)} warning(s):", file=sys.stderr)
        for warning in warnings:
            print(f"  warning: {warning}", file=sys.stderr)
    else:
        pdf = output.with_suffix(".pdf")
        size = pdf.stat().st_size if pdf.is_file() else 0
        print(f"compiled cleanly (no warnings), PDF: {pdf} ({size} bytes)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def list_entries(entries: list[KnowledgeEntry]) -> None:
    """Print a compact table of the knowledge base."""
    print(f"{'id':40} {'unit':>4}  {'difficulty':9} topic")
    for e in entries:
        print(f"{e.id:40} {e.unit:>4}  {e.difficulty:9} {e.topic}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    build_dir = Path(__file__).resolve().parent
    repo_root = build_dir.parent

    parser = argparse.ArgumentParser(
        description="Build a filtered, standalone AP Psychology review guide (.typ)."
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=repo_root / "main.typ",
        help="path to the master document (default: <repo>/main.typ)",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="path to a profile JSON; omit for the full knowledge base",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "out" / "student_review.typ",
        help="path of the generated guide (default: <repo>/out/student_review.typ)",
    )
    parser.add_argument("--title", help="override the guide title")
    parser.add_argument("--student", help="override the student name")
    parser.add_argument(
        "--compile", action="store_true", help="also compile the guide to PDF after writing"
    )
    parser.add_argument(
        "--force-extract",
        action="store_true",
        help="regenerate content_db.json even if it appears fresh",
    )
    parser.add_argument(
        "--list", action="store_true", help="list all knowledge entries and exit"
    )
    args = parser.parse_args(argv)

    try:
        metadata = query_master(args.master)
        db, regenerated = ensure_db(args.master, force=args.force_extract)
        entries = merge_entries(metadata, db, args.master)

        if args.list:
            list_entries(entries)
            return 0

        if args.profile is not None:
            if not args.profile.is_file():
                raise BuildError(f"profile file not found: {args.profile}")
            data = json.loads(args.profile.read_text(encoding="utf-8"))
            profile = Profile.from_dict(data, args.profile)
        else:
            profile = Profile.empty()
        if args.title:
            profile.title = args.title
        if args.student:
            profile.name = args.student

        chosen = select_entries(entries, profile)
        if not chosen:
            raise BuildError(
                "the profile selected 0 entries; loosen the filters "
                "(ids / units / tags / difficulty / exclude_ids)"
            )

        guide_text = render_guide(chosen, profile, total=len(entries))
        write_bundle(args.output, guide_text, args.master.parent / "lib.typ",
                     args.master.parent / "build" / "templates" / "review_guide.typ")
        maybe_compile(args.output, args.compile)

        by_unit: dict[int, int] = {}
        for e in chosen:
            by_unit[e.unit] = by_unit.get(e.unit, 0) + 1
        print(f"Selected {len(chosen)} of {len(entries)} knowledge entries.")
        print("Breakdown by unit:")
        for unit in sorted(by_unit):
            print(f"  Unit {unit} — {UNIT_NAMES.get(unit, unit)}: {by_unit[unit]}")
        print(f"content_db.json: {'regenerated' if regenerated else 'fresh'} ({len(db)} entries)")
        print(f"Output: {args.output.resolve()}")
        return 0
    except BuildError as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"build failed: invalid JSON ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
