#!/usr/bin/env python3
"""Extract knowledge-entry bodies into content_db.json.

Walks every ``.typ`` file under ``units/``, finds each ``#knowledge(...)``
call, and captures the raw body text (the trailing content block) keyed by
the entry's ``id`` field.  The output is a JSON object mapping id -> body
that ``build.py`` merges with the metadata it queries from the master.

Extraction backends
-------------------
1. **tree-sitter-typst** (optional): AST-accurate parsing, used automatically
   when the ``tree_sitter_typst`` package is importable.
2. **Bracket-aware scanner** (fallback, always available): a small hand-written
   lexer that understands nested ``[...]`` and ``(...)`` delimiters,
   double-quoted strings, and ``//`` and ``/* */`` comments.  It is validated
   against the whole content set and is the authority when tree-sitter is not
   installed.

Known limitations of the scanner fallback (see README):
  - assumes ``knowledge()`` bodies are written as a single trailing ``[...]``
    content block (the repo's authoring convention);
  - cannot recover from genuinely unbalanced brackets in a body (it reports
    them as extraction errors instead of silently truncating);
  - will extract a call that only appears inside a comment if the comment
    still contains a complete, well-formed ``#knowledge(...)`` call (avoid
    such comments).

Usage::

    python extract_bodies.py [--units-dir PATH] [--output PATH] [--check]

``--check`` extracts and validates everything but writes nothing (CI mode).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# The literal that starts a knowledge() call in source files.
CALL_START = "#knowledge("
# id: "..." within the argument list of a knowledge() call.
_ID_PATTERN = re.compile(r'\bid:\s*"([^"]*)"')

try:  # optional AST backend
    import tree_sitter_typst  # type: ignore[import-not-found]

    TREE_SITTER_AVAILABLE = True
except ModuleNotFoundError:
    TREE_SITTER_AVAILABLE = False


class ExtractionError(RuntimeError):
    """Raised when a source file cannot be parsed or a body is malformed."""


@dataclass(frozen=True)
class Entry:
    """One atomic knowledge entry extracted from a source file."""

    id: str
    body: str
    file: Path
    line: int


# ---------------------------------------------------------------------------
# Low-level lexing helpers (shared by the scanner backend and validation)
# ---------------------------------------------------------------------------
def _skip_string(source: str, i: int, origin: str) -> int:
    """Return the index just past the double-quoted string starting at i."""
    i += 1
    n = len(source)
    while i < n:
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        i += 1
    raise ExtractionError(f"{origin}: unterminated string literal")


def _skip_comment(source: str, i: int, origin: str) -> int:
    """Return the index just past a // or /* */ comment starting at i."""
    if source[i : i + 2] == "//":
        end = source.find("\n", i)
        return len(source) if end == -1 else end + 1
    end = source.find("*/", i + 2)
    if end == -1:
        raise ExtractionError(f"{origin}: unterminated block comment")
    return end + 2


def _is_comment_start(source: str, i: int) -> bool:
    return source[i] == "/" and i + 1 < len(source) and source[i + 1] in "/*"


def _match_delim(source: str, i: int, open_ch: str, close_ch: str, origin: str) -> int:
    """Return the index just past the delimiter matching the one at i.

    Respects nesting, double-quoted strings, and comments.
    """
    depth = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c == '"':
            i = _skip_string(source, i, origin)
            continue
        if _is_comment_start(source, i):
            i = _skip_comment(source, i, origin)
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ExtractionError(f"{origin}: unmatched {open_ch!r} while scanning for {close_ch!r}")


def _skip_ws_and_comments(source: str, i: int, origin: str) -> int:
    """Return the next non-whitespace, non-comment index at or after i."""
    n = len(source)
    while i < n:
        c = source[i]
        if c in " \t\r\n":
            i += 1
        elif _is_comment_start(source, i):
            i = _skip_comment(source, i, origin)
        else:
            return i
    return i


def validate_body(body: str, origin: str = "<body>") -> None:
    """Ensure square brackets are balanced outside strings/comments.

    build.py re-injects each body into a ``[...]`` content block, so an
    unbalanced body would produce an uncompilable guide.  Call this before
    every write.
    """
    depth = 0
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == '"':
            i = _skip_string(body, i, origin)
            continue
        if _is_comment_start(body, i):
            i = _skip_comment(body, i, origin)
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth < 0:
                raise ExtractionError(f"{origin}: unbalanced ']' in body text")
        i += 1
    if depth != 0:
        raise ExtractionError(f"{origin}: unbalanced '[' in body text")


# ---------------------------------------------------------------------------
# Scanner backend (fallback; also the validator of last resort)
# ---------------------------------------------------------------------------
def _scan_call(source: str, paren_idx: int, origin: str) -> tuple[int, int, int]:
    """Scan a ``knowledge(...)`` argument list and its trailing body block.

    ``paren_idx`` must point at the ``(`` that opens the argument list.
    Returns ``(args_end, body_open, body_close)`` where body_open/body_close
    delimit the trailing ``[...]`` content block (exclusive of the brackets).
    """
    args_end = _match_delim(source, paren_idx, "(", ")", origin)
    after = _skip_ws_and_comments(source, args_end, origin)
    if after >= len(source) or source[after] != "[":
        raise ExtractionError(
            f"{origin}: knowledge() call is missing its trailing [...] body block"
        )
    body_close = _match_delim(source, after, "[", "]", origin)
    return args_end, after + 1, body_close - 1


def extract_entries(source: str, origin: Path) -> list[Entry]:
    """Extract every knowledge() entry from one source string (scanner)."""
    entries: list[Entry] = []
    pos = 0
    while True:
        idx = source.find(CALL_START, pos)
        if idx == -1:
            break
        _args_end, body_open, body_close = _scan_call(source, idx + len(CALL_START) - 1, str(origin))
        arg_region = source[idx : body_close]
        id_match = _ID_PATTERN.search(arg_region)
        if id_match is None:
            raise ExtractionError(f"{origin}: knowledge() call without an id field (near line {source.count(chr(10), 0, idx) + 1})")
        body = source[body_open:body_close].strip()
        validate_body(body, f"{origin} (id {id_match.group(1)!r})")
        entries.append(
            Entry(
                id=id_match.group(1),
                body=body,
                file=origin,
                line=source.count("\n", 0, idx) + 1,
            )
        )
        pos = body_close
    return entries


# ---------------------------------------------------------------------------
# Optional tree-sitter backend
# ---------------------------------------------------------------------------
def _extract_entries_tree_sitter(source: str, origin: Path) -> list[Entry] | None:
    """Extract entries with tree-sitter-typst, or return None if the grammar's
    node shapes are unfamiliar (callers then fall back to the scanner)."""
    if not TREE_SITTER_AVAILABLE:
        return None
    try:
        import tree_sitter

        language = tree_sitter.Language(tree_sitter_typst.language())
        parser = tree_sitter.Parser(language)
        tree = parser.parse(source.encode("utf-8"))

        entries: list[Entry] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.children))
            text = node.text or b""
            if not text.startswith(CALL_START.encode()):
                continue
            # The smallest node starting with "#knowledge(" is the call itself;
            # its trailing content block is the last bracket-delimited child.
            blocks = [c for c in node.children if (c.text or b"").startswith(b"[")]
            if not blocks:
                continue
            body_bytes = blocks[-1].text or b""
            body = body_bytes[1:-1].decode("utf-8").strip()
            id_match = _ID_PATTERN.search(text.decode("utf-8", errors="replace"))
            if id_match is None:
                continue
            validate_body(body, f"{origin} (id {id_match.group(1)!r}, tree-sitter)")
            entries.append(
                Entry(
                    id=id_match.group(1),
                    body=body,
                    file=origin,
                    line=node.start_point[0] + 1,
                )
            )
        return entries
    except Exception:  # noqa: BLE001 - any grammar surprise falls back safely
        return None


# ---------------------------------------------------------------------------
# Directory-level extraction and the JSON database
# ---------------------------------------------------------------------------
def extract_directory(units_dir: Path) -> list[Entry]:
    """Extract and validate all entries from every .typ file under units_dir."""
    if not units_dir.is_dir():
        raise ExtractionError(f"units directory not found: {units_dir}")
    entries: list[Entry] = []
    seen: dict[str, Path] = {}
    files = sorted(p for p in units_dir.rglob("*.typ") if not p.name.startswith("_"))
    if not files:
        raise ExtractionError(f"no .typ entry files found under {units_dir}")
    for path in files:
        source = path.read_text(encoding="utf-8")
        scanner_entries = extract_entries(source, path)
        found = scanner_entries
        backend = "scanner"
        if TREE_SITTER_AVAILABLE:
            ts_entries = _extract_entries_tree_sitter(source, path)
            if ts_entries is None:
                print(
                    f"note: tree-sitter backend skipped {path.name}; using scanner fallback",
                    file=sys.stderr,
                )
            elif [e.id for e in ts_entries] != [e.id for e in scanner_entries]:
                # Never trust an AST backend that disagrees with the scanner.
                print(
                    f"note: tree-sitter/scanner mismatch on {path.name}; using scanner fallback",
                    file=sys.stderr,
                )
            else:
                found = ts_entries
                backend = "tree-sitter-typst"
        for entry in found:
            if entry.id in seen:
                raise ExtractionError(
                    f"duplicate knowledge id {entry.id!r} in {path} (first seen in {seen[entry.id]})"
                )
            seen[entry.id] = path
        entries.extend(found)
        print(f"  {path.relative_to(units_dir)}: {len(found)} entry(ies) [{backend}]")
    return entries


def build_db(entries: list[Entry]) -> dict[str, str]:
    """Return the id -> raw body text mapping."""
    return {entry.id: entry.body for entry in entries}


def write_db(db: dict[str, str], output: Path) -> None:
    """Write content_db.json (UTF-8, stable key order)."""
    output.write_text(
        json.dumps(db, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(description="Extract knowledge bodies into content_db.json")
    parser.add_argument(
        "--units-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "units",
        help="directory containing the unit folders (default: <repo>/units)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "content_db.json",
        help="path of the generated content_db.json (default: <repo>/content_db.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="extract and validate only; do not write the database",
    )
    args = parser.parse_args(argv)

    try:
        entries = extract_directory(args.units_dir)
    except ExtractionError as exc:
        print(f"extraction failed: {exc}", file=sys.stderr)
        return 1

    backend = "tree-sitter-typst" if TREE_SITTER_AVAILABLE else "scanner fallback"
    print(f"extracted {len(entries)} entries from {args.units_dir} (backend: {backend})")
    if args.check:
        print("check mode: nothing written")
        return 0
    write_db(build_db(entries), args.output)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
