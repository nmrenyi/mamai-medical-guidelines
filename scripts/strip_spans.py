"""
strip_spans.py — Strip HTML span tags from marker-pdf markdown output.

marker-pdf preserves <span id="page-X-Y"></span> anchor tags from the source
PDF's HTML layer. These are invisible in rendered markdown but break heading
detection (a line starting with `# <span...>` is not matched as a heading by
regex or markdown parsers).

Reads from:  processed/markdowns/{international,tanzania}/
Writes to:   processed/markdowns_clean/{international,tanzania}/

Originals are never modified.

Usage:
    python scripts/strip_spans.py
    python scripts/strip_spans.py --dry-run   # report changes without writing
"""

import argparse
import re
from pathlib import Path

# Matches empty span tags only: <span id="..."></span>
# marker-pdf only emits empty anchors (no content inside), so this is safe.
SPAN_RE = re.compile(r"<span[^>]*></span>")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "processed" / "extracted"
DST_ROOT = PROJECT_ROOT / "processed" / "normalized"
SUBDIRS = ["international", "tanzania"]


def strip_spans(text: str) -> tuple[str, int]:
    """Remove all empty span tags. Returns (cleaned_text, count_removed)."""
    cleaned, n = SPAN_RE.subn("", text)
    return cleaned, n


def main():
    parser = argparse.ArgumentParser(description="Strip span tags from markdowns")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing any files",
    )
    args = parser.parse_args()

    total_files = 0
    total_spans = 0
    unchanged = 0

    for subdir in SUBDIRS:
        src_dir = SRC_ROOT / subdir
        dst_dir = DST_ROOT / subdir

        if not src_dir.exists():
            print(f"  SKIP (not found): {src_dir}")
            continue

        if not args.dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)

        for src in sorted(src_dir.glob("*.md")):
            text = src.read_text(encoding="utf-8")
            cleaned, n = strip_spans(text)
            total_files += 1

            if n == 0:
                unchanged += 1
                if not args.dry_run:
                    # Still copy to keep the clean dir complete
                    (dst_dir / src.name).write_text(text, encoding="utf-8")
                print(f"  {'[dry]' if args.dry_run else '[copy]'} {subdir}/{src.name}  (no spans)")
            else:
                total_spans += n
                dst = dst_dir / src.name
                if not args.dry_run:
                    dst.write_text(cleaned, encoding="utf-8")
                print(f"  {'[dry]' if args.dry_run else '[wrote]'} {subdir}/{src.name}  ({n} spans removed)")

    print()
    print(f"Files processed : {total_files}")
    print(f"Files unchanged : {unchanged}")
    print(f"Total spans removed: {total_spans}")
    if args.dry_run:
        print("(dry run — nothing written)")
    else:
        print(f"Output: {DST_ROOT}")


if __name__ == "__main__":
    main()
