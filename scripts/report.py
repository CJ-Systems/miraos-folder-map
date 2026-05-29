#!/usr/bin/env python3
"""report.py — render clusters.json into report.md (canonical) + report.html.

Sections, in order:
  1. Header overview-file callout (surfaces a top-level index/overview/taxonomy
     file if present, for awareness only; never ingested as clustering input).
  2. Path Map (directory tree as-found: counts, sizes, modtimes).
  3. Project Clusters (name, confidence + derivation, evidence, reps, loose).
  4. Narrative Wrap (TEMPLATE — deterministic; every sentence traces to a
     number in clusters.json).
  5. Future-Projections stub (one note).

Deterministic. No LLM calls. Python stdlib only (string templating).

Privacy: paths are shown as-found by default (it's your folder, your eyes).
Pass --redact to scrub the local username / home path from the rendered output
when you intend to share or screenshot the report.

Output contract: a single JSON status object on stdout (the agent's input).
"""

import argparse
import getpass
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Top-level files that read like an index / overview / taxonomy of the folder.
# Surfaced for awareness only — never used as clustering input.
TAXONOMY_PATTERNS = (
    re.compile(r"top-level", re.I),
    re.compile(r"taxonomy", re.I),
    re.compile(r"^_?index\.(md|markdown|txt)$", re.I),
    re.compile(r"table.?of.?contents", re.I),
    re.compile(r"\bMOC\b"),
    re.compile(r"^map\.(md|markdown)$", re.I),
    re.compile(r"^readme", re.I),
)


def redact(text):
    """Scrub the local username / home path from rendered output.

    OFF by default — the report shows real paths because it is your folder for
    your eyes. Turn this on (--redact) when you intend to share or screenshot
    the report: some scanned files (e.g. tool session dirs) embed the absolute
    home path in their names, so the username can leak into cluster names,
    paths, and file lists. Source data in clusters.json is left intact; only
    the presentation is sanitized. Placeholder avoids angle brackets so it is
    safe in both markdown and HTML.
    """
    user = getpass.getuser()
    home = os.path.expanduser("~")
    text = text.replace(home, "~")
    if user:
        text = text.replace(user, "[user]")
    return text


def fmt_bytes(n):
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024


def fmt_date(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def read_taxonomy_callout(target: Path):
    """Scan the target's top-level files (non-recursive) for an index/overview
    file. Returns (name, first ~200 chars) or (None, None)."""
    try:
        entries = sorted(
            (p for p in target.iterdir() if p.is_file()),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return None, None
    for p in entries:
        if any(pat.search(p.name) for pat in TAXONOMY_PATTERNS):
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:200]
            except OSError:
                head = ""
            return p.name, head
    return None, None


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def render_md(data, source_label, overview_name, overview_head):
    s = data["summary"]
    L = []
    L.append("# Folder Map — Read-Only Report")
    L.append("")
    L.append(f"_Generated: {data['generated_at']}_  ")
    L.append(f"_Source (read-only, untouched): `{source_label}`_")
    L.append("")
    L.append("> No files were moved, renamed, deleted, or modified. "
             "This is a map of your existing work, not a reorganization of it.")
    L.append("")

    # 1. Header overview-file callout
    L.append("## Noticed: top-level overview file")
    L.append("")
    if overview_name:
        L.append(f"A top-level index / overview file is present: "
                 f"**`{overview_name}`**. It is surfaced here for awareness "
                 f"only and was **not** used as clustering input.")
        L.append("")
        L.append("First ~200 chars:")
        L.append("")
        L.append("```")
        L.append(overview_head.strip())
        L.append("```")
    else:
        L.append("_No top-level index or overview file detected._")
    L.append("")

    # 2. Path Map
    L.append("## Path Map (as-found — counts, sizes, modtimes)")
    L.append("")
    L.append(f"- Files inventoried: **{s['total_files_inventoried']}**")
    L.append(f"- Clusters detected: **{s['cluster_count']}**")
    L.append(f"- Confidence: {fmt_conf_dist(s['confidence_distribution'])}")
    L.append(f"- Cross-bucket twins: **{s['cross_bucket_twin_count']}**")
    L.append(f"- Unsorted loose files: **{s['unsorted_loose_count']}**")
    L.append(f"- Software-project subtrees (metadata-only): "
             f"**{s['software_project_count']}**")
    L.append("")
    if data.get("preservation_buckets"):
        L.append("### Low-confidence containers (numeric-named folders)")
        L.append("")
        L.append("| Folder | Files | Meaningful children |")
        L.append("|---|---:|---|")
        for b in data["preservation_buckets"]:
            kids = ", ".join(b["child_clusters"]) or "—"
            L.append(f"| `{b['name']}/` | {b['file_count']} | {kids} |")
        L.append("")
        L.append("> Numeric- or generic-named top-level folders carry little "
                 "semantic meaning on their own — the meaning lives in their "
                 "children.")
        L.append("")

    # 3. Project Clusters
    L.append("## Project Clusters")
    L.append("")
    L.append("> Confidence describes evidence strength, not importance. A "
             "low-confidence cluster may still hold valuable work — it just "
             "means the scanner has weak evidence for naming it.")
    L.append("")
    for c in data["clusters"]:
        L.append(f"### {c['name']}  ·  _{c['confidence']}_")
        L.append("")
        L.append(f"- **Path:** `{c['key_path']}`")
        L.append(f"- **Name source:** {c['name_source']}")
        L.append(f"- **Confidence:** {c['confidence']} — "
                 f"{c['confidence_reason']}")
        L.append(f"- **Files:** {c['file_count']}  ·  "
                 f"**Size:** {fmt_bytes(c['total_bytes'])}")
        if c.get("mtime_min"):
            L.append(f"- **Modified:** {fmt_date(c['mtime_min'])} → "
                     f"{fmt_date(c['mtime_max'])} "
                     f"(~{c.get('mtime_span_days', 0)}d span)")
        if c.get("dominant_exts"):
            ex = ", ".join(f"`{k or '∅'}`×{v}"
                           for k, v in c["dominant_exts"].items())
            L.append(f"- **Top extensions:** {ex}")
        if c.get("is_software_project"):
            L.append("- **Software project:** yes (metadata-only; source "
                     "contents not sampled)")
        if c.get("cross_bucket_twin"):
            t = c["cross_bucket_twin"]
            L.append(f"- **Cross-bucket twin:** `{t['name']}` in buckets "
                     f"{t['buckets']} — {t['note']}")
        if c["signals"]:
            L.append("- **Evidence:**")
            for sig in c["signals"]:
                L.append(f"    - {sig}")
        if c["representative_files"]:
            L.append("- **Representative files:**")
            for f in c["representative_files"]:
                L.append(f"    - `{f}`")
        if c["loose_files_attached"]:
            L.append(f"- **Loose files attached here "
                     f"({len(c['loose_files_attached'])}):**")
            for f in c["loose_files_attached"][:10]:
                L.append(f"    - `{f}`")
        L.append("")

    if data["cross_bucket_twins"]:
        L.append("### Cross-bucket twins")
        L.append("")
        for t in data["cross_bucket_twins"]:
            L.append(f"- **`{t['name']}`** appears in buckets {t['buckets']} "
                     f"— possible same project / possible diverged copies.")
        L.append("")

    ub = data["unsorted_loose_files"]
    L.append(f"### Unsorted / loose files ({ub['count']})")
    L.append("")
    if ub["files"]:
        for f in ub["files"][:25]:
            L.append(f"- `{f}`")
        if ub["count"] > 25:
            L.append(f"- _…and {ub['count'] - 25} more._")
    else:
        L.append("_None._")
    L.append("")

    # 4. Narrative Wrap (template)
    L.append("## Narrative Wrap")
    L.append("")
    L.extend(narrative_lines(data))
    L.append("")

    # 5. Future Projections stub
    L.append("## Future Projections (stub)")
    L.append("")
    L.append("Later versions can project these clusters into PARA, GTD, "
             "Obsidian/MOC, or a custom layout. This report keeps the source "
             "map and evidence primary. No machinery here.")
    L.append("")
    return "\n".join(L)


def fmt_conf_dist(dist):
    order = ("High", "Medium", "Low")
    return ", ".join(f"{k} {dist.get(k, 0)}" for k in order)


def narrative_lines(data):
    """Deterministic template wrap — every sentence traces to a number."""
    s = data["summary"]
    clusters = data["clusters"]
    L = []
    L.append(f"Scanned **{s['total_files_inventoried']}** files and grouped "
             f"them into **{s['cluster_count']}** clusters "
             f"({fmt_conf_dist(s['confidence_distribution'])} confidence).")

    high = [c for c in clusters if c["confidence"] == "High"]
    med = [c for c in clusters if c["confidence"] == "Medium"]
    strongest = (high + med)[:3]
    if strongest:
        names = ", ".join(f"**{c['name']}** ({c['file_count']} files)"
                          for c in strongest)
        L.append(f"The best-evidenced clusters are {names}.")

    # possibly forgotten: oldest mtime + small + low confidence
    candidates = [c for c in clusters
                  if c.get("mtime_max") and c["file_count"] <= 10]
    candidates.sort(key=lambda c: c.get("mtime_max") or 0)
    if candidates:
        c = candidates[0]
        L.append(f"Worth a look: **{c['name']}** is small "
                 f"({c['file_count']} files) and last touched "
                 f"{fmt_date(c['mtime_max'])} — it may be easy to miss.")

    if s["cross_bucket_twin_count"]:
        names = ", ".join(f"`{t['name']}`"
                          for t in data["cross_bucket_twins"])
        L.append(f"**{s['cross_bucket_twin_count']}** cross-bucket twin(s) "
                 f"appear across more than one folder ({names}); these are "
                 f"possible duplicates or diverged copies worth reconciling.")

    if s["unsorted_loose_count"]:
        L.append(f"**{s['unsorted_loose_count']}** loose file(s) did not "
                 f"attach to any cluster and sit in the unsorted bucket.")

    L.append("Suggested next move (advisory only): review the cross-bucket "
             "twins first, then the low-confidence containers, before "
             "deciding any reorganization. Nothing here has been changed.")
    return L


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Folder Map — Read-Only Report</title>
<style>
  :root {{
    color-scheme: dark;
    --bg: #070604;
    --panel: #14100b;
    --panel-soft: #1d160e;
    --panel-raised: #19130d;
    --ink: #f6efe4;
    --muted: #b8aa99;
    --line: #3f2d17;
    --line-strong: #75501f;
    --amber: #ff9f1a;
    --amber-bright: #ffc15d;
    --amber-soft: rgba(255, 159, 26, .14);
    --green: #4ade80;
    --green-soft: rgba(74, 222, 128, .14);
    --blue: #a78bfa;
    --blue-soft: rgba(167, 139, 250, .14);
    --red: #fb7185;
    --red-soft: rgba(251, 113, 133, .14);
    --gray-soft: rgba(255, 255, 255, .07);
    --violet: #a78bfa;
    --shadow: 0 18px 48px rgba(0, 0, 0, .42);
    --glow: 0 0 0 1px rgba(255, 159, 26, .18),
      0 16px 38px rgba(0, 0, 0, .36);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    color: var(--ink);
    background:
      linear-gradient(180deg, #140d06 0, var(--bg) 420px);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, sans-serif;
  }}
  .page {{
    width: min(1120px, calc(100% - 32px));
    margin: 0 auto;
    padding: 28px 0 48px;
  }}
  .hero {{
    padding: 28px 0 22px;
    border-bottom: 1px solid var(--line);
  }}
  .kicker {{
    margin: 0 0 8px;
    color: var(--amber);
    font-size: .78rem;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
  }}
  h1 {{
    max-width: 760px;
    margin: 0;
    font-size: clamp(2rem, 5vw, 3.4rem);
    line-height: 1.02;
    letter-spacing: 0;
  }}
  .subtitle {{
    max-width: 760px;
    margin: 14px 0 0;
    color: #d9cdbf;
    font-size: 1.03rem;
  }}
  .meta {{
    color: var(--muted);
    font-size: .88rem;
  }}
  .hero .meta {{
    margin-top: 18px;
  }}
  .promise {{
    margin-top: 18px;
    background: linear-gradient(90deg, var(--amber-soft), rgba(255, 159, 26, .05));
    border: 1px solid rgba(255, 159, 26, .35);
    border-left: 5px solid var(--amber);
    padding: .85rem 1rem;
    border-radius: 8px;
    font-weight: 650;
    box-shadow: 0 0 28px rgba(255, 159, 26, .08);
  }}
  .section {{
    margin-top: 28px;
    padding-top: 4px;
  }}
  h2 {{
    margin: 0 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--line);
    color: var(--amber-bright);
    font-size: 1.25rem;
  }}
  h3 {{
    margin: 0 0 10px;
    font-size: 1rem;
  }}
  .callout, .note {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 14px 16px;
    box-shadow: var(--glow);
  }}
  .callout p, .note p {{ margin: 0; }}
  .metrics {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 10px;
    margin: 14px 0 18px;
  }}
  .metric {{
    min-width: 0;
    background: linear-gradient(180deg, var(--panel-raised), var(--panel));
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 12px;
    box-shadow: var(--glow);
  }}
  .metric strong {{
    display: block;
    color: var(--amber-bright);
    font-size: 1.45rem;
    line-height: 1.1;
  }}
  .metric span {{
    display: block;
    margin-top: 4px;
    color: var(--muted);
    font-size: .78rem;
    font-weight: 700;
  }}
  .table-wrap {{
    width: 100%;
    overflow-x: auto;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--panel);
    box-shadow: var(--glow);
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    min-width: 620px;
  }}
  th, td {{
    border-bottom: 1px solid var(--line);
    padding: .55rem .7rem;
    text-align: left;
    vertical-align: top;
  }}
  tr:last-child td {{ border-bottom: 0; }}
  th {{
    background: var(--panel-soft);
    color: var(--amber-bright);
    font-size: .78rem;
    text-transform: uppercase;
  }}
  code {{
    overflow-wrap: anywhere;
    background: var(--gray-soft);
    padding: .08rem .32rem;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .88em;
  }}
  pre {{
    max-height: 230px;
    margin: 12px 0 0;
    background: #0b0907;
    color: #f2dfc0;
    border: 1px solid var(--line);
    padding: .9rem 1rem;
    border-radius: 8px;
    overflow: auto;
  }}
  .cluster-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }}
  .cluster {{
    min-width: 0;
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 14px 16px;
    background: linear-gradient(180deg, var(--panel-raised), var(--panel));
    box-shadow: var(--glow);
  }}
  .cluster-head {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
    padding-bottom: 9px;
    border-bottom: 1px solid var(--line);
  }}
  .cluster-head h3 {{
    margin: 0;
    overflow-wrap: anywhere;
  }}
  .badge {{
    display: inline-flex;
    align-items: center;
    min-height: 24px;
    padding: .16rem .55rem;
    border-radius: 999px;
    font-size: .76rem;
    font-weight: 800;
    white-space: nowrap;
  }}
  .High {{ background: var(--green-soft); color: #86efac; }}
  .Medium {{ background: var(--amber-soft); color: var(--amber-bright); }}
  .Low {{ background: var(--blue-soft); color: #c4b5fd; }}
  .cluster ul, .compact-list {{
    margin: 10px 0 0;
    padding-left: 1.1rem;
  }}
  .cluster li {{ margin: .24rem 0; }}
  .cluster li ul {{ margin-top: .28rem; }}
  .twin {{ color: var(--violet); font-weight: 700; }}
  .narrative {{
    background:
      linear-gradient(180deg, rgba(255, 159, 26, .08), rgba(20, 16, 11, .92));
    border: 1px solid var(--line-strong);
    border-radius: 8px;
    padding: 16px 18px;
    box-shadow: var(--shadow);
  }}
  .narrative p {{
    margin: .6rem 0;
  }}
  .narrative p:first-child {{ margin-top: 0; }}
  .narrative p:last-child {{ margin-bottom: 0; }}
  @media (max-width: 920px) {{
    .metrics {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .cluster-grid {{ grid-template-columns: 1fr; }}
  }}
  @media (max-width: 560px) {{
    .page {{ width: min(100% - 20px, 1120px); padding-top: 18px; }}
    .hero {{ padding-top: 14px; }}
    .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .metric strong {{ font-size: 1.22rem; }}
    .cluster {{ padding: 12px; }}
  }}
</style></head><body>
<main class="page">
{body}
</main>
</body></html>"""


def esc(x):
    return html.escape(str(x))


def render_html(data, source_label, overview_name, overview_head):
    s = data["summary"]
    B = []
    B.append("<header class='hero'>")
    B.append("<p class='kicker'>Read-only folder map</p>")
    B.append("<h1>See what's in your folder before you move anything.</h1>")
    B.append("<p class='subtitle'>A deterministic report over your folder: "
             "original paths, provisional clusters, evidence, confidence, and "
             "advisory next moves.</p>")
    B.append(f"<p class='meta'>Generated: {esc(data['generated_at'])}<br>"
             f"Source (read-only, untouched): <code>{esc(source_label)}</code></p>")
    B.append("<p class='promise'>No files were moved, renamed, deleted, or "
             "modified. This is a map of your existing work, not a "
             "reorganization of it.</p>")
    B.append("</header>")

    # 1. overview-file callout
    B.append("<section class='section'>")
    B.append("<h2>Noticed: overview file</h2>")
    B.append("<div class='callout'>")
    if overview_name:
        B.append(f"<p>A top-level index / overview file is present: "
                 f"<strong><code>{esc(overview_name)}</code></strong>. "
                 f"Surfaced for awareness only; <strong>not</strong> used "
                 f"as clustering input.</p>")
        B.append(f"<pre>{esc(overview_head.strip())}</pre>")
    else:
        B.append("<p><em>No top-level index or overview file detected.</em></p>")
    B.append("</div>")
    B.append("</section>")

    # 2. Path Map
    B.append("<section class='section'>")
    B.append("<h2>Path Map</h2>")
    B.append("<div class='metrics'>")
    B.append(f"<div class='metric'><strong>{s['total_files_inventoried']}"
             f"</strong><span>files inventoried</span></div>")
    B.append(f"<div class='metric'><strong>{s['cluster_count']}</strong>"
             f"<span>clusters detected</span></div>")
    B.append(f"<div class='metric'><strong>"
             f"{s['confidence_distribution'].get('High', 0)}</strong>"
             f"<span>high confidence</span></div>")
    B.append(f"<div class='metric'><strong>"
             f"{s['confidence_distribution'].get('Medium', 0)}</strong>"
             f"<span>medium confidence</span></div>")
    B.append(f"<div class='metric'><strong>"
             f"{s['cross_bucket_twin_count']}</strong>"
             f"<span>cross-bucket twins</span></div>")
    B.append(f"<div class='metric'><strong>{s['unsorted_loose_count']}</strong>"
             f"<span>unsorted loose files</span></div>")
    B.append("</div>")
    if data.get("preservation_buckets"):
        B.append("<h3>Low-confidence containers (numeric-named folders)</h3>")
        B.append("<div class='table-wrap'><table><tr><th>Folder</th><th>Files</th>"
                 "<th>Meaningful children</th></tr>")
        for b in data["preservation_buckets"]:
            kids = esc(", ".join(b["child_clusters"]) or "—")
            B.append(f"<tr><td><code>{esc(b['name'])}/</code></td>"
                     f"<td>{b['file_count']}</td><td>{kids}</td></tr>")
        B.append("</table></div>")
        B.append("<p class='meta'>Numeric- or generic-named top-level folders "
                 "carry little semantic meaning on their own — the meaning "
                 "lives in their children.</p>")
    B.append("</section>")

    # 3. Clusters
    B.append("<section class='section'>")
    B.append("<h2>Project Clusters</h2>")
    B.append("<div class='note'><p>Confidence describes evidence strength, not "
             "importance. A low-confidence cluster may still hold valuable "
             "work — it just means the scanner has weak evidence for naming "
             "it.</p></div>")
    B.append("<div class='cluster-grid'>")
    for c in data["clusters"]:
        B.append("<div class='cluster'>")
        B.append("<div class='cluster-head'>")
        B.append(f"<h3>{esc(c['name'])}</h3>")
        B.append(f"<span class='badge {c['confidence']}'>{c['confidence']}"
                 f"</span>")
        B.append("</div>")
        B.append("<ul>")
        B.append(f"<li><strong>Path:</strong> <code>{esc(c['key_path'])}"
                 f"</code></li>")
        B.append(f"<li><strong>Name source:</strong> {esc(c['name_source'])}"
                 f"</li>")
        B.append(f"<li><strong>Confidence:</strong> {c['confidence']} — "
                 f"{esc(c['confidence_reason'])}</li>")
        B.append(f"<li><strong>Files:</strong> {c['file_count']} · "
                 f"<strong>Size:</strong> {fmt_bytes(c['total_bytes'])}</li>")
        if c.get("mtime_min"):
            B.append(f"<li><strong>Modified:</strong> "
                     f"{fmt_date(c['mtime_min'])} → "
                     f"{fmt_date(c['mtime_max'])}</li>")
        if c.get("is_software_project"):
            B.append("<li><strong>Software project:</strong> yes "
                     "(metadata-only)</li>")
        if c.get("cross_bucket_twin"):
            t = c["cross_bucket_twin"]
            B.append(f"<li class='twin'>Cross-bucket twin: "
                     f"<code>{esc(t['name'])}</code> in {esc(t['buckets'])} — "
                     f"{esc(t['note'])}</li>")
        if c["signals"]:
            B.append("<li><strong>Evidence:</strong><ul>")
            for sig in c["signals"]:
                B.append(f"<li>{esc(sig)}</li>")
            B.append("</ul></li>")
        if c["representative_files"]:
            B.append("<li><strong>Representative files:</strong><ul>")
            for f in c["representative_files"]:
                B.append(f"<li><code>{esc(f)}</code></li>")
            B.append("</ul></li>")
        if c["loose_files_attached"]:
            B.append(f"<li><strong>Loose files attached "
                     f"({len(c['loose_files_attached'])}):</strong><ul>")
            for f in c["loose_files_attached"][:10]:
                B.append(f"<li><code>{esc(f)}</code></li>")
            B.append("</ul></li>")
        B.append("</ul></div>")
    B.append("</div>")

    if data["cross_bucket_twins"]:
        B.append("<section class='section'>")
        B.append("<h3>Cross-bucket twins</h3><ul>")
        for t in data["cross_bucket_twins"]:
            B.append(f"<li class='twin'><code>{esc(t['name'])}</code> in "
                     f"buckets {esc(t['buckets'])} — possible same project / "
                     f"diverged copies.</li>")
        B.append("</ul>")
        B.append("</section>")

    ub = data["unsorted_loose_files"]
    B.append(f"<h3>Unsorted / loose files ({ub['count']})</h3>")
    if ub["files"]:
        B.append("<ul class='compact-list'>")
        for f in ub["files"][:25]:
            B.append(f"<li><code>{esc(f)}</code></li>")
        B.append("</ul>")
    else:
        B.append("<p><em>None.</em></p>")
    B.append("</section>")

    # 4. Narrative wrap
    B.append("<section class='section'>")
    B.append("<h2>Narrative Wrap</h2>")
    B.append("<div class='narrative'>")
    for line in narrative_lines(data):
        # crude md-bold -> html-bold for the template prose
        B.append(f"<p>{md_inline_to_html(line)}</p>")
    B.append("</div>")
    B.append("</section>")

    # 5. stub
    B.append("<section class='section'>")
    B.append("<h2>Future Projections (stub)</h2>")
    B.append("<div class='note'><p>Later versions can project these clusters into PARA, GTD, "
             "Obsidian/MOC, or a custom layout. This report keeps the source "
             "map and evidence primary. No machinery here.</p></div>")
    B.append("</section>")

    return HTML_TEMPLATE.format(body="\n".join(B))


def md_inline_to_html(line):
    # Render the template prose's **bold** and `code` spans as HTML, after
    # escaping. Deterministic; the prose itself comes from narrative_lines.
    esc_line = html.escape(line)
    esc_line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc_line)
    esc_line = re.sub(r"`(.+?)`", r"<code>\1</code>", esc_line)
    return esc_line


def default_out_dir() -> Path:
    return Path.cwd() / "folder-map-out"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Render clusters.json into report.md + report.html."
    )
    ap.add_argument("target", help="The folder that was scanned (read-only; "
                                   "read here only to surface a top-level "
                                   "overview file).")
    ap.add_argument(
        "--out", default=None,
        help="Directory holding clusters.json; reports are written here too "
             "(default: ./folder-map-out).",
    )
    ap.add_argument(
        "--redact", action="store_true",
        help="Scrub local username / home path from the rendered output "
             "(for sharing or screenshots). Off by default.",
    )
    args = ap.parse_args(argv[1:])

    target = Path(os.path.expanduser(args.target)).resolve()
    out_dir = (
        Path(os.path.expanduser(args.out)) if args.out else default_out_dir()
    )
    clusters_path = out_dir / "clusters.json"
    report_md = out_dir / "report.md"
    report_html = out_dir / "report.html"

    # Display only the folder name, never the absolute path.
    source_label = target.name + "/"

    if not clusters_path.exists():
        print(json.dumps({
            "status": "error",
            "reason": "clusters_missing",
            "expected": str(clusters_path),
            "hint": "run cluster.py first",
        }))
        return 2

    data = json.loads(clusters_path.read_text(encoding="utf-8"))
    overview_name, overview_head = read_taxonomy_callout(target)

    md = render_md(data, source_label, overview_name, overview_head)
    html_doc = render_html(data, source_label, overview_name, overview_head)
    if args.redact:
        md = redact(md)
        html_doc = redact(html_doc)
    report_md.write_text(md, encoding="utf-8")
    report_html.write_text(html_doc, encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "out": str(out_dir),
        "report_md": str(report_md),
        "report_html": str(report_html),
        "redacted": bool(args.redact),
        "overview_file": overview_name,
        "cluster_count": data["summary"]["cluster_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
