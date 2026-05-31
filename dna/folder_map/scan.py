#!/usr/bin/env python3
"""scan.py — read-only walker for any folder of scattered files.

Walks a target folder applying the tiered scanning rules and emits
<out>/inventory.jsonl — one JSON object per file (metadata + bounded text
samples).

Hard rule: READ-ONLY. This script never moves, renames, deletes, rewrites,
or symlinks anything in the target. It only reads.

Deterministic heuristics only. No LLM calls. Python stdlib only.

Output contract: a single JSON status object on stdout (the agent's input —
never shown to the user raw). Human-readable progress goes to stderr.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# --- Tier 1: skip entirely -------------------------------------------------
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".cache",
}
# binaries by extension — skipped entirely (not even metadata-only)
SKIP_EXTS = {
    ".zip", ".png", ".svg", ".pyc", ".tar", ".gz", ".tgz", ".bz2", ".xz",
    ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".so", ".dll", ".exe",
    ".whl", ".7z", ".rar", ".mp4", ".mp3", ".wav", ".webp", ".woff",
    ".woff2", ".ttf", ".eot", ".bin", ".dat", ".db", ".sqlite",
}
# defensive: Windows backup cruft (e.g. files synced off a Windows drive)
SKIP_NAMES_SUFFIX = (":Zone.Identifier",)

# --- Tier 3/4: text sampling ----------------------------------------------
ONE_MB = 1024 * 1024
SAMPLE_SMALL = 4 * 1024
SAMPLE_LARGE = 16 * 1024

TEXT_EXTS = {
    ".md", ".markdown", ".txt", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".csv", ".tsv", ".rst", ".org", ".html",
    ".htm", ".xml", ".log", ".env", ".sh", ".sql", ".gitignore",
}
# Source-code extensions: metadata-only by default; never sampled inside a
# software-project subtree (would pollute clustering vocabulary).
SOURCE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb", ".java",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala",
    ".lua", ".pl", ".r", ".m", ".mm", ".vue",
}

LARGE_SAMPLE_PATTERNS = (
    re.compile(r"^readme", re.I),
    re.compile(r"^index\.md$", re.I),
    re.compile(r"manifest", re.I),
    re.compile(r"top-level", re.I),
    re.compile(r"^changelog", re.I),
)

# Manifests that mark a directory as a software-project root.
PROJECT_MANIFESTS = {
    "pyproject.toml", "setup.py", "requirements.txt", "package.json",
    "cargo.toml", "go.mod", "gemfile",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was",
    "you", "your", "have", "has", "not", "but", "all", "can", "will",
    "one", "out", "use", "any", "how", "what", "when", "where", "which",
    "they", "them", "then", "than", "into", "more", "some", "such",
    "http", "https", "www", "com", "org", "html", "true", "false", "null",
    "def", "import", "return", "self", "none", "class", "print", "name",
    "value", "data", "type", "file", "files", "list", "dict", "str",
    "int", "new", "get", "set", "var", "const", "let", "function",
}

H_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$")


def is_binary_sample(chunk: bytes) -> bool:
    if not chunk:
        return False
    if b"\x00" in chunk:
        return True
    # high ratio of non-text bytes => binary
    text_chars = bytes(range(0x20, 0x7F)) + b"\n\r\t\f\b"
    nontext = sum(1 for b in chunk if b not in text_chars)
    return nontext / len(chunk) > 0.30


def find_project_root(dirpath: Path, dirnames, filenames) -> bool:
    """True if this directory is a software-project subtree root."""
    lowered = {f.lower() for f in filenames}
    if lowered & PROJECT_MANIFESTS:
        return True
    if ".git" in dirnames:
        return True
    return False


def tokenize(text: str) -> Counter:
    c = Counter()
    for m in TOKEN_RE.finditer(text):
        w = m.group(0).lower()
        if w in STOPWORDS:
            continue
        c[w] += 1
    return c


def extract_md_headers(text: str, limit: int = 8):
    headers = []
    for line in text.splitlines():
        m = H_RE.match(line)
        if m:
            headers.append(m.group(2).strip())
            if len(headers) >= limit:
                break
    return headers


def wants_large_sample(name: str) -> bool:
    return any(p.search(name) for p in LARGE_SAMPLE_PATTERNS)


def _in_docs(rel: str) -> bool:
    parts = rel.replace("\\", "/").lower().split("/")
    return "docs" in parts


def scan(target: Path, out_dir: Path):
    target = target.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = out_dir / "inventory.jsonl"

    stats = Counter()
    project_roots = []  # list of resolved paths that are project subtrees

    with inventory_path.open("w", encoding="utf-8") as out:
        for dirpath, dirnames, filenames in os.walk(target):
            dpath = Path(dirpath)

            # Detect software-project root BEFORE pruning .git, so .git counts.
            # The scan root itself is excluded: the target may itself be a git
            # repo (a container), not a project subtree we want to collapse.
            in_project = any(
                str(dpath) == r or str(dpath).startswith(r + os.sep)
                for r in project_roots
            )
            if (
                not in_project
                and dpath != target
                and find_project_root(dpath, dirnames, filenames)
            ):
                project_roots.append(str(dpath))
                in_project = True

            # Prune skip dirs in-place so os.walk does not descend.
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            # Sort in place so descent order is deterministic across machines
            # (os.walk yields entries in filesystem order otherwise).
            dirnames.sort()

            for fname in sorted(filenames):
                fpath = dpath / fname
                rel = os.path.relpath(fpath, target)

                if any(fname.endswith(suf) for suf in SKIP_NAMES_SUFFIX):
                    stats["skipped"] += 1
                    continue

                ext = fpath.suffix.lower()
                if ext in SKIP_EXTS:
                    stats["skipped"] += 1
                    continue

                try:
                    st = fpath.stat()
                except OSError:
                    stats["skipped"] += 1
                    continue

                rec = {
                    "path": rel,
                    "size": st.st_size,
                    "ext": ext,
                    "mtime": int(st.st_mtime),
                    "in_project": in_project,
                    "tier": None,
                    "tokens": {},
                    "headers": [],
                    "sample_chars": 0,
                }

                is_source = ext in SOURCE_EXTS
                is_text = ext in TEXT_EXTS

                # Metadata-only tiers --------------------------------------
                # >1MB always metadata-only; source files always metadata-only;
                # any source-content inside a project subtree is metadata-only.
                if st.st_size > ONE_MB:
                    rec["tier"] = "metadata-only(>1MB)"
                    stats["metadata_only"] += 1
                    out.write(json.dumps(rec) + "\n")
                    continue

                if is_source:
                    rec["tier"] = "metadata-only(source)"
                    stats["metadata_only"] += 1
                    out.write(json.dumps(rec) + "\n")
                    continue

                if in_project and not (is_text and (
                    wants_large_sample(fname) or _in_docs(rel)
                )):
                    # Inside a software project: sample only README*/CHANGELOG*
                    # /docs; everything else metadata-only.
                    rec["tier"] = "metadata-only(in-project)"
                    stats["metadata_only"] += 1
                    out.write(json.dumps(rec) + "\n")
                    continue

                if not is_text:
                    # Unknown extension: content-sniff then metadata-only.
                    rec["tier"] = "metadata-only(non-text)"
                    stats["metadata_only"] += 1
                    out.write(json.dumps(rec) + "\n")
                    continue

                # Sampling tiers -------------------------------------------
                cap = SAMPLE_LARGE if wants_large_sample(fname) else SAMPLE_SMALL
                try:
                    with fpath.open("rb") as fh:
                        chunk = fh.read(cap)
                except OSError:
                    rec["tier"] = "metadata-only(unreadable)"
                    stats["metadata_only"] += 1
                    out.write(json.dumps(rec) + "\n")
                    continue

                if is_binary_sample(chunk):
                    rec["tier"] = "metadata-only(binary-sniff)"
                    stats["metadata_only"] += 1
                    out.write(json.dumps(rec) + "\n")
                    continue

                text = chunk.decode("utf-8", errors="replace")
                rec["tier"] = (
                    "sample-16k" if cap == SAMPLE_LARGE else "sample-4k"
                )
                rec["sample_chars"] = len(text)
                # top-K keyword tokens
                rec["tokens"] = dict(tokenize(text).most_common(12))
                if ext in (".md", ".markdown"):
                    rec["headers"] = extract_md_headers(text)
                stats["sampled"] += 1
                out.write(json.dumps(rec) + "\n")

    stats["project_subtrees"] = len(project_roots)
    return stats, project_roots, inventory_path


def default_out_dir() -> Path:
    return Path.cwd() / "folder-map-out"


def main(argv):
    ap = argparse.ArgumentParser(
        description="Read-only walker over a folder of scattered files."
    )
    ap.add_argument("target", help="Folder to scan (read-only).")
    ap.add_argument(
        "--out", default=None,
        help="Output directory for inventory.jsonl "
             "(default: ./folder-map-out).",
    )
    args = ap.parse_args(argv[1:])

    target = Path(os.path.expanduser(args.target))
    out_dir = (
        Path(os.path.expanduser(args.out)) if args.out else default_out_dir()
    )

    if not target.is_dir():
        print(json.dumps({
            "status": "error",
            "reason": "target_not_found",
            "target": str(target),
        }))
        return 2

    print(f"Scanning (read-only): {target}", file=sys.stderr)
    stats, project_roots, inventory_path = scan(target, out_dir)
    total = stats["sampled"] + stats["metadata_only"] + stats["skipped"]
    print(json.dumps({
        "status": "ok",
        "target": str(target),
        "out": str(out_dir),
        "inventory": str(inventory_path),
        "files_seen": total,
        "sampled": stats["sampled"],
        "metadata_only": stats["metadata_only"],
        "skipped": stats["skipped"],
        "project_subtrees": stats["project_subtrees"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
