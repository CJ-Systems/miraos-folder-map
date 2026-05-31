#!/usr/bin/env python3
"""cluster.py — hybrid, directory-primary clustering over inventory.jsonl.

Reads <out>/inventory.jsonl, scores directory subtrees, names + scores
confidence for each cluster, attaches loose files, flags cross-bucket twins,
and emits <out>/clusters.json.

Deterministic heuristics only. No LLM calls. Python stdlib only.

clusters.json is built ingest-ready (each cluster is a node-shaped record with
evidence) but no ingest happens here.

Output contract: a single JSON status object on stdout (the agent's input).
Human-readable progress goes to stderr.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Numeric preservation buckets carry no semantic meaning. (Some backup tools
# create numeric top-level dirs — 2/, 3/, 4/ — to avoid overwriting same-named
# folders from different vintages. The meaning lives in their children.)
NUMERIC_BUCKET_RE = re.compile(r"^\d+$")
GENERIC_DIR_NAMES = {
    "temp", "tmp", "misc", "untitled", "new folder", "data", "src",
    "docs", "doc", "assets", "_assets", "files", "output", "out",
}

# A directory needs at least this many files to be a candidate cluster.
MIN_CLUSTER_FILES = 4
# Cluster directories at this depth from root (1 = top-level, 2 = bucket
# child, etc). We cluster at depth 1 and 2 so children of numeric buckets
# (e.g. 3/project-notes) earn their own labels.
CLUSTER_DEPTHS = (1, 2)

README_RE = re.compile(r"^(readme|index)", re.I)
MANIFEST_RE = re.compile(r"(manifest|\.toml$|package\.json$)", re.I)


def load_inventory(path: Path):
    recs = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def parts_of(rel: str):
    return rel.replace("\\", "/").split("/")


def cluster_key_for(rel: str):
    """Return (depth, key_path) for the clustering directory this file rolls
    up into, or None if the file is a root-level loose stray.

    Files directly under root (depth-1 file) are loose. Files inside a
    top-level dir roll up to that dir (depth 1). Files two levels deep where
    the top-level dir is a numeric preservation bucket roll up to the
    depth-2 child so meaningful names surface.
    """
    p = parts_of(rel)
    if len(p) <= 1:
        return None  # root-level loose file
    top = p[0]
    if NUMERIC_BUCKET_RE.match(top) and len(p) >= 3:
        # numeric bucket: cluster on the child (depth 2)
        return (2, f"{top}/{p[1]}")
    return (1, top)


def derive_name(key_path, members):
    """Return (name, source) per the naming priority order."""
    p = parts_of(key_path)
    dir_name = p[-1]

    # 1. README / manifest project name (use the dir name when a README or
    #    manifest is present — it is the closest deterministic proxy for the
    #    project's declared name without LLM extraction).
    has_readme = any(README_RE.match(parts_of(m["path"])[-1]) for m in members)
    has_manifest = any(MANIFEST_RE.search(parts_of(m["path"])[-1]) for m in members)
    meaningful_dir = not (
        NUMERIC_BUCKET_RE.match(dir_name)
        or dir_name.lower() in GENERIC_DIR_NAMES
    )

    if (has_readme or has_manifest) and meaningful_dir:
        return dir_name, "readme/manifest"

    # 2. Meaningful directory name
    if meaningful_dir:
        return dir_name, "directory-name"

    # 3. Dominant repeated token across filenames
    tok = dominant_filename_token(members)
    if tok:
        token, hits, total = tok
        return (
            f"{token} (inferred from {hits}/{total} filenames)",
            "dominant-token",
        )

    # 4. Fallback: loose files of a dominant type in this path
    ext = dominant_ext(members)
    kind = EXT_LABELS.get(ext, ext.lstrip(".").upper() if ext else "mixed")
    return f"Loose {kind} files in {key_path}/", "path+ext"


EXT_LABELS = {
    ".md": "Markdown",
    ".json": "JSON",
    ".jsonl": "JSONL",
    ".py": "Python",
    ".txt": "text",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".html": "HTML",
    ".csv": "CSV",
}

FNAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
FNAME_STOP = {"the", "and", "for", "md", "json", "txt", "yaml", "session"}


def dominant_filename_token(members):
    counts = Counter()
    for m in members:
        stem = parts_of(m["path"])[-1].rsplit(".", 1)[0].lower()
        for w in set(FNAME_TOKEN_RE.findall(stem)):
            if w not in FNAME_STOP:
                counts[w] += 1
    if not counts:
        return None
    token, hits = counts.most_common(1)[0]
    total = len(members)
    if hits >= max(3, total * 0.5):
        return token, hits, total
    return None


def dominant_ext(members):
    c = Counter(m["ext"] for m in members if m["ext"])
    return c.most_common(1)[0][0] if c else ""


def dominant_token_from_content(members):
    """Top token across sampled file headers/tokens; used as a signal."""
    c = Counter()
    for m in members:
        for tok, n in m.get("tokens", {}).items():
            c[tok] += n
    if not c:
        return None
    token, _ = c.most_common(1)[0]
    # share of members mentioning the token
    mentions = sum(1 for m in members if token in m.get("tokens", {}))
    return token, mentions, len(members)


def modtime_span_days(members):
    times = [m["mtime"] for m in members if m.get("mtime")]
    if len(times) < 2:
        return 0.0
    return (max(times) - min(times)) / 86400.0


def score_cluster(key_path, depth, members):
    name, name_source = derive_name(key_path, members)
    dir_name = parts_of(key_path)[-1]
    is_numeric = bool(NUMERIC_BUCKET_RE.match(dir_name))

    # --- independent signals ---
    signals = []
    has_readme = any(README_RE.match(parts_of(m["path"])[-1]) for m in members)
    has_manifest = any(MANIFEST_RE.search(parts_of(m["path"])[-1]) for m in members)
    if has_readme or has_manifest:
        signals.append("readme/manifest present")

    ftok = dominant_filename_token(members)
    if ftok:
        signals.append(
            f"shared filename token '{ftok[0]}' ({ftok[1]}/{ftok[2]})"
        )

    ctok = dominant_token_from_content(members)
    if ctok and ctok[1] >= max(3, ctok[2] * 0.5):
        signals.append(
            f"shared content token '{ctok[0]}' ({ctok[1]}/{ctok[2]})"
        )

    span = modtime_span_days(members)
    if 0 < span <= 14 and len(members) >= MIN_CLUSTER_FILES:
        signals.append(f"tight modtime cluster (~{span:.1f}d span)")

    enough = len(members) >= MIN_CLUSTER_FILES

    # --- confidence (derivation made visible) ---
    n_signals = len(signals)
    if is_numeric:
        confidence = "Low"
        conf_reason = "numeric preservation bucket (no semantics)"
    elif (has_readme or has_manifest) and n_signals >= 3 and enough:
        confidence = "High"
        conf_reason = "three independent signals agree + enough files"
    elif n_signals >= 2 and enough:
        confidence = "Medium"
        conf_reason = "two independent signals agree"
    elif n_signals >= 2:
        confidence = "Low"
        conf_reason = "signals agree but few files"
    else:
        confidence = "Low"
        conf_reason = "single signal / weak evidence"

    exts = Counter(m["ext"] for m in members if m["ext"])
    times = [m["mtime"] for m in members if m.get("mtime")]
    is_project = any(m.get("in_project") for m in members)

    reps = sorted(
        members,
        key=lambda m: (
            0 if README_RE.match(parts_of(m["path"])[-1]) else 1,
            -m.get("sample_chars", 0),
        ),
    )[:5]

    return {
        "name": name,
        "name_source": name_source,
        "key_path": key_path,
        "depth": depth,
        "is_numeric_bucket": is_numeric,
        "is_software_project": is_project,
        "confidence": confidence,
        "confidence_reason": conf_reason,
        "signals": signals,
        "file_count": len(members),
        "total_bytes": sum(m["size"] for m in members),
        "dominant_exts": dict(exts.most_common(5)),
        "mtime_min": min(times) if times else None,
        "mtime_max": max(times) if times else None,
        "mtime_span_days": round(span, 1),
        "representative_files": [m["path"] for m in reps],
        "loose_files_attached": [],
    }


def cluster(recs):
    # Group files by their clustering directory.
    groups = defaultdict(list)
    root_loose = []
    for r in recs:
        ck = cluster_key_for(r["path"])
        if ck is None:
            root_loose.append(r)
        else:
            groups[ck].append(r)

    clusters = []
    weak_loose = list(root_loose)
    for (depth, key_path), members in groups.items():
        if len(members) >= MIN_CLUSTER_FILES:
            clusters.append(score_cluster(key_path, depth, members))
        else:
            # weak directory -> its files become loose for a file-level pass
            weak_loose.extend(members)

    # --- file-level pass: attach loose files by token match -----------------
    # Build a token index from strong clusters.
    cluster_tokens = []
    for c in clusters:
        toks = set()
        m = re.match(r"^(\S+)", c["name"])
        if m:
            toks.add(m.group(1).lower())
        toks.update(parts_of(c["key_path"])[-1].lower().split())
        cluster_tokens.append((c, toks))

    unsorted_bucket = []
    for f in weak_loose:
        stem = parts_of(f["path"])[-1].rsplit(".", 1)[0].lower()
        ftoks = set(FNAME_TOKEN_RE.findall(stem))
        attached = False
        for c, toks in cluster_tokens:
            if toks & ftoks and toks - {""}:
                c["loose_files_attached"].append(f["path"])
                attached = True
                break
        if not attached:
            unsorted_bucket.append(f["path"])

    # --- cross-bucket twins -------------------------------------------------
    # same child name appearing under more than one numeric bucket.
    by_child = defaultdict(list)
    for c in clusters:
        p = parts_of(c["key_path"])
        if len(p) == 2 and NUMERIC_BUCKET_RE.match(p[0]):
            by_child[p[1].lower()].append(c)
    twins = []
    for child, group in by_child.items():
        if len(group) > 1:
            buckets = sorted(parts_of(c["key_path"])[0] for c in group)
            for c in group:
                c.setdefault("cross_bucket_twin", {})
                c["cross_bucket_twin"] = {
                    "name": child,
                    "buckets": buckets,
                    "note": "possible same project / possible diverged copies",
                }
            twins.append({"name": child, "buckets": buckets})

    # --- preservation-bucket containers -------------------------------------
    # Numeric parents (2/3/4) render as explicit low-confidence containers;
    # their meaningful children (already clustered above) earn the labels.
    bucket_children = defaultdict(list)
    for c in clusters:
        p = parts_of(c["key_path"])
        if len(p) == 2 and NUMERIC_BUCKET_RE.match(p[0]):
            bucket_children[p[0]].append(c["name"])
    bucket_file_counts = Counter()
    for r in recs:
        top = parts_of(r["path"])[0]
        if NUMERIC_BUCKET_RE.match(top):
            bucket_file_counts[top] += 1
    containers = []
    for bucket in sorted(bucket_file_counts):
        containers.append({
            "name": bucket,
            "name_source": "numeric-preservation-bucket",
            "key_path": bucket,
            "depth": 1,
            "is_numeric_bucket": True,
            "is_software_project": False,
            "confidence": "Low",
            "confidence_reason": (
                "numeric preservation bucket — created to avoid overwriting "
                "same-named backups; carries no semantic meaning"
            ),
            "signals": [],
            "file_count": bucket_file_counts[bucket],
            "child_clusters": sorted(bucket_children.get(bucket, [])),
            "representative_files": [],
            "loose_files_attached": [],
        })

    # Sort: confidence then size.
    conf_rank = {"High": 0, "Medium": 1, "Low": 2}
    clusters.sort(key=lambda c: (conf_rank[c["confidence"]], -c["file_count"]))

    conf_dist = Counter(c["confidence"] for c in clusters)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_files_inventoried": len(recs),
            "cluster_count": len(clusters),
            "confidence_distribution": dict(conf_dist),
            "cross_bucket_twin_count": len(twins),
            "unsorted_loose_count": len(unsorted_bucket),
            "software_project_count": sum(
                1 for c in clusters if c["is_software_project"]
            ),
        },
        "preservation_buckets": containers,
        "clusters": clusters,
        "cross_bucket_twins": twins,
        "unsorted_loose_files": {
            "count": len(unsorted_bucket),
            "files": unsorted_bucket[:200],
        },
    }


def default_out_dir() -> Path:
    return Path.cwd() / "folder-map-out"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Hybrid directory-primary clustering over inventory.jsonl."
    )
    ap.add_argument(
        "--out", default=None,
        help="Directory holding inventory.jsonl; clusters.json is written "
             "here too (default: ./folder-map-out).",
    )
    args = ap.parse_args(argv[1:])

    out_dir = (
        Path(os.path.expanduser(args.out)) if args.out else default_out_dir()
    )
    inventory_path = out_dir / "inventory.jsonl"
    clusters_path = out_dir / "clusters.json"

    if not inventory_path.exists():
        print(json.dumps({
            "status": "error",
            "reason": "inventory_missing",
            "expected": str(inventory_path),
            "hint": "run scan.py first",
        }))
        return 2

    recs = load_inventory(inventory_path)
    result = cluster(recs)
    clusters_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    s = result["summary"]
    print(json.dumps({
        "status": "ok",
        "out": str(out_dir),
        "clusters_json": str(clusters_path),
        "total_files_inventoried": s["total_files_inventoried"],
        "cluster_count": s["cluster_count"],
        "confidence_distribution": s["confidence_distribution"],
        "cross_bucket_twin_count": s["cross_bucket_twin_count"],
        "unsorted_loose_count": s["unsorted_loose_count"],
        "software_project_count": s["software_project_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
