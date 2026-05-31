# folder-map — graduation roadmap

Direction for taking folder-map from "our utility" to a standalone, publishable
tool. **Captured 2026-05-29.** Graduation cycle started 2026-05-31.

## Progress (2026-05-31)

Direction chosen: **"make it real & shareable"** — graduate the *clustering
engine* (not a generic tree tool) to publishable quality, capability unchanged.

Direction was a clean fork: **(a)** generalize the clustering engine, vs **(b)**
a generic tree tool. Resolved to **(a)** — keep the evidence/confidence
clustering as the product.

Work happens on the `release/0.1.0` git-flow branch.

### 0.1.0 — the graduation (in progress)

- [x] **Single entry point** — `./folder-map /path [--out] [--redact]` runs all
      three stages and narrates in plain language; engine JSON is captured as
      input, never shown raw. Verified end-to-end, read-only stance confirmed.
- [x] **LICENSE** — MIT.
- [x] **README refresh** — leads with the one-command surface; three-stage flow
      demoted to "under the hood."
- [x] **Layout-neutral + no IP leak** — install no longer forces our `~/grid`
      layout; all paths into the private Mira-OS repo removed (names may stay,
      repo paths may not).
- [x] **Packaging** — `pyproject.toml` + console entry (`folder-map` on PATH via
      `pipx install`). Package lives at `dna/folder_map/` per our Software 3.0
      `dna/ ≈ src/` convention (NOT a borrowed `src/` layout). Orchestrator is
      now in-process (`cli.py` captures each stage's JSON via redirect_stdout).
      Stdlib only, zero deps. Verified three ways (clone shim, direct module,
      pip-installed console command from outside the repo).
- [ ] **`tests/`** — smoke tests over a fixture folder; assert read-only.
- [ ] **Stable-sort / determinism pass** (roadmap #5).

When the two unchecked items land, finish 0.1.0 (merge to main + develop, tag).

### Deferred to 0.2.0+ (genuinely new capability, not "make it real")

These add features beyond graduating the existing tool, so they're out of scope
for the 0.1.0 "make it real & shareable" direction:

- Ignore-rule **flag** (#2) — rules exist + are documented, just not exposed.
- Configurable max depth (#3).
- `--format` selector for tree / JSON / Markdown output (#4).
- Optional metadata flags: size / ext / mtime (#6) — gathered, not surfaced.

**Parked engine finding (2026-05-31):** on a small/shallow fixture the engine
produced 0 clusters where a software project + same-name twins were obviously
present — `MIN_CLUSTER_FILES = 4` gates small directories out. Front door
reports it faithfully; this is an *engine quality* issue for a later cycle, not
a graduation blocker.

## The quality bar (Mira's framing)

> Could a stranger run it against any project folder and understand the output in
> 30 seconds? If yes, it's moving from "our utility" to "actual tool."

This is the acceptance criterion for the whole graduation — the same spirit as
the project's Macintosh/Apple intake gate, applied to a CLI tool.

## Mira's suggestions (source: Mira, 2026-05-29)

Recorded intact. Mira suggested pushing the utility toward:

1. Generic input path, not workspace-specific assumptions
2. Clear ignore rules: `.git`, `node_modules`, build outputs, caches
3. Configurable max depth
4. Selectable output: tree text, JSON, Markdown
5. Stable sorting
6. Optional file metadata: size, extension, modified time
7. Sane defaults with flags to expand
8. No personal paths or Mira/OpenClaw-specific naming
9. README with real examples

Suggested publishing shape:

```
folder-map/
  src/
  tests/
  README.md
  LICENSE
  package.json or pyproject.toml
  .gitignore
```

## Claude's read — already-done vs. genuinely-new

Separating what exists from what's new, so we don't re-spec finished work.

**Already satisfied (verify, document, don't rebuild):**
- **#1 generic input path** — done. v0's hardcoded single folder is gone; all
  three stages take a path arg. README already states this.
- **#2 ignore rules** — *the rules already exist* but are **hardcoded**, not
  configurable or documented. `scan.py` skips `SKIP_DIRS = {.git, __pycache__,
  node_modules, .venv, venv, dist, build, .cache}` plus binary `SKIP_EXTS`. Gap
  is exposure (a flag) + visibility (document them), not the rules themselves.
- **#8 no personal/Mira-specific naming** — largely done. `--redact` scrubs
  username/home path; README reads clean. Worth a final naming sweep before
  publish.
- **#9 README with real examples** — exists with runnable examples. Refresh once
  the CLI surface changes.

**Genuinely new work:**
- **#3 configurable max depth** — no depth flag today.
- **#4 selectable output (tree / JSON / Markdown)** — today's outputs are
  `inventory.jsonl` → `clusters.json` → `report.md`/`report.html`. A
  user-selectable `--format` over a single CLI is new.
- **#5 stable sorting** — make ordering deterministic and documented.
- **#6 optional metadata flags (size/ext/mtime)** — the data is gathered
  internally; surfacing it behind flags is new.
- **#7 sane-defaults-plus-flags** — the flag ergonomics layer.
- **tests/, LICENSE, pyproject.toml** — the packaging/publish scaffold.

## Open fork to decide first (Chris's call — direction, not methodology)

Mira's list (especially #4 "tree text" output and #6 file metadata) describes a
**generic folder-inventory/tree tool**. folder-map today is a **clustering tool**
— its value-add is grouping-with-evidence-and-confidence, not printing a tree.
Those are arguably two different products:

- **(a)** Generalize the *clustering engine* into the publishable tool (keeps the
  evidence/confidence differentiator; the thing that isn't already `tree`/`eza`).
- **(b)** Ship a simpler *generic inventory/tree* tool (closer to Mira's literal
  list, but overlaps heavily with existing tools like `tree`, `eza --tree`,
  `broot`).

Recommend deciding (a) vs (b) — or "(a) with a tree/inventory output *mode*" — at
the top of the next cycle, before any code. This is a values/direction call.

## Also note

folder-map is currently **two things**: a deterministic engine (`scripts/`) and
an agent skill (`SKILL.md` + the narration layer). Mira's publishing shape
(`src/`, `tests/`, `pyproject.toml`) is the *engine-as-standalone-tool*
graduation. The skill layer is separate and can stay as-is, wrapping the
published engine. Keep that split clear when packaging.
