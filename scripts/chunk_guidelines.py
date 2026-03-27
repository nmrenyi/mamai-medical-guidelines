"""
chunk_guidelines.py — Chunk processed markdown guidelines for RAG ingestion.

Reads markdown files from processed/markdown/, splits content by page markers
first (so every chunk knows its source PDF page), then further splits large
pages into overlapping chunks. Each chunk is prefixed with structured metadata:

    [SOURCE:WHO_PositiveBirth_2018|PAGE:42]

Output is a <sep>-delimited text file compatible with Android's memorizeChunks()
in RagPipeline.kt. Copy the output to app/android/app/src/main/assets/mamai_trim.txt,
uncomment memorizeChunks() in RagPipeline.kt, run on device, then adb pull
the resulting embeddings.sqlite.

Usage:
    python scripts/chunk_guidelines.py
    python scripts/chunk_guidelines.py --output processed/chunks_for_rag.txt
    python scripts/chunk_guidelines.py --chunk-size 800 --overlap 100
"""

import argparse
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# File selection
# ---------------------------------------------------------------------------

# Executive summaries duplicate content from the full guidelines — skip them
# to avoid redundant retrieval hits.
SKIP_FILES = {
    "WHO_ANCExSummary_2016",       # duplicates WHO_ANC_2016
    "WHO_PositiveBirthExSum_2018", # duplicates WHO_PositiveBirth_2018
}

# Only HIGH-relevance files are included by default (see processed/guideline_relevance_summary.md).
# Add MEDIUM-relevance stems here if you want broader coverage.
HIGH_RELEVANCE = {
    # Preconception
    "ACOG_Preconcepcare_2019",
    "AJGP_Preconception_2024",
    # Antenatal
    "WHO_ANC_2016",
    "NICE_Antenatal_2021",
    "NICE_Nutrition_2025",
    "ACM_FetalMove_2017",
    "NHS_Fetal_2019",
    # Intrapartum
    "WHO_PositiveBirth_2018",
    "NICE_intrapartum_2023",
    "WHO_LabourCare_2020",
    "RCM_InductionLabour_2019",
    "AJOG_BirthPlan_2023",
    "WHO_Cord_2014",
    "WHO_Sepsis_2015",
    # Postnatal
    "NICE_Posnatal_2021",
    "WHO_PNC_2013",
    # Newborn
    "WHO_Neborn_2017",
    "ERC_NewbornResuscitation_2021",
    "enc-course-overview-09.05.2024",
    # Mental health
    "NICE_MentalHealth_2020",
    "RCM_MentalHealth_2015",
    # Comprehensive / cross-phase
    "WHO_IntegratedPregBirth_2015",
    "WHO_Complications_2017",
    "ICM_EssentialCompetencies_2024",
    "ACM_Referral_2021",
}

# Minimum chunk character length — shorter chunks are discarded (likely empty
# pages, copyright notices, or single-line headings with no clinical content).
MIN_CHUNK_CHARS = 80

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")


def split_into_pages(text: str) -> list[tuple[int, str]]:
    """Split markdown text into (page_number, content) pairs."""
    pages = []
    current_page = 1
    current_content: list[str] = []

    for line in text.splitlines():
        m = PAGE_MARKER.match(line.strip())
        if m:
            # Save whatever accumulated before this marker
            content = "\n".join(current_content).strip()
            if content:
                pages.append((current_page, content))
            current_page = int(m.group(1))
            current_content = []
        else:
            current_content.append(line)

    # Final page
    content = "\n".join(current_content).strip()
    if content:
        pages.append((current_page, content))

    return pages


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Split text into overlapping chunks, breaking at natural boundaries.
    Tries paragraph breaks, then line breaks, then sentence endings, then words.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    separators = ["\n\n", "\n", ". ", " "]

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Walk separators from coarsest to finest to find a clean break point
        break_pos = end
        for sep in separators:
            pos = text.rfind(sep, start + overlap, end)
            if pos != -1:
                break_pos = pos + len(sep)
                break

        chunk = text[start:break_pos].strip()
        if chunk:
            chunks.append(chunk)

        # Next chunk starts overlap chars before the break
        start = max(start + 1, break_pos - overlap)

    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_file(
    md_path: Path,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """
    Parse a single markdown file and return a list of prefixed chunk strings.
    Each chunk has the form:
        [SOURCE:stem|PAGE:N]\\nchunk content...
    """
    stem = md_path.stem
    text = md_path.read_text(encoding="utf-8")
    pages = split_into_pages(text)

    result: list[str] = []
    for page_num, page_content in pages:
        for chunk in chunk_text(page_content, chunk_size, overlap):
            if len(chunk) < MIN_CHUNK_CHARS:
                continue
            # Prefix with structured metadata on its own line so it's easy to
            # parse in RagPipeline.kt with a simple startsWith / regex check.
            prefixed = f"[SOURCE:{stem}|PAGE:{page_num}]\n{chunk}"
            result.append(prefixed)

    return result


def main():
    parser = argparse.ArgumentParser(description="Chunk guidelines for RAG")
    parser.add_argument(
        "--output",
        default="processed/chunks_for_rag.txt",
        help="Output path (default: processed/chunks_for_rag.txt)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=800,
        help="Max characters per chunk (default: 800)",
    )
    parser.add_argument(
        "--overlap", type=int, default=100,
        help="Overlap characters between chunks (default: 100)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Include all files, not just HIGH-relevance ones",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    intl_dir     = project_root / "processed" / "markdowns" / "international"
    tanzania_dir = project_root / "processed" / "markdowns" / "tanzania"
    output_path  = project_root / args.output

    intl_files     = sorted(intl_dir.glob("*.md"))     if intl_dir.exists()     else []
    tanzania_files = sorted(tanzania_dir.glob("*.md")) if tanzania_dir.exists() else []

    if not intl_files and not tanzania_files:
        print(f"No markdown files found in {intl_dir} or {tanzania_dir}")
        return

    # Pre-classify files so we know the total count for the progress bar
    to_process: list[Path] = []
    to_skip: list[tuple[Path, str]] = []

    # International files: filter to HIGH_RELEVANCE (unless --all), skip duplicates
    for md_path in intl_files:
        stem = md_path.stem
        if stem in SKIP_FILES:
            to_skip.append((md_path, "duplicate"))
        elif not args.all and stem not in HIGH_RELEVANCE:
            to_skip.append((md_path, "not HIGH"))
        else:
            to_process.append(md_path)

    # Tanzania files: always include all (no relevance filtering)
    for md_path in tanzania_files:
        stem = md_path.stem
        if stem in SKIP_FILES:
            to_skip.append((md_path, "duplicate"))
        else:
            to_process.append(md_path)

    total = len(to_process)
    bar_width = 30
    all_chunks: list[str] = []

    for i, md_path in enumerate(to_process, start=1):
        filled = int(bar_width * i / total)
        bar = "█" * filled + "░" * (bar_width - filled)
        # Print the progress line, overwriting the previous one
        print(f"\r[{bar}] {i}/{total}  {md_path.stem[:40]:<40}", end="", flush=True)

        chunks = process_file(md_path, args.chunk_size, args.overlap)
        all_chunks.extend(chunks)

        # Once done, print the final count for this file on a permanent line
        print(f"\r  [{i:>2}/{total}] {md_path.name:<45} {len(chunks):>4} chunks")

    if to_skip:
        print(f"\nSkipped ({len(to_skip)} files):")
        for md_path, reason in to_skip:
            print(f"  {reason:<12}  {md_path.name}")

    if not all_chunks:
        print("\nNo chunks produced — check that markdown files exist.")
        return

    # Write output: chunks separated by <sep> on its own line.
    # memorizeChunks() in RagPipeline.kt splits on lines that start with <sep>
    # and treats text after <sep> on the same line as the start of the new chunk.
    # We write the metadata prefix on the <sep> line itself:
    #
    #   <sep>[SOURCE:WHO_PositiveBirth_2018|PAGE:5]
    #    content line 1
    #    content line 2
    #
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            # First line of each prefixed chunk is "[SOURCE:...|PAGE:N]"
            lines = chunk.split("\n", 1)
            metadata_line = lines[0]   # [SOURCE:...|PAGE:N]
            body = lines[1] if len(lines) > 1 else ""
            f.write(f"<sep>{metadata_line}\n{body}\n")

    total_chars = sum(
        len(chunk.split("\n", 1)[1]) if "\n" in chunk else len(chunk)
        for chunk in all_chunks
    )
    avg_chars = total_chars // len(all_chunks) if all_chunks else 0

    print(f"\nOutput: {output_path}")
    print(f"Total chunks: {len(all_chunks)}")
    print(f"Avg chunk body size: {avg_chars} chars")
    print(f"Total output size: {output_path.stat().st_size / 1024:.1f} KB")
    print(
        "\nNext steps:"
        "\n  1. Copy output to app/android/app/src/main/assets/mamai_trim.txt"
        "\n  2. Uncomment memorizeChunks() in RagPipeline.kt"
        "\n  3. Build + run on device (embedding will run on first launch)"
        "\n  4. adb pull /sdcard/Android/data/com.example.app/files/embeddings.sqlite"
        "\n  5. Re-comment memorizeChunks()"
    )


if __name__ == "__main__":
    main()
