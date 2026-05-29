---
name: folder-map
description: Map a folder of scattered files (notes, backups, recovered AI work, a messy project dir) read-only — scan it, cluster related files with visible evidence and confidence, and explain what's there without moving, renaming, or deleting anything. Trigger when the user asks to "map my folder," "make sense of this backup," "what's in this folder," "help me sort/organize these notes" (offer the read-only map first), or points at a directory they want to understand before reorganizing.
---

# folder-map

This is the folder-map skill. When a user wants to understand a folder full of scattered files — a backup drive, a notes pile, recovered AI work, an old project dir they've lost the thread on — this file tells you how to run the read-only scanning engine in `scripts/` and how to translate its results into user-facing voice.

**The promise this skill makes to the user:** *help them see their existing work clearly before they decide what to do with it.* Visibility before action. It maps their mess; it does not translate their mess into someone else's productivity system, and it never touches a single file.

**The hybrid pattern:**
- *You* (the agent) own intent parsing, judgment calls (which folder, when to offer this), and voice — every sentence the user reads, you wrote.
- *The scripts* in `scripts/` own deterministic mechanics. They walk the folder read-only and return a single JSON status object on stdout describing what happened, plus a written report (`report.md` + `report.html`) and a structured `clusters.json`.
- The user sees only your voice. Script JSON, progress chatter, and the raw report files are your INPUTS, never the user's output (until you choose to hand them the HTML to open or screenshot).

## What's available so far

- **`scan`** — walk a folder read-only, emit an inventory.
- **`cluster`** — group the inventory into clusters with names, confidence, and evidence.
- **`report`** — render a readable report (`report.md` canonical + `report.html` presentable).

Not yet shipped: same-name twin comparison view, PARA/GTD/Obsidian-MOC projection views, custom/override layouts, and any ingest into a knowledge store. If the user asks for those, say so plainly — don't improvise. This version maps and advises; it does not reorganize.

## When this skill runs

Read for intent, not exact wording. Examples that match:

- "Can you make sense of this backup folder?"
- "What's even in `~/Downloads/old-stuff`?"
- "I have a folder of notes I've lost track of — help."
- "Organize these files for me" → **offer the read-only map first.** This skill's whole stance is *advisor, not auto-organizer*. Don't start moving files; map them, show what's there, and let the user decide.

## Operating principle — agent voice is the only UX surface

Every sentence the user reads, you wrote. Script output and the raw report files never reach the user as substrate. Capture the JSON, parse it, speak about it.

Two specific rules:
- **Don't echo script JSON or progress lines.** Parse them and narrate.
- **Don't run your own `ls`/`find`/`cat` to "explore" the folder.** The scan already inventoried it; ad-hoc filesystem pokes both leak substrate and risk reading things the tiered scan deliberately bounded. Work from `clusters.json`.

## How to run (three stages, in sequence)

Pick a working directory **outside** the folder being scanned, and pass the same `--out` to all three stages. A temp dir is fine (e.g. `~/.cache/folder-map/run` or `mktemp -d`). Never write output inside the scanned folder.

```
# 1. Walk the folder (read-only) -> <out>/inventory.jsonl
python3 ~/.claude/skills/folder-map/scripts/scan.py "<FOLDER>" --out "<OUT>"

# 2. Cluster the inventory -> <out>/clusters.json
python3 ~/.claude/skills/folder-map/scripts/cluster.py --out "<OUT>"

# 3. Render the report -> <out>/report.md + <out>/report.html
python3 ~/.claude/skills/folder-map/scripts/report.py "<FOLDER>" --out "<OUT>"
```

Each stage prints exactly one line of JSON to stdout (capture it). Add `--redact` to the **report** stage only when the user intends to share or screenshot the report — it scrubs their username/home path from the rendered output. Default is off (real paths, for their own eyes).

### Result statuses (every stage)

| Status | What it means | What to do |
| --- | --- | --- |
| `ok` (scan) | Inventory written. JSON has `files_seen`, `sampled`, `metadata_only`, `skipped`, `project_subtrees`. | Move straight to cluster. Optionally tell the user how many files you looked at. |
| `ok` (cluster) | Clusters written. JSON has `cluster_count`, `confidence_distribution`, `cross_bucket_twin_count`, `unsorted_loose_count`. | Move straight to report. |
| `ok` (report) | `report.md` + `report.html` written. JSON has their paths, `redacted`, `overview_file`. | Narrate from `clusters.json` (below), then offer the HTML to open/screenshot. |
| `error` · `target_not_found` | The folder path doesn't exist. | "I can't find a folder at `<path>` — double-check the path?" |
| `error` · `inventory_missing` | cluster ran before scan. | Run scan first (orchestration slip on your side — just do it). |
| `error` · `clusters_missing` | report ran before cluster. | Run cluster first. |
| other / argparse error | Unexpected. | Read the message, translate to plain language, suggest a retry; don't quote raw tracebacks. |

## Narrating the result (the warm layer)

After report `ok`, read `clusters.json` — that closed-world file is your **entire** input for narration; everything in it is already decided by the deterministic engine. Speak in a calm advisor voice:

- **Lead with what's clearly there:** the High/Medium clusters by name and file count.
- **Surface what looks forgotten:** small + old-modtime clusters.
- **Flag duplicates to reconcile:** cross-bucket twins, if any.
- **Bind your prose to the `confidence` field.** Never describe a `Low` cluster as certain. Confidence is *evidence strength for the name*, not importance — say so if you mention it. A Low cluster may still hold something valuable.
- **Close advisory, not directive:** suggest what's worth reviewing first; make clear nothing was changed and any reorganization is the user's call.

Then hand off the artifact: "I've written a full report you can open — `report.html` (formatted) or `report.md` (plain)."

## How to talk to the user

1. **Don't quote raw JSON, progress, or tracebacks.** Translate.
2. **Prefer the words the user thinks in.** "Folder" over "directory." "Your files" over "the corpus." "Groups of related files" over "clusters" if they seem unfamiliar with the term.
3. **Name things concretely.** Real folder and file names beat vague counts.
4. **Always suggest the next move.** Never a dead-end.
5. **Stay calm and read-only in tone.** This tool's reassurance — "nothing was touched" — is part of its value. Don't undercut it by sounding like you're about to reorganize their life.

## Things this skill won't do (hard, read-only)

- **Move, rename, delete, or rewrite any file** in the scanned folder. Ever. This is the core promise; the scripts only `os.walk` and read bounded byte ranges.
- **Create symlinks** in the scanned folder.
- **Write anything inside the scanned folder** — all artifacts go to the `--out` dir, which must be outside it.
- **Ingest the overview file as input.** If a top-level index/taxonomy file is present, it's surfaced for *awareness only*; it never steers clustering.
- **Reorganize on the user's behalf.** Advisor, not auto-organizer. If they want PARA/GTD/etc., name that it's not yet built and keep the map primary.
- **Improvise unshipped workflows.** Say plainly what isn't here.

## Where this is headed

Each new capability gets its own stage (or flag) in `scripts/` and its own row in the status table. The pattern stays identical: scripts return JSON + artifacts, the agent translates to voice, the user reads the agent. Next candidates: same-name twin side-by-side comparison, projection views (PARA/GTD/Obsidian-MOC) over the same `clusters.json`, and optional ingest into a knowledge store.
