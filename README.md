# AP Psychology Knowledge Base

A modular, queryable knowledge base for AP Psychology, authored in **Typst**,
with a Python build pipeline that extracts arbitrary subsets of the content
and regenerates them as standalone study guides.

You maintain **one master source** and automatically produce smaller guides
filtered by unit, topic, tag, difficulty, or an explicit list of knowledge
IDs — without ever editing a generated file by hand.

> Agent note: `AGENTS.md` is the quick operational reference for AI agents
> (commands, invariants, pitfalls); `instruction_to_ai.md` is the full
> orientation. Keep all three docs in sync.

```
ap-psych/
├── main.typ                  # master document — includes only the unit files
├── lib.typ                   # knowledge(), review_entry(), unit_header(), theme
├── units/
│   ├── 00-research-methods/  # Unit 0 — foundational science practices
│   │   ├── _unit.typ
│   │   └── 01-... .typ       # one file per atomic knowledge entry
│   ├── 01-biological/        # Unit 1 — Biological Bases of Behavior
│   ├── 02-cognition/         # Unit 2 — Cognition
│   ├── 03-development-learning/  # Unit 3 — Development and Learning
│   ├── 04-social-personality/    # Unit 4 — Social Psychology and Personality
│   └── 05-mental-physical-health/# Unit 5 — Mental and Physical Health
├── build/
│   ├── build.py              # CLI: master + profile -> standalone guide
│   ├── extract_bodies.py     # CLI: units/ -> content_db.json
│   ├── profiles/
│   │   └── example_student.json
│   └── templates/
│       └── review_guide.typ  # cover page + TOC template for generated guides
├── content_db.json           # GENERATED — maps knowledge id -> raw body text
├── out/                      # GENERATED — all build artifacts (gitignored)
├── requirements.txt
└── README.md
```

## Setup

```bash
pip install -r requirements.txt   # just: typst
```

That is the only dependency (`typst` = the typst-py bindings, which embed the
Typst compiler). Everything else is the Python standard library.

## The workflow

1. **Content lives in `units/`** — one `.typ` file per atomic knowledge entry;
   each calls `knowledge(...)` exactly once (see below).
2. **`main.typ`** includes every unit's `_unit.typ` (in pedagogical order) and
   applies the shared theme. It must always compile: `python -c "import typst;
   typst.compile('main.typ')"`.
3. **Build a guide:**

   ```bash
   cd build
   python build.py --master ../main.typ \
                   --profile profiles/example_student.json \
                   --output ../out/student_review.typ
   # add --compile to also produce a PDF
   ```

   The build prints the number of entries selected, the breakdown by unit, and
   the output path. It **never mutates source files** — it writes only `out/`
   and (when stale) `content_db.json`.
4. **Compile the generated guide** (if you skipped `--compile`):

   ```bash
   typst compile out/student_review.typ
   ```

### Why `out/` is a self-contained bundle

Typst forbids file imports that escape the project root (the input file's
folder by default). A generated guide that did `#import "../lib.typ"` could
therefore not be compiled with a plain `typst compile`. The build solves this
by copying `lib.typ` and `review_guide.typ` (with its lib import rewritten)
next to the generated `.typ`, so the output folder compiles anywhere with no
extra flags. All three files are build-managed — edit the originals, rebuild.

## Profiles

```json
{
  "name": "Example Student",
  "title": "Units 1-2 Review: Neurons & Memory",
  "ids": ["bio-neuron-structure", "cog-encoding-storage-retrieval"],
  "units": [1, 2],
  "tags": ["memory", "neuron"],
  "difficulty": ["core", "standard"],
  "exclude_ids": ["cog-forgetting"]
}
```

Any field may be omitted; an empty profile (or no `--profile`) produces the
full guide. Filter semantics:

| Field | Type | Meaning |
|---|---|---|
| `name` | string | student name (rendered on the cover; `--student` overrides) |
| `title` | string | guide title (`--title` overrides) |
| `ids` | list of strings | explicit selection of entries by id |
| `units` | list of ints 0-5 | keep entries in these units |
| `tags` | list of strings | keep entries having AT LEAST ONE of these tags |
| `difficulty` | list of strings | `core`, `standard`, and/or `advanced` |
| `exclude_ids` | list of strings | remove these entries at the end |

**Combination rule:** categories combine with AND (an entry must pass every
non-empty category); values *within* a category combine with OR. Unknown ids
in `ids` or `exclude_ids` are a hard error — the build fails loudly listing
the valid ids. The example profile demonstrates every field: it selects
Unit 1-2 entries tagged `memory` or `neuron` at core/standard difficulty,
always includes the two named ids, and drops `cog-forgetting`.

Difficulty conventions used in the content:

- `core` — essential CED must-know material.
- `standard` — full CED depth and detail.
- `advanced` — beyond-CED context or genuinely low-frequency detail (the body
  of every `advanced` entry says so explicitly).

## Adding a new knowledge entry

1. Create `units/<unit-dir>/<next-number>-<slug>.typ`:

   ```typst
   #import "../../lib.typ": knowledge

   #knowledge(
     id: "bio-new-topic",          // unique, stable slug: unit prefix + topic
     topic: "Human-Readable Title",
     unit: 1,                       // 0-5 (0 = research design)
     tags: ("tag-one", "tag-two", "tag-three"),   // 3-6 lowercase tags
     difficulty: "core",
   )[
   The body: definitions, key terms (*bold*), examples, common misconceptions,
   mnemonics, and exam tips. Comprehensive — enough to answer an FRQ.
   ]
   ```

2. Add `#include "NN-slug.typ"` to that unit's `_unit.typ` in pedagogical
   order.
3. Verify: compile the master, then run the build — `content_db.json`
   regenerates automatically when it is older than any source file.

**Authoring rules (enforced or checked by the tooling):**

- `id` must be unique across the whole repo; duplicates fail the extraction.
- The body is a trailing `[...]` content block; never write an unescaped `]`
  inside a body (it would close the block), and never write `#knowledge(` in a
  comment or body. Extraction validates bracket balance and fails loudly.
- Do not invent AP content: if you are unsure whether a topic belongs to the
  current CED, set `difficulty: "advanced"` and note the uncertainty in the
  body.
- Keep `tags` lowercase; hyphens are allowed (`nature-nurture`).

## Content database and extraction backends

`build/extract_bodies.py` walks `units/**/*.typ`, extracts the body of every
`knowledge()` call, and writes `content_db.json` (`{id: body}`).

Backends, in order of preference:

1. **tree-sitter-typst** — used automatically when importable. Note: as of
   writing there is no `tree-sitter-typst` distribution on PyPI, so this
   backend is dormant. When present, its results are cross-checked against the
   scanner and it is only trusted if they agree (mismatch -> scanner wins,
   with a note on stderr).
2. **Bracket-aware scanner (the operative backend)** — a hand-written lexer
   that handles nested `(...)`/`[...]`, double-quoted strings, and `//` and
   `/* */` comments.

**Scanner limitations** (by design, and safe): bodies must be a single
trailing `[...]` block of the `knowledge()` call; genuinely unbalanced
brackets are reported as errors rather than silently truncated; a complete,
well-formed `#knowledge(...)` call inside a comment would still be extracted
(avoid such comments). `--check` runs extraction and validation without
writing anything.

`build.py` calls the extractor automatically when `content_db.json` is
missing or older than any file under `units/`; `--force-extract` overrides.

## Compiling outputs

```bash
python build.py ... --compile          # typst-py compiles the PDF and reports warnings
# or, with the typst CLI:
typst compile out/student_review.typ
```

Every compile in the test pipeline uses `typst.compile_with_warnings`, so a
warning-free build is part of verification. Fonts are the Typst-embedded
"New Computer Modern" family — no system fonts are required.

## Extending the system

- **A `--format html` flag** would reuse the exact pipeline up to rendering:
  query the master, merge with `content_db.json`, filter per profile, then
  emit HTML instead of `.typ` — wrap each body with a small Markdown-ish
  Typst-markup-to-HTML converter (bold/italic/bullets) or run the Typst output
  through a converter. Keep filtering in one place (`select_entries`) so both
  formats stay consistent.
- **New metadata fields** (e.g., `est_minutes` for study-time budgets): add
  the parameter to `knowledge()` in `lib.typ`, include it in the emitted
  metadata dictionary, and add the key to `merge_entries` + `KnowledgeEntry`
  in `build.py`. The query contract (`<knowledge>`, `field="value"`) is
  unchanged.
- **Per-student progress tracking** can layer on top of profiles: the generated
  guide already lists selected ids on its cover checklist.

## Content coverage and provenance

All content derives from the master reference `knowledge file.md` (CED
framework + course materials) in the parent directory; nothing is invented.
Notes:

- Unit 0 ("Research Design / Research Methods") is not a College Board exam
  unit; it is the foundational science-practices unit in the reference
  framework, assessed across Units 1-5 — hence `units/00-research-methods` and
  the `unit: 0` default in `knowledge()`.
- Items the reference marks "taught, though outside the CED" (e.g.,
  chromosomal abnormalities, signal detection theory, scapegoating, named
  emotion theories) are included as clearly marked context with
  `difficulty: "advanced"` or an in-body note.
- Items once listed as excluded but actually present in the current CED
  (flashbulb memory, content validity, intellectual disability, giftedness,
  epigenetics, Wundt, linguistic determinism/relativism, attraction factors,
  social scripts, social desirability, descriptive statistics, mechanoreceptors/
  thermoreceptors, social identity, self-awareness) are first-class entries.
- CED topic numbering follows the reference mapping (Unit 1 = topics 1.1-1.6,
  Unit 2 = 2.1-2.8, Unit 3 = 3.1-3.9, Unit 4 = 4.1-4.7, Unit 5 = 5.1-5.5).
