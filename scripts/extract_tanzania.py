"""
Extract Tanzania/Zanzibar guideline PDFs to markdown.

Walks raw/Clinical guidelines_Zanzibar-Tanzania/, processes PDFs only.
Non-PDF files (.doc, .docx, .xlsx) are skipped.

Output goes to processed/markdown/tanzania/.

Usage:
    python scripts/extract_tanzania.py              # default 3 workers
    python scripts/extract_tanzania.py --workers 4
    python scripts/extract_tanzania.py --force      # re-extract even if output exists
"""

import argparse
import os
import re
import sys
from multiprocessing import Process, Queue
from pathlib import Path

# Redirect marker-pdf's font cache to a writable location
os.environ.setdefault("FONT_DIR", "/tmp/marker-fonts")
os.environ.setdefault("FONT_PATH", "/tmp/marker-fonts/GoNotoCurrent-Regular.ttf")

sys.path.insert(0, str(Path(__file__).parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "raw" / "Clinical guidelines_Zanzibar-Tanzania"
OUTPUT_DIR = PROJECT_ROOT / "processed" / "extracted" / "tanzania"

# marker-pdf embeds {N}-{48 dashes} as physical page boundary markers when
# paginate_output=True (e.g. "{0}------------------------------------------------").
_CURLY_PAGE = re.compile(r"^\{(\d+)\}-{48}$", re.MULTILINE)


def collect_pdfs(force: bool = False) -> list[Path]:
    """Walk RAW_DIR and collect all PDFs, skipping already-processed ones."""
    pdfs = []
    for root, _dirs, files in os.walk(RAW_DIR):
        for f in sorted(files):
            path = Path(root) / f
            if path.suffix.lower() != ".pdf":
                continue
            out = OUTPUT_DIR / f"{path.stem}.md"
            if out.exists() and not force:
                print(f"  SKIP (already done): {f}")
                continue
            pdfs.append(path)
    return pdfs


def normalize_page_markers(text: str) -> str:
    """Replace marker-pdf's {N} page markers with <!-- page: N+1 --> comments."""
    return _CURLY_PAGE.sub(lambda m: f"<!-- page: {int(m.group(1)) + 1} -->", text)


def pdf_worker_fn(worker_id: int, pdf_paths: list, output_dir: Path, progress_queue: Queue):
    """Worker process: loads its own marker-pdf model and processes its share of PDFs."""
    from marker.models import create_model_dict
    from marker.converters.pdf import PdfConverter

    config = {"paginate_output": True, "extract_images": False}
    model_dict = create_model_dict()
    converter = PdfConverter(artifact_dict=model_dict, config=config)

    for pdf_path in pdf_paths:
        out = output_dir / f"{pdf_path.stem}.md"
        try:
            rendered = converter(str(pdf_path))
            markdown = normalize_page_markers(rendered.markdown)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown, encoding="utf-8")
            progress_queue.put(("OK", worker_id, pdf_path.name))
        except Exception as e:
            progress_queue.put(("ERROR", worker_id, f"{pdf_path.name}: {e}"))


def main():
    parser = argparse.ArgumentParser(
        description="Extract Tanzania/Zanzibar guideline PDFs to markdown"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Number of parallel workers (default: 3, ~4GB RAM each)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if output already exists",
    )
    args = parser.parse_args()

    print(f"Source: {RAW_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    print("Collecting PDFs...")
    pdfs = collect_pdfs(force=args.force)
    print(f"Found {len(pdfs)} PDFs to process.\n")

    if not pdfs:
        print("Nothing to process.")
        sys.exit(0)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    n_workers = min(args.workers, len(pdfs))
    print(f"Extracting {len(pdfs)} PDF(s) with {n_workers} worker(s)...")

    chunks: list[list] = [[] for _ in range(n_workers)]
    for i, pdf in enumerate(pdfs):
        chunks[i % n_workers].append(pdf)

    progress_queue: Queue = Queue()
    processes = []
    for worker_id, chunk in enumerate(chunks):
        if not chunk:
            continue
        p = Process(
            target=pdf_worker_fn,
            args=(worker_id, chunk, OUTPUT_DIR, progress_queue),
        )
        p.start()
        processes.append(p)

    done = errors = 0
    total = len(pdfs)
    while done + errors < total:
        status, worker_id, msg = progress_queue.get()
        if status == "OK":
            done += 1
            print(f"  [{done + errors}/{total}] Worker {worker_id}: {msg}")
        else:
            errors += 1
            print(f"  [{done + errors}/{total}] Worker {worker_id} ERROR: {msg}")

    for p in processes:
        p.join()

    print(f"\nDone. {done} succeeded, {errors} failed. Output in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
