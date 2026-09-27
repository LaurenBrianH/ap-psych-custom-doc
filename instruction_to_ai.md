# AI Agent Brief — AP Psychology Knowledge Base

This document is a complete orientation for any AI agent (or new maintainer)
working in this repository. Read it fully before touching anything. For a
quick operational reference (commands, invariants, pitfalls), see `AGENTS.md`;
for the build workflow and profile schema, see `README.md`.

## 1. What this repository is

A **modular, queryable knowledge base for AP Psychology**, authored in Typst,
with a Python build pipeline. The teacher maintains **one master source**
(`main.typ` + `units/`) and the pipeline (`build/build.py`) automatically
produces smaller, standalone study guides filtered by unit, topic, tag,
difficulty, or explicit knowledge IDs — for personalized student review.

Content provenance: every entry derives from the master reference
`../knowledge file.md` (CED framework + course materials). **Do not invent
AP Psychology content.** If unsure whether something belongs to the current
CED, mark the entry `difficulty: "advanced"` and note the uncertainty in its
body.

## 2. Architecture in one paragraph

Every atomic fact-set lives in its own `.typ` file under `units/<unit>/` and
calls `knowledge(id, topic, unit, tags, difficulty, body)` exactly once
(defined in `lib.typ`). `knowledge()` emits a hidden `#metadata(...)`
dictionary labelled `<knowledge>` (all fields except the body) and renders the
body. `main.typ` includes every unit's `_unit.typ` under a shared theme and is
the single compile/query target. `build/extract_bodies.py` parses the unit
files into `content_db.json` (id -> raw body text). `build/build.py` runs
`typst.query(main.typ, "<knowledge>", field="value")`, merges that metadata
with `content_db.json`, applies a JSON profile's filters, and writes a
standalone `.typ` review guide (plus build-managed copies of `lib.typ` and
`build/templates/review_guide.typ`) into `out/` so it compiles anywhere with
a plain `typst compile`.

## 3. Hard invariants — never violate these

1. **Never edit generated files.** Everything in `out/` and
   `content_db.json` is generated. To change content, edit the `units/`
   source and rebuild.
2. **The master must always compile.** After any edit, verify:
   `python -c "import typst; typst.compile_with_warnings('main.typ')"` —
   zero warnings is the standard.
3. **IDs are stable slugs** (`bio-neuron-structure`, `cog-forgetting`, ...).
   They are the API: profiles, handouts, and past exports reference them.
   Renaming an ID is a breaking change — coordinate it.
4. **Bodies must not contain an unescaped `]`** (it would close the content
   block) and must not contain the literal `#knowledge(` in text or comments.
   The extractor validates bracket balance and fails loudly; do not bypass it.
5. **`main.typ` contains no content** — only the theme application and
   `#include` of the unit files.
6. **Every entry calls `knowledge()` exactly once**, with a unique `id`, 3-6
   lowercase `tags`, a correct `unit` (0-5), and one of
   `core` / `standard` / `advanced` difficulty.
7. **The build never mutates sources.** It writes only `out/` and
   `content_db.json`.

## 4. The metadata contract (what makes querying work)

In `lib.typ`, `knowledge()` emits:

```typst
#metadata((id: id, topic: topic, unit: unit, tags: tags, difficulty: difficulty)) <knowledge>
```

The build queries with `typst.query(master, "<knowledge>", field="value")`,
which returns a **JSON-encoded string** — parse it with `json.loads` before
use. Field names in the metadata dictionary must stay in sync with
`build/build.py` (`merge_entries` / `KnowledgeEntry`). If you add a field to
`knowledge()`, update: the emitted dictionary, `KnowledgeEntry`,
`merge_entries`, and (optionally) the review-guide rendering.

## 5. Recipes

### Add a knowledge entry
1. `units/<unit>/<NN>-<slug>.typ` with the `#import "../../lib.typ": knowledge`
   line and one `#knowledge(...)` call (see README "Adding a new knowledge
   entry").
2. Add the `#include` line to that unit's `_unit.typ` in pedagogical order.
3. Verify: compile the master (no warnings), then run
   `python build/build.py --master ../main.typ --list` from `build/` —
   the new id must appear. `content_db.json` refreshes automatically.

### Produce a custom handout for a student
1. Write a profile JSON (`build/profiles/<student>.json`) — fields and
   semantics are documented in the README (categories AND, values OR,
   `exclude_ids` last). Example:

   ```json
   {
     "name": "Ana",
     "title": "FRQ Skills Bootcamp",
     "units": [0],
     "difficulty": ["core", "standard"],
     "exclude_ids": []
   }
   ```

2. Build and compile:

   ```bash
   cd build
   python build.py --master ../main.typ --profile profiles/ana.json \
                   --output ../out/ana_review.typ --compile
   ```

3. Confirm the summary line ("Selected N of 79 knowledge entries") matches the
   intent, and that the compile reports zero warnings. Deliver
   `out/ana_review.typ` (+ the `.pdf` if `--compile` was used). The PDF is
   self-sufficient; the `.typ` bundle in `out/` also compiles standalone.

### Extend the content (new tags, re-tagging)
Edit the `tags=(...)` of the relevant entries, then rebuild — tags are
metadata, so no db regeneration is strictly required, but rebuild anyway so
`content_db.json` mtimes stay coherent. Use lowercase tags; reuse existing
tags where possible (see `--list` output) so cross-unit filtering stays
useful.

### Diagnostics
- `python build/extract_bodies.py --check` — validate all bodies without
  writing.
- `python build/build.py --list` — full entry table (id, unit, difficulty,
  topic).
- Delete `content_db.json` (or `--force-extract`) if metadata and db seem out
  of sync.

## 6. Pitfalls (learned the hard way in this repo)

- **Typst project-root sandbox:** imports cannot escape the input file's
  folder. This is why generated guides get copies of `lib.typ` and
  `review_guide.typ` in `out/` (the template's lib import is rewritten by the
  build). Never generate a guide that does `#import "../lib.typ"`.
- **Show-rule argument binding:** `#show: tpl(a: 1)` does NOT pass the
  document body as an argument in current Typst; `#show: tpl.with(a: 1)` does.
  Generated guides therefore emit `review_guide.with(...)`.
- **`typst.query` returns a JSON string**, not a Python object — `json.loads`
  it. With `field="value"` you get the metadata dicts in document
  (pedagogical) order.
- **Typst dictionaries cannot have integer keys** (`(0: "...")` fails with
  "expected string, found integer"). Use arrays indexed by unit number, as
  `UNIT_NAMES` in `lib.typ` does.
- **Typst strings are double-quoted only.** Single quotes are a syntax error.
- **Typst bold is single asterisks** (`*bold*`); Markdown `**bold**` produces
  "no text within stars" warnings.
- **Fonts:** stick to the Typst-embedded "New Computer Modern" family; other
  fonts silently fall back (typst-py does not surface font warnings except via
  `compile_with_warnings`, and missing glyphs can render as tofu).
- **Unicode in bodies:** em dashes, ×, ÷, ≈, ≤, ≥, ± are fine. Avoid arrows
  (→) and checkbox glyphs — use words or ASCII.
- **Warnings visibility:** use `typst.compile_with_warnings(...)` for all
  verification compiles; plain `typst.compile` hides warnings.

## 7. File-by-file responsibilities

| Path | Role | May you edit it? |
|---|---|---|
| `main.typ` | master document; includes unit files | structure only, no content |
| `lib.typ` | `knowledge()`, `review_entry()`, `unit_header()`, theme, palette | yes — carefully, keep the metadata contract |
| `units/**` | the content (one entry per file) + `_unit.typ` include lists | yes — this is where content work happens |
| `build/build.py` | the CLI pipeline | yes |
| `build/extract_bodies.py` | body extraction to `content_db.json` | yes |
| `build/templates/review_guide.typ` | cover + TOC template | yes |
| `build/profiles/*.json` | student profiles | add freely |
| `out/`, `content_db.json` | generated artifacts | NEVER by hand |
| `README.md`, `instruction_to_ai.md` | documentation | keep in sync with reality |

## 8. Definition of done for any change

1. Master compiles with **zero warnings**.
2. `content_db.json` is fresh and validated (`--check` passes).
3. A build with a profile (or the default full guide) **compiles cleanly**
   (`--compile` reports no warnings).
4. Documentation (README / this file) still describes the truth.
