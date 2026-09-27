# AGENTS.md — operating guide for AI agents

`ap-psych` is a modular, queryable AP Psychology knowledge base: content is
authored in Typst (one atomic knowledge entry per file) and a Python build
pipeline extracts arbitrary subsets into standalone student review guides.

Fuller docs: `README.md` (workflow, profile schema, extraction backends) and
`instruction_to_ai.md` (complete orientation with recipes). This file is the
quick operational reference — keep all three in sync with reality.

## Environment

- Windows + Git Bash; Python 3.13 (`python`, not `python3`). Quote paths —
  the absolute path contains spaces.
- Only dependency: `pip install typst` (typst-py; embeds the Typst compiler).
  Everything else is the standard library.

## Commands (verified)

From `ap-psych/`:

```bash
# verify the master compiles with ZERO warnings — run after every edit
python -c "import typst; _, w = typst.compile_with_warnings('main.typ'); print('warnings:', w or 'none')"

# validate all bodies without writing anything
python build/extract_bodies.py --check

# list the knowledge base (id | unit | difficulty | topic)
python build/build.py --list
```

From `ap-psych/build/`:

```bash
# full guide (also writes a PDF; any warning is a failure)
python build.py --master ../main.typ --output ../out/full_review.typ --compile

# profile-based guide
python build.py --master ../main.typ --profile profiles/example_student.json \
                --output ../out/student_review.typ --compile

# force body re-extraction before building
python build.py --master ../main.typ --force-extract
```

## Architecture

| Path | Role |
|---|---|
| `main.typ` | master document; applies the theme and includes unit files. **No content here.** |
| `lib.typ` | `knowledge()`, `review_entry()`, `unit_header()`, theme/palette; owns the `<knowledge>` metadata contract. |
| `units/<unit>/NN-*.typ` | one atomic knowledge entry per file; `knowledge()` called exactly once. |
| `units/<unit>/_unit.typ` | includes that unit's entries in pedagogical order. |
| `build/build.py` | CLI: query master + merge db + apply profile -> standalone guide. |
| `build/extract_bodies.py` | parses unit files -> `content_db.json` (id -> raw body text). |
| `build/templates/review_guide.typ` | cover page + TOC template used by generated guides. |
| `build/profiles/*.json` | student profiles (filter schema and semantics in README). |
| `out/`, `content_db.json` | GENERATED artifacts. **Never hand-edit.** |

Data flow: `typst.query(main.typ, "<knowledge>", field="value")` returns a
JSON **string** (parse it with `json.loads`) containing the metadata dicts in
pedagogical (document) order; bodies come from `content_db.json`; the merged,
filtered entries are rendered into `out/<name>.typ` plus build-managed copies
of `lib.typ` and `review_guide.typ` — a self-contained bundle so a plain
`typst compile` works inside `out/`.

## Invariants (violating any of these breaks the system)

1. Never edit generated artifacts (`out/`, `content_db.json`). Change sources
   under `units/` and rebuild.
2. `main.typ` must compile with **zero warnings** at all times.
3. Knowledge ids are the stable API — profiles, handouts, and past exports
   reference them. Renaming an id is a breaking change.
4. One `knowledge()` call per file; unique id; 3-6 lowercase tags; `unit`
   0-5 (0 = Research Design, the foundational unit); `difficulty` one of
   `core` | `standard` | `advanced`.
5. Entry bodies: no unescaped `]` (it would close the content block); no
   literal `#knowledge(` in text or comments; no Markdown `**bold**`
   (Typst bold is single asterisks: `*bold*`).
6. Do not invent AP Psychology content. If CED status is uncertain, set
   `difficulty: "advanced"` and state the uncertainty in the body.
7. The build never mutates source files; it writes only `out/` and
   `content_db.json`.

## Adding an entry (happy path)

1. Create `units/<unit>/<NN>-<slug>.typ`:

```typst
#import "../../lib.typ": knowledge

#knowledge(
  id: "bio-new-topic",
  topic: "Human-Readable Title",
  unit: 1,
  tags: ("tag-one", "tag-two", "tag-three"),
  difficulty: "core",
)[
Body: definitions, key terms (*bold*), examples, common misconceptions,
mnemonics, and exam tips. Comprehensive enough to answer an FRQ.
]
```

2. Add `#include "NN-slug.typ"` to that unit's `_unit.typ` in pedagogical
   order.
3. Run the zero-warnings master check, then `python build/build.py --list`
   to confirm the new id. `content_db.json` refreshes automatically whenever
   it is older than any source file.

## Pitfalls (each of these actually bit this repo)

- **Typst project-root sandbox:** file imports cannot escape the input
  file's folder. This is why generated guides bundle copies of `lib.typ` and
  `review_guide.typ`; never generate a guide that does
  `#import "../lib.typ"` from `out/`.
- **Show-rule argument binding:** `#show: f(args)` does NOT pass the document
  body to the function; `#show: f.with(args)` does. Generated guides emit
  `review_guide.with(...)`.
- **`typst.query` returns a JSON string**, not a Python object — always
  `json.loads` it.
- **Typst dictionaries cannot have integer keys** (`(0: "...")` fails with
  "expected string, found integer"). `UNIT_NAMES` in `lib.typ` is an array
  indexed by unit number for this reason.
- **Typst strings are double-quoted only** — single quotes are a syntax
  error.
- **Verify with `typst.compile_with_warnings`**, never plain
  `typst.compile` — the latter hides warnings.
- **Fonts:** stick to the Typst-embedded "New Computer Modern" family; other
  families fall back silently. Glyph-safe in bodies: em dash, ×, ÷, ≈, ≤, ≥,
  ±. Avoid arrows (→) and checkbox glyphs — use words or ASCII.
- **Metadata contract:** if you add a field to `knowledge()`, update the
  emitted dictionary in `lib.typ` AND `KnowledgeEntry`/`merge_entries` in
  `build/build.py`, or the merge will drop it.

## Definition of done (for any change)

1. Master compiles with zero warnings.
2. `python build/extract_bodies.py --check` passes.
3. At least one guide build with `--compile` reports zero warnings.
4. README, `instruction_to_ai.md`, and this file still describe reality.
