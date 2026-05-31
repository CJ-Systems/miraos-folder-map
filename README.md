# folder-map

A local, **read-only** map of a folder full of scattered files — notes, backups,
recovered AI work, a project directory you've lost the thread on. It scans the
folder, preserves original paths, groups related files into clusters with
*visible evidence and confidence*, explains why it grouped them, and suggests
what's worth reviewing — **without moving, renaming, deleting, or modifying any
file.**

The stance is **organizational advisor, not automatic organizer**: visibility
before action. It maps your mess; it doesn't translate your mess into someone
else's productivity system.

This project is the generalization of the Mira-OS read-only recovery-map spike
(v0 was hardcoded to one folder for a build-in-public artifact). It was promoted
out of that spike into its own canonical home at `~/dna/folder-map`. The original
v0 spec and philosophy live in the Mira-OS repo at
`docs/briefs/read-only-recovery-map-prototype.md`, with a provenance breadcrumb
at `spikes/recovery-map/README.md`.

## Layout

```
folder-map/
├── folder-map          # the command — one entry point over all three stages
├── SKILL.md            # how the agent runs + narrates this (the UX layer)
└── scripts/
    ├── scan.py         # read-only walker             -> <out>/inventory.jsonl
    ├── cluster.py      # directory-primary heuristics  -> <out>/clusters.json
    └── report.py       # clusters.json -> <out>/report.md + report.html
```

## Install

**The utility (primary).** End-user installs target `~/grid/tools/` directly —
copy (or, once published, clone) this project there:

```bash
cp -r folder-map ~/grid/tools/folder-map
```

For the dev setup it's a symlink instead, so edits to the canonical source at
`~/dna/folder-map` go live immediately:

```bash
ln -s ~/dna/folder-map ~/grid/tools/folder-map
```

The Python is stdlib-only and runs anywhere `python3` does — no packages to
install.

**The Agent Skill wrapper (optional).** `SKILL.md` makes an agent the interactive
front-end (the "agent IS the UI" pattern). It's optional — the engine runs fine
without it. To enable it, expose this project at your harness's skill location
(the dev setup uses a symlink):

```bash
ln -s ~/dna/folder-map ~/.claude/skills/folder-map
```

`SKILL.md` is the cross-vendor Agent Skills standard; only the discovery location
varies per harness.

## Run it

One command maps the folder and writes the report:

```bash
./folder-map /path/to/folder              # writes ./folder-map-out/report.html
./folder-map /path/to/folder --redact     # scrub your home path, for sharing
./folder-map /path/to/folder --out ~/maps/project   # choose where output goes
# then open folder-map-out/report.html
```

It runs the three stages in order and narrates the run in plain language —
nothing in the scanned folder is touched. Example:

```
Mapping (read-only): /home/you/messy-folder
  1/3  Scanning files…
  2/3  Clustering related files…
  3/3  Writing the report…

Mapped  messy-folder/  (read-only — nothing in it was changed)
  428 files seen · 12 clusters · 3 high-confidence, 6 medium, 3 low
  Report: folder-map-out/report.html
```

### Under the hood (running the stages by hand)

The `folder-map` command is a thin orchestrator over three independent stages.
You can run them yourself if you want to inspect the intermediate
`inventory.jsonl` / `clusters.json`, or wire a stage into something else:

```bash
OUT=folder-map-out
python3 scripts/scan.py    /path/to/folder --out "$OUT"
python3 scripts/cluster.py                 --out "$OUT"
python3 scripts/report.py  /path/to/folder --out "$OUT"   # add --redact to share
```

Each stage prints one JSON status line to stdout; progress goes to stderr. The
`folder-map` command captures those status lines and translates them into the
plain-language recap above.

## Safety

The scanned folder is strictly read-only: the scripts only `os.walk` and read
bounded byte ranges. They never write, move, rename, delete, or symlink inside
it. All artifacts go to the `--out` directory, which must live outside the
scanned folder. Paths are shown as-found; pass `--redact` to the report stage to
scrub your username/home path when sharing or screenshotting.

## Deferred

Same-name twin comparison, PARA/GTD/Obsidian-MOC projection views,
custom/override layouts, and ingest into a knowledge store. `clusters.json` is
kept structured so those can be built over the same output later.
