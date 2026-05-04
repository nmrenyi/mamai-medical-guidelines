"""
Extract a directory of PDFs to markdown using marker-pdf.

Generic extraction script — no hardcoded paths or exclusion lists.
All PDFs found in --input-dir are extracted. Files whose output already
exists are skipped unless --force is given.

Usage:
    python scripts/extract_dir.py --input-dir raw/open-books --output-dir processed/extracted/international
    python scripts/extract_dir.py --input-dir raw/exams --output-dir processed/extracted/international
    python scripts/extract_dir.py --input-dir raw/whole-books --output-dir processed/extracted/international --workers 4
    python scripts/extract_dir.py --input-dir raw/open-books --output-dir processed/extracted/international --force
"""

import argparse
import re
from multiprocessing import Process, Queue
from pathlib import Path

_CURLY_PAGE = re.compile(r"^\{(\d+)\}-{48}$", re.MULTILINE)


def normalize_page_markers(text: str) -> str:
    return _CURLY_PAGE.sub(lambda m: f"<!-- page: {int(m.group(1)) + 1} -->", text)


def collect_pdfs(input_dir: Path, output_dir: Path, force: bool) -> list[Path]:
    pdfs = []
    for pdf in sorted(input_dir.glob("*.pdf")):
        out = output_dir / f"{pdf.stem}.md"
        if out.exists() and not force:
            print(f"  SKIP (already extracted): {pdf.name}")
            continue
        pdfs.append(pdf)
    return pdfs


def worker_fn(worker_id: int, pdf_paths: list[Path], output_dir: Path, progress_queue: Queue):
    from marker.models import create_model_dict
    from marker.converters.pdf import PdfConverter

    config = {"paginate_output": True, "extract_images": False}
    model_dict = create_model_dict()
    converter = PdfConverter(artifact_dict=model_dict, config=config)

    for pdf_path in pdf_paths:
        output_path = output_dir / f"{pdf_path.stem}.md"
        try:
            rendered = converter(str(pdf_path))
            markdown = normalize_page_markers(rendered.markdown)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding="utf-8")
            progress_queue.put(("OK", worker_id, pdf_path.name))
        except Exception as e:
            progress_queue.put(("ERROR", worker_id, f"{pdf_path.name}: {e}"))


def main():
    parser = argparse.ArgumentParser(description="Extract a directory of PDFs to markdown")
    parser.add_argument("--input-dir", required=True, help="Directory containing PDFs to extract")
    parser.add_argument("--output-dir", required=True, help="Directory to write .md files into")
    parser.add_argument("--workers", type=int, default=3, help="Parallel worker count (default: 3)")
    parser.add_argument("--force", action="store_true", help="Re-extract even if output already exists")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    input_dir = Path(args.input_dir) if Path(args.input_dir).is_absolute() else project_root / args.input_dir
    output_dir = Path(args.output_dir) if Path(args.output_dir).is_absolute() else project_root / args.output_dir

    if not input_dir.exists():
        print(f"Error: input directory not found: {input_dir}")
        raise SystemExit(1)

    print(f"Input:   {input_dir}")
    print(f"Output:  {output_dir}")
    print(f"Workers: {args.workers}")
    print()

    print("Collecting PDFs...")
    pdfs = collect_pdfs(input_dir, output_dir, args.force)
    print(f"\nFound {len(pdfs)} PDFs to extract.\n")

    if not pdfs:
        print("Nothing to do.")
        return

    chunks: list[list[Path]] = [[] for _ in range(args.workers)]
    for i, pdf in enumerate(pdfs):
        chunks[i % args.workers].append(pdf)

    print(f"Launching {args.workers} workers...")
    progress_queue: Queue = Queue()
    processes = []
    for worker_id, chunk in enumerate(chunks):
        if not chunk:
            continue
        p = Process(target=worker_fn, args=(worker_id, chunk, output_dir, progress_queue))
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

    print(f"\nDone. {done} succeeded, {errors} failed. Output in {output_dir}")


if __name__ == "__main__":
    main()
