"""
package_bundle.py — Package the RAG data bundle for distribution.

Produces a versioned bundle directory:

    rag-bundle-<version>/
        manifest.json
        checksums.sha256
        runtime/
            embeddings.sqlite
        debug/
            chunks_for_rag.txt
        docs/
            <normalized_source_id>.pdf

The normalized_source_id rule (applied to every SOURCE stem and to the PDF
filename it maps to) is:
    - Replace any character that is not alphanumeric, dash, or dot with '_'
    - Collapse consecutive underscores into one
    - Strip leading/trailing underscores

This rule must also be applied in the consumer app's openPdf() before
constructing the file path, so that the app resolves e.g.
"WHO_Abortion Care_2022" -> "WHO_Abortion_Care_2022.pdf".

Usage:
    python scripts/package_bundle.py --version v1.0.0
    python scripts/package_bundle.py --version v1.0.0 --output-dir /tmp/bundle
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_EMBEDDINGS  = PROJECT_ROOT / "processed" / "embeddings.sqlite"
DEFAULT_CHUNKS      = PROJECT_ROOT / "processed" / "chunks_for_rag.txt"
RAW_DIR             = PROJECT_ROOT / "raw"

# PDFs whose stems produce no chunks (exec summaries, alternate filenames).
# These are excluded from the bundle docs/ directory.
SOURCELESS_PDF_STEMS = {
    "WHO_ANCExSummary_2016",
    "WHO_PositiveBirthExSum_2018",
    "WHO_PostnatalEsp_2022",
    "tanzania-nursing-midwifery-curriculum-level5",
    "tanzania-nursing-midwifery-curriculum-level6",
}

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalize_source_id(stem: str) -> str:
    """
    Convert a SOURCE stem (or PDF filename stem) to a safe, URL-friendly ID.

    Rule: replace any char that is not alphanumeric, '-', or '.' with '_',
    collapse consecutive underscores, strip edges.

    Examples:
        "WHO_Abortion Care_2022"              -> "WHO_Abortion_Care_2022"
        "SE 1 _ Governance and Management (2)"-> "SE_1_Governance_and_Management_2"
        "WHO_PositiveBirth_2018"              -> "WHO_PositiveBirth_2018"  (unchanged)
    """
    s = re.sub(r"[^A-Za-z0-9\-.]", "_", stem)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def count_chunks(chunks_path: Path) -> int:
    count = 0
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("<sep>"):
                count += 1
    return count


def collect_source_ids(chunks_path: Path) -> set[str]:
    sources: set[str] = set()
    # Lines look like: <sep>[SOURCE:WHO_PositiveBirth_2018|PAGE:42]
    # or (in the raw chunk body): [SOURCE:...|PAGE:...]
    pattern = re.compile(r"<sep>\[SOURCE:([^|]+)\|")
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            m = pattern.match(line)
            if m:
                sources.add(m.group(1))
    return sources


def find_pdf_for_stem(stem: str) -> Path | None:
    """Search raw/ for a PDF whose stem exactly matches the given stem."""
    for path in RAW_DIR.rglob("*.pdf"):
        if path.stem == stem:
            return path
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Package the RAG data bundle")
    parser.add_argument("--version",    required=True, help="Bundle version, e.g. v1.0.0")
    parser.add_argument("--embeddings", default=str(DEFAULT_EMBEDDINGS))
    parser.add_argument("--chunks",     default=str(DEFAULT_CHUNKS))
    parser.add_argument("--output-dir", default=None,
                        help="Parent directory for the bundle (default: project root)")
    args = parser.parse_args()

    embeddings_path = Path(args.embeddings)
    chunks_path     = Path(args.chunks)
    version         = args.version
    output_parent   = Path(args.output_dir) if args.output_dir else PROJECT_ROOT
    bundle_dir      = output_parent / f"rag-bundle-{version}"

    # Validate inputs
    for label, path in [("embeddings", embeddings_path), ("chunks", chunks_path)]:
        if not path.exists():
            sys.exit(f"ERROR: {label} file not found: {path}")

    print(f"Bundle version: {version}")
    print(f"Embeddings:     {embeddings_path}")
    print(f"Chunks:         {chunks_path}")
    print(f"Output dir:     {bundle_dir}")
    print()

    # Collect SOURCE ids from chunk file
    print("Scanning chunk file for SOURCE ids... ", end="", flush=True)
    source_ids = collect_source_ids(chunks_path)
    chunk_count = count_chunks(chunks_path)
    print(f"{len(source_ids)} unique sources, {chunk_count} chunks.")

    # Build SOURCE -> PDF mapping
    print("Resolving SOURCE ids to raw PDFs...")
    source_to_pdf: dict[str, Path] = {}
    missing: list[str] = []
    for sid in sorted(source_ids):
        pdf = find_pdf_for_stem(sid)
        if pdf:
            source_to_pdf[sid] = pdf
        else:
            missing.append(sid)

    if missing:
        print(f"\nERROR: {len(missing)} SOURCE id(s) have no matching PDF:")
        for s in missing:
            print(f"  {repr(s)}")
        sys.exit(1)

    print(f"  All {len(source_ids)} sources resolved.")

    # Check for normalisation collisions
    norm_names = [normalize_source_id(sid) for sid in source_ids]
    if len(norm_names) != len(set(norm_names)):
        dupes = {n for n in norm_names if norm_names.count(n) > 1}
        sys.exit(f"ERROR: normalisation collision(s): {dupes}")

    # Create bundle directory structure
    if bundle_dir.exists():
        print(f"\nBundle dir already exists — removing: {bundle_dir}")
        shutil.rmtree(bundle_dir)

    runtime_dir = bundle_dir / "runtime"
    debug_dir   = bundle_dir / "debug"
    docs_dir    = bundle_dir / "docs"
    for d in [runtime_dir, debug_dir, docs_dir]:
        d.mkdir(parents=True)

    # Copy runtime assets
    print("\nCopying runtime/embeddings.sqlite... ", end="", flush=True)
    shutil.copy2(embeddings_path, runtime_dir / "embeddings.sqlite")
    print("done.")

    # Copy debug assets
    print("Copying debug/chunks_for_rag.txt... ", end="", flush=True)
    shutil.copy2(chunks_path, debug_dir / "chunks_for_rag.txt")
    print("done.")

    # Copy and normalize PDFs
    print(f"Copying {len(source_to_pdf)} PDFs to docs/...")
    doc_entries: list[dict] = []
    already_copied: set[str] = set()

    for sid in sorted(source_to_pdf):
        src_pdf = source_to_pdf[sid]
        norm    = normalize_source_id(sid)
        dest    = docs_dir / f"{norm}.pdf"

        if norm in already_copied:
            # Duplicate physical file (different directory, same stem) — skip
            print(f"  [skip dup]  {sid}")
            continue
        already_copied.add(norm)

        shutil.copy2(src_pdf, dest)
        size = dest.stat().st_size
        sha  = sha256_file(dest)
        doc_entries.append({
            "source_id":   sid,
            "normalized_id": norm,
            "bundle_path": f"docs/{norm}.pdf",
            "file_size":   size,
            "sha256":      sha,
        })
        changed = " (renamed)" if norm != sid else ""
        print(f"  {norm}.pdf{changed}")

    # Compute artifact checksums
    print("\nComputing checksums...")
    artifacts: list[dict] = []
    for rel, abs_path in [
        ("runtime/embeddings.sqlite", runtime_dir / "embeddings.sqlite"),
        ("debug/chunks_for_rag.txt",  debug_dir   / "chunks_for_rag.txt"),
    ]:
        sha  = sha256_file(abs_path)
        size = abs_path.stat().st_size
        artifacts.append({"path": rel, "file_size": size, "sha256": sha})
        print(f"  {rel}  {sha[:16]}...")

    # Write manifest.json
    manifest = {
        "schema_version": 1,
        "bundle_version": version,
        "producer_repo":  "mamai-medical-guidelines",
        "producer_commit": git_commit(),
        "chunk_count":    chunk_count,
        "source_count":   len(doc_entries),
        "embedding": {
            "model":      "Gecko_1024_quant (TFLite)",
            "dimensions": 768,
            "blob_format": "VF32",
            "blob_bytes":  3076,
        },
        "source_id_contract": {
            "format":           "chunk SOURCE stem",
            "pdf_naming":       "<normalized_source_id>.pdf",
            "normalization":    "re.sub(r'[^A-Za-z0-9\\-.]', '_', stem) -> collapse '_+' -> strip edges",
            "page_index_base":  1,
        },
        "artifacts": artifacts,
        "documents": doc_entries,
    }

    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote manifest.json  ({manifest_path.stat().st_size} bytes)")

    # Write checksums.sha256
    checksum_lines: list[str] = []
    for entry in artifacts:
        checksum_lines.append(f"{entry['sha256']}  {entry['path']}")
    for doc in doc_entries:
        checksum_lines.append(f"{doc['sha256']}  {doc['bundle_path']}")
    checksum_lines.append(f"{sha256_file(manifest_path)}  manifest.json")

    checksums_path = bundle_dir / "checksums.sha256"
    checksums_path.write_text("\n".join(checksum_lines) + "\n")
    print(f"Wrote checksums.sha256  ({len(checksum_lines)} entries)")

    # Summary
    total_size = sum(f.stat().st_size for f in bundle_dir.rglob("*") if f.is_file())
    print(f"\nBundle:       {bundle_dir}")
    print(f"Total size:   {total_size / (1024 * 1024):.1f} MB")
    print(f"PDFs:         {len(doc_entries)}")
    print(f"Chunks:       {chunk_count}")

    # Create tarball with macOS metadata disabled so ._* / __MACOSX entries are
    # never included.  COPYFILE_DISABLE=1 is a no-op on Linux.
    tarball_name = f"rag-bundle-{version}.tar.gz"
    tarball_path = bundle_dir.parent / tarball_name
    print(f"\nCreating {tarball_path} ...")
    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"
    subprocess.run(
        ["tar", "-czf", str(tarball_path), bundle_dir.name],
        cwd=str(bundle_dir.parent),
        env=env,
        check=True,
    )

    # Validate: reject any AppleDouble / macOS metadata entries
    bad_pattern = re.compile(r"(^|/)\._|(^|/)\.DS_Store$|^__MACOSX/")
    result = subprocess.run(
        ["tar", "-tzf", str(tarball_path)],
        capture_output=True, text=True, check=True,
    )
    bad_entries = [line for line in result.stdout.splitlines() if bad_pattern.search(line)]
    if bad_entries:
        raise RuntimeError(
            f"Tarball contains macOS metadata entries — rebuild failed:\n"
            + "\n".join(f"  {e}" for e in bad_entries)
        )

    tarball_sha256 = sha256_file(tarball_path)
    tarball_size_mb = tarball_path.stat().st_size / (1024 * 1024)
    print(f"Tarball:      {tarball_path}  ({tarball_size_mb:.1f} MB)")
    print(f"SHA-256:      {tarball_sha256}")
    print(f"Validated:    no macOS metadata entries found")

    print(f"\nNext steps:")
    print(f"  1. Review {bundle_dir}/manifest.json")
    print(f"  2. gh release create {version} {tarball_path} \\")
    print(f"       --repo nmrenyi/mamai-medical-guidelines \\")
    print(f"       --title 'RAG Bundle {version}' --notes '...'")
    print(f"  3. Update rag-assets.lock.json in the mamai consumer repo")


if __name__ == "__main__":
    main()
