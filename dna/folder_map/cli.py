#!/usr/bin/env python3
"""folder-map — one command that maps a folder of scattered files, read-only.

This is the front door. It runs the three engine stages in order —
scan -> cluster -> report — in-process, and narrates the run in plain
language. Each stage's ``main()`` prints one JSON status line to stdout and
progress to stderr; both are captured here so the user only ever reads a line
this orchestrator wrote. The engine's output is *this program's input*, never
the user's output.
"""

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

from folder_map import cluster as cluster_mod
from folder_map import report as report_mod
from folder_map import scan as scan_mod

__all__ = ["main"]


def default_out_dir() -> Path:
    # Matches each stage's own default so behaviour is identical with or
    # without this orchestrator.
    return Path.cwd() / "folder-map-out"


def _run_stage(label, module, stage_argv):
    """Run one engine stage in-process. Return its parsed JSON status dict.

    The stage's stdout (a JSON status line) is captured as our input. Its
    stderr (progress chatter) is captured and only surfaced if the stage
    fails, so the user reads our narration, not the substrate's.
    """
    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out_buf), \
                contextlib.redirect_stderr(err_buf):
            # Each stage parses argv[1:], so prepend a dummy program name.
            rc = module.main([f"folder-map-{label}"] + stage_argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1

    # The status line is the last non-empty stdout line.
    status = None
    for line in reversed(out_buf.getvalue().strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            status = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

    if rc != 0 or status is None or status.get("status") != "ok":
        _stage_failed(label, status, err_buf.getvalue())
        return None
    return status


def _stage_failed(label, status, stderr_text):
    """Translate a stage failure into a plain sentence + a next step."""
    reason = (status or {}).get("reason")
    messages = {
        "target_not_found": "I couldn't find that folder. Check the path and "
                            "try again.",
        "inventory_missing": "The scan step didn't leave its inventory behind "
                            "— the scan may have been interrupted.",
        "clusters_missing": "The clustering step didn't finish, so there's "
                           "nothing to report on yet.",
    }
    print(f"\nSomething went wrong during the {label} step.", file=sys.stderr)
    if reason in messages:
        print(f"  {messages[reason]}", file=sys.stderr)
    elif status and status.get("status") == "error":
        print(f"  reason: {reason}", file=sys.stderr)
    else:
        # No clean status line — show the substrate's own stderr as a last
        # resort so the failure isn't silent.
        tail = (stderr_text or "").strip()
        if tail:
            print("  " + tail.replace("\n", "\n  "), file=sys.stderr)


def main(argv=None):
    if argv is None:
        argv = sys.argv
    ap = argparse.ArgumentParser(
        prog="folder-map",
        description="Map a folder of scattered files, read-only: scan it, "
                    "cluster related files with visible evidence and "
                    "confidence, and write a report. Never moves, renames, or "
                    "deletes anything in the scanned folder.",
    )
    ap.add_argument("target", help="Folder to map (read-only).")
    ap.add_argument(
        "--out", default=None,
        help="Output directory for the inventory, clusters, and report "
             "(default: ./folder-map-out). Must be outside the scanned folder.",
    )
    ap.add_argument(
        "--redact", action="store_true",
        help="Scrub your username / home path from the report, for sharing "
             "or screenshots.",
    )
    ap.add_argument(
        "--version", action="version",
        version=f"folder-map {_version()}",
    )
    args = ap.parse_args(argv[1:])

    target = Path(os.path.expanduser(args.target))
    out_dir = (
        Path(os.path.expanduser(args.out)) if args.out else default_out_dir()
    )

    if not target.is_dir():
        print(f"I couldn't find a folder at: {target}", file=sys.stderr)
        print("Check the path and try again.", file=sys.stderr)
        return 2

    out = str(out_dir)
    print(f"Mapping (read-only): {target}")

    print("  1/3  Scanning files…")
    scan = _run_stage("scan", scan_mod, [str(target), "--out", out])
    if scan is None:
        return 1

    print("  2/3  Clustering related files…")
    clust = _run_stage("cluster", cluster_mod, ["--out", out])
    if clust is None:
        return 1

    print("  3/3  Writing the report…")
    report_argv = [str(target), "--out", out]
    if args.redact:
        report_argv.append("--redact")
    report = _run_stage("report", report_mod, report_argv)
    if report is None:
        return 1

    _summary(target, scan, clust, report)
    return 0


def _version():
    from folder_map import __version__
    return __version__


def _summary(target, scan, clust, report):
    """Print the one clean recap the user actually reads."""
    dist = clust.get("confidence_distribution", {})
    high = dist.get("High", 0)
    medium = dist.get("Medium", 0)
    low = dist.get("Low", 0)

    files = scan.get("files_seen", 0)
    clusters = clust.get("cluster_count", 0)

    print()
    print(f"Mapped  {target.name}/  "
          f"(read-only — nothing in it was changed)")
    print(f"  {files} files seen · {clusters} clusters · "
          f"{high} high-confidence, {medium} medium, {low} low")

    twins = clust.get("cross_bucket_twin_count", 0)
    loose = clust.get("unsorted_loose_count", 0)
    extras = []
    if twins:
        extras.append(f"{twins} same-name twins worth comparing")
    if loose:
        extras.append(f"{loose} loose files not yet sorted")
    if extras:
        print("  " + " · ".join(extras))

    print(f"  Report: {report.get('report_html', '(see output dir)')}")
    if report.get("redacted"):
        print("  (report is redacted — safe to share)")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
