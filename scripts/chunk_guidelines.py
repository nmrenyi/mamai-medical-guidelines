"""
chunk_guidelines.py — Chunk normalized guideline markdowns for RAG ingestion.

The default strategy is structure-first:
1. Parse markdown into heading-aware sections while tracking page markers as
   metadata.
2. Emit one chunk per section when the section is reasonably sized.
3. Subdivide only oversized sections, preferring block boundaries (paragraphs,
   lists, tables) before falling back to overlapping text windows.

The legacy page-first strategy is still available via --strategy legacy for
comparison. Both strategies write the same <sep>-delimited output format:

    <sep>[SOURCE:WHO_PositiveBirth_2018|PAGE:42]
    chunk content...

That keeps the output compatible with Android's memorizeChunks() and with
build_embeddings.py.
"""

import argparse
import json
import re
from dataclasses import dataclass
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

# Only HIGH-relevance files are included by default (see
# processed/guideline_relevance_summary.md). Add MEDIUM-relevance stems here
# if you want broader coverage.
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

# Minimum chunk character length — shorter chunks are discarded.
MIN_CHUNK_CHARS = 80

# Let full sections stay intact up to this length before subdividing them into
# smaller retrieval chunks. This is intentionally larger than CHUNK_SIZE so a
# complete recommendation block can survive as one coherent chunk.
DEFAULT_MAX_SECTION_CHARS = 1500

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BOLD_ONLY_RE = re.compile(r"^\*\*(.+?)\*\*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
EMPHASIS_RE = re.compile(r"[*_`~]+")

BOILERPLATE_HEADING_PATTERNS = (
    "contents",
    "table of contents",
    "acknowledg",
    "glossary",
    "acronym",
    "abbreviat",
    "references",
    "bibliography",
    "foreword",
    "preface",
    "disclaimer",
    "list participants",
)


@dataclass
class LineSpan:
    text: str
    page: int


@dataclass
class Section:
    source: str
    section_id: str
    heading_raw: str | None
    heading_text: str | None
    heading_level: int | None
    heading_path: tuple[str, ...]
    page_start: int
    page_end: int
    body_lines: list[LineSpan]

    def render(self) -> str:
        parts: list[str] = []
        if self.heading_raw:
            parts.append(self.heading_raw)
        body = "\n".join(line.text for line in self.body_lines).strip()
        if body:
            parts.append(body)
        return "\n\n".join(parts).strip()

    def body_text(self) -> str:
        return "\n".join(line.text for line in self.body_lines).strip()


@dataclass
class Block:
    text: str
    block_type: str
    page_start: int
    page_end: int


@dataclass
class Chunk:
    chunk_id: str
    source: str
    text: str
    page_start: int
    page_end: int
    section_id: str | None
    section_path: tuple[str, ...]
    chunk_type: str
    strategy: str

    def prefixed_text(self) -> str:
        return f"[SOURCE:{self.source}|PAGE:{self.page_start}]\n{self.text}"


def strip_inline_markdown(text: str) -> str:
    """Best-effort normalization for filtering and sidecar metadata."""
    text = LINK_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = EMPHASIS_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_heading_text(text: str) -> str:
    return strip_inline_markdown(text).strip(": ").lower()


def looks_like_heading_text(text: str) -> bool:
    text = strip_inline_markdown(text)
    if not text or len(text) > 160:
        return False
    if text.endswith((".", ";", "?", "!")):
        return False
    words = text.split()
    if len(words) < 3 or len(words) > 18:
        return False
    return True


def is_table_line(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def classify_line(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "blank"
    if is_table_line(stripped):
        return "table"
    if LIST_ITEM_RE.match(text):
        return "list"
    return "paragraph"


def load_markdown_lines(text: str) -> list[LineSpan]:
    """Return markdown lines with page metadata, excluding page marker lines."""
    current_page = 1
    lines: list[LineSpan] = []

    for raw_line in text.splitlines():
        marker = PAGE_MARKER.match(raw_line.strip())
        if marker:
            current_page = int(marker.group(1))
            continue
        lines.append(LineSpan(text=raw_line.rstrip("\n"), page=current_page))

    return lines


def detect_heading(line: LineSpan) -> tuple[int, str, str] | None:
    stripped = line.text.strip()
    if not stripped:
        return None

    match = ATX_HEADING_RE.match(stripped)
    if match:
        level = len(match.group(1))
        heading_text = strip_inline_markdown(match.group(2))
        return level, stripped, heading_text

    match = BOLD_ONLY_RE.match(stripped)
    if match and looks_like_heading_text(match.group(1)):
        heading_text = strip_inline_markdown(match.group(1))
        # Use a mid-level synthetic depth. Splitting matters more than exact
        # depth, but retaining an ordered level still gives us a path.
        return 3, stripped, heading_text

    return None


def split_into_pages(text: str) -> list[tuple[int, str]]:
    """Legacy page-first splitter kept for compatibility and comparison."""
    pages = []
    current_page = 1
    current_content: list[str] = []

    for line in text.splitlines():
        marker = PAGE_MARKER.match(line.strip())
        if marker:
            content = "\n".join(current_content).strip()
            if content:
                pages.append((current_page, content))
            current_page = int(marker.group(1))
            current_content = []
        else:
            current_content.append(line)

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

        break_pos = end
        for sep in separators:
            pos = text.rfind(sep, start + overlap, end)
            if pos != -1:
                break_pos = pos + len(sep)
                break

        chunk = text[start:break_pos].strip()
        if chunk:
            chunks.append(chunk)

        start = max(start + 1, break_pos - overlap)

    return chunks


def parse_sections(md_path: Path) -> list[Section]:
    """Parse a markdown file into heading-aware sections with page metadata."""
    lines = load_markdown_lines(md_path.read_text(encoding="utf-8"))
    sections: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    current: Section | None = None
    section_index = 0

    def finalize_current() -> None:
        nonlocal current
        if current is None:
            return
        body_has_text = any(line.text.strip() for line in current.body_lines)
        if current.heading_raw or body_has_text:
            sections.append(current)
        current = None

    for line in lines:
        heading = detect_heading(line)
        if heading:
            finalize_current()
            level, heading_raw, heading_text = heading
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
            section_index += 1
            current = Section(
                source=md_path.stem,
                section_id=f"{md_path.stem}:section:{section_index:04d}",
                heading_raw=heading_raw,
                heading_text=heading_text,
                heading_level=level,
                heading_path=tuple(text for _, text in heading_stack),
                page_start=line.page,
                page_end=line.page,
                body_lines=[],
            )
            continue

        if current is None:
            if not line.text.strip():
                continue
            section_index += 1
            current = Section(
                source=md_path.stem,
                section_id=f"{md_path.stem}:section:{section_index:04d}",
                heading_raw=None,
                heading_text=None,
                heading_level=None,
                heading_path=tuple(),
                page_start=line.page,
                page_end=line.page,
                body_lines=[],
            )

        current.body_lines.append(line)
        if line.text.strip():
            current.page_end = line.page

    finalize_current()
    return sections


def looks_like_table_of_contents(text: str) -> bool:
    plain = strip_inline_markdown(text).lower()
    if "table of contents" in plain:
        return True

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        return False

    tocish = 0
    for line in lines:
        stripped = strip_inline_markdown(line)
        if re.search(r"\b\d+\s*$", stripped):
            tocish += 1
        elif line.strip().startswith("|") and re.search(r"\|\s*[\divxlcdmIVXLCDM]+\s*\|\s*$", line):
            tocish += 1

    return tocish >= max(4, len(lines) // 2)


def should_skip_section(section: Section) -> bool:
    """Skip only obvious boilerplate sections; keep the rest intact."""
    if section.heading_text:
        normalized = normalize_heading_text(section.heading_text)
        if any(pattern in normalized for pattern in BOILERPLATE_HEADING_PATTERNS):
            return True

    rendered = section.render()
    if not rendered:
        return True

    if looks_like_table_of_contents(rendered):
        return True

    return False


def split_section_into_blocks(section: Section) -> list[Block]:
    """Split a section body into block-aware units for chunk assembly."""
    blocks: list[Block] = []
    lines = section.body_lines
    i = 0

    while i < len(lines):
        kind = classify_line(lines[i].text)
        if kind == "blank":
            i += 1
            continue

        start = i
        if kind == "table":
            while i < len(lines) and classify_line(lines[i].text) == "table":
                i += 1
        elif kind == "list":
            i += 1
            while i < len(lines):
                next_kind = classify_line(lines[i].text)
                if next_kind == "blank" or next_kind == "table":
                    break
                if LIST_ITEM_RE.match(lines[i].text) or lines[i].text.startswith((" ", "\t")):
                    i += 1
                    continue
                # List item continuation line.
                i += 1
        else:
            while i < len(lines):
                next_kind = classify_line(lines[i].text)
                if next_kind in {"blank", "table", "list"}:
                    break
                i += 1

        block_lines = lines[start:i]
        block_text = "\n".join(line.text for line in block_lines).strip()
        if not block_text:
            continue
        blocks.append(
            Block(
                text=block_text,
                block_type=kind,
                page_start=block_lines[0].page,
                page_end=block_lines[-1].page,
            )
        )

    return blocks


def render_chunk_body(heading_raw: str | None, body_text: str) -> str:
    parts: list[str] = []
    if heading_raw:
        parts.append(heading_raw)
    if body_text.strip():
        parts.append(body_text.strip())
    return "\n\n".join(parts).strip()


def build_breadcrumb(section: Section) -> str | None:
    """Return a '> Parent > Child' breadcrumb for ancestor headings, or None if top-level."""
    parents = section.heading_path[:-1]
    if not parents:
        return None
    return "> " + " > ".join(parents)


def prepend_breadcrumb(section: Section, text: str) -> str:
    """Prepend the parent heading path to chunk text so each chunk is self-contained."""
    breadcrumb = build_breadcrumb(section)
    if not breadcrumb:
        return text
    return breadcrumb + "\n\n" + text


def split_table_block(block: Block, max_chars: int) -> list[Block]:
    """Split a large markdown table into row groups while repeating the header."""
    lines = [line for line in block.text.splitlines() if line.strip()]
    if len(lines) < 3:
        return [block]

    header_lines = lines[:2]
    row_lines = lines[2:]
    pieces: list[Block] = []
    current_rows: list[str] = []
    current_start = block.page_start

    def flush() -> None:
        nonlocal current_rows, current_start
        if not current_rows:
            return
        text = "\n".join(header_lines + current_rows)
        pieces.append(
            Block(
                text=text,
                block_type="table",
                page_start=current_start,
                page_end=block.page_end,
            )
        )
        current_rows = []

    for row in row_lines:
        candidate_rows = current_rows + [row]
        candidate_text = "\n".join(header_lines + candidate_rows)
        if current_rows and len(candidate_text) > max_chars:
            flush()
            current_start = block.page_start
        current_rows.append(row)

    flush()
    return pieces or [block]


def split_list_block(block: Block, chunk_size: int) -> list[Block]:
    """Split a large list block by top-level items before falling back further."""
    lines = block.text.splitlines()
    if not lines:
        return []

    items: list[list[str]] = []
    current_item: list[str] = []
    for line in lines:
        if LIST_ITEM_RE.match(line) and current_item:
            items.append(current_item)
            current_item = [line]
        else:
            current_item.append(line)
    if current_item:
        items.append(current_item)

    pieces: list[Block] = []
    current_lines: list[str] = []
    for item in items:
        candidate = current_lines + item
        candidate_text = "\n".join(candidate).strip()
        if current_lines and len(candidate_text) > chunk_size:
            pieces.append(
                Block(
                    text="\n".join(current_lines).strip(),
                    block_type="list",
                    page_start=block.page_start,
                    page_end=block.page_end,
                )
            )
            current_lines = list(item)
        else:
            current_lines = candidate

    if current_lines:
        pieces.append(
            Block(
                text="\n".join(current_lines).strip(),
                block_type="list",
                page_start=block.page_start,
                page_end=block.page_end,
            )
        )

    return pieces or [block]


def split_block(block: Block, chunk_size: int, overlap: int) -> list[Block]:
    """Split an oversized block without immediately falling back to word windows."""
    if len(block.text) <= chunk_size:
        return [block]
    if block.block_type == "table":
        return split_table_block(block, chunk_size)
    if block.block_type == "list":
        return split_list_block(block, chunk_size)

    pieces = chunk_text(block.text, chunk_size, overlap)
    return [
        Block(
            text=piece,
            block_type=block.block_type,
            page_start=block.page_start,
            page_end=block.page_end,
        )
        for piece in pieces
    ]


def make_chunk(
    source: str,
    text: str,
    page_start: int,
    page_end: int,
    section: Section | None,
    chunk_type: str,
    strategy: str,
    index: int,
) -> Chunk | None:
    text = text.strip()
    if len(text) < MIN_CHUNK_CHARS:
        return None
    return Chunk(
        chunk_id=f"{source}:chunk:{index:05d}",
        source=source,
        text=text,
        page_start=page_start,
        page_end=page_end,
        section_id=section.section_id if section else None,
        section_path=section.heading_path if section else tuple(),
        chunk_type=chunk_type,
        strategy=strategy,
    )


def chunk_section(
    section: Section,
    chunk_size: int,
    overlap: int,
    max_section_chars: int,
    strategy: str,
    chunk_index_start: int,
) -> tuple[list[Chunk], int]:
    rendered = section.render()
    if should_skip_section(section):
        return [], chunk_index_start

    if len(rendered) <= max_section_chars:
        chunk = make_chunk(
            source=section.source,
            text=prepend_breadcrumb(section, rendered),
            page_start=section.page_start,
            page_end=section.page_end,
            section=section,
            chunk_type="section",
            strategy=strategy,
            index=chunk_index_start,
        )
        return ([chunk] if chunk else []), chunk_index_start + (1 if chunk else 0)

    blocks = split_section_into_blocks(section)
    if not blocks:
        chunk = make_chunk(
            source=section.source,
            text=prepend_breadcrumb(section, rendered),
            page_start=section.page_start,
            page_end=section.page_end,
            section=section,
            chunk_type="section",
            strategy=strategy,
            index=chunk_index_start,
        )
        return ([chunk] if chunk else []), chunk_index_start + (1 if chunk else 0)

    expanded_blocks: list[Block] = []
    for block in blocks:
        expanded_blocks.extend(split_block(block, chunk_size, overlap))

    chunks: list[Chunk] = []
    current_texts: list[str] = []
    current_types: set[str] = set()
    current_page_start: int | None = None
    current_page_end: int | None = None
    next_index = chunk_index_start

    def flush_current() -> None:
        nonlocal current_texts, current_types, current_page_start, current_page_end, next_index
        if not current_texts or current_page_start is None or current_page_end is None:
            return
        body = "\n\n".join(current_texts).strip()
        chunk_text_body = prepend_breadcrumb(section, render_chunk_body(section.heading_raw, body))
        chunk_type = current_types.pop() if len(current_types) == 1 else "mixed"
        chunk = make_chunk(
            source=section.source,
            text=chunk_text_body,
            page_start=current_page_start,
            page_end=current_page_end,
            section=section,
            chunk_type=chunk_type,
            strategy=strategy,
            index=next_index,
        )
        if chunk:
            chunks.append(chunk)
            next_index += 1
        current_texts = []
        current_types = set()
        current_page_start = None
        current_page_end = None

    for block in expanded_blocks:
        block_text = block.text.strip()
        if not block_text:
            continue

        candidate_body = "\n\n".join(current_texts + [block_text]).strip()
        candidate_text = render_chunk_body(section.heading_raw, candidate_body)

        if current_texts and len(candidate_text) > chunk_size:
            flush_current()

        if current_page_start is None:
            current_page_start = block.page_start
        current_page_end = block.page_end
        current_texts.append(block_text)
        current_types.add(block.block_type)

        # If a single block already exceeds the target size, keep it isolated.
        solo_text = render_chunk_body(section.heading_raw, block_text)
        if len(current_texts) == 1 and len(solo_text) >= chunk_size:
            flush_current()

    flush_current()
    return chunks, next_index


def process_file_legacy(
    md_path: Path,
    chunk_size: int,
    overlap: int,
    chunk_index_start: int,
) -> tuple[list[Chunk], int]:
    """Legacy page-first chunker preserved for side-by-side comparisons."""
    pages = split_into_pages(md_path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    next_index = chunk_index_start

    for page_num, page_content in pages:
        for piece in chunk_text(page_content, chunk_size, overlap):
            chunk = make_chunk(
                source=md_path.stem,
                text=piece,
                page_start=page_num,
                page_end=page_num,
                section=None,
                chunk_type="page",
                strategy="legacy",
                index=next_index,
            )
            if chunk:
                chunks.append(chunk)
                next_index += 1

    return chunks, next_index


def process_file_structured(
    md_path: Path,
    chunk_size: int,
    overlap: int,
    max_section_chars: int,
    chunk_index_start: int,
) -> tuple[list[Chunk], int]:
    sections = parse_sections(md_path)
    chunks: list[Chunk] = []
    next_index = chunk_index_start

    for section in sections:
        section_chunks, next_index = chunk_section(
            section=section,
            chunk_size=chunk_size,
            overlap=overlap,
            max_section_chars=max_section_chars,
            strategy="structured",
            chunk_index_start=next_index,
        )
        chunks.extend(section_chunks)

    return chunks, next_index


def collect_files(project_root: Path, include_all: bool) -> tuple[list[Path], list[tuple[Path, str]]]:
    intl_dir = project_root / "processed" / "normalized" / "international"
    tanzania_dir = project_root / "processed" / "normalized" / "tanzania"

    intl_files = sorted(intl_dir.glob("*.md")) if intl_dir.exists() else []
    tanzania_files = sorted(tanzania_dir.glob("*.md")) if tanzania_dir.exists() else []

    to_process: list[Path] = []
    to_skip: list[tuple[Path, str]] = []

    for md_path in intl_files:
        stem = md_path.stem
        if stem in SKIP_FILES:
            to_skip.append((md_path, "duplicate"))
        elif not include_all and stem not in HIGH_RELEVANCE:
            to_skip.append((md_path, "not HIGH"))
        else:
            to_process.append(md_path)

    for md_path in tanzania_files:
        stem = md_path.stem
        if stem in SKIP_FILES:
            to_skip.append((md_path, "duplicate"))
        else:
            to_process.append(md_path)

    return to_process, to_skip


def write_output(chunks: list[Chunk], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            metadata_line, body = chunk.prefixed_text().split("\n", 1)
            handle.write(f"<sep>{metadata_line}\n{body}\n")


def write_sidecar(chunks: list[Chunk], sidecar_path: Path) -> None:
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    with sidecar_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            record = {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_id": chunk.section_id,
                "section_path": list(chunk.section_path),
                "chunk_type": chunk.chunk_type,
                "strategy": chunk.strategy,
                "text": chunk.text,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize_chunks(chunks: list[Chunk], output_path: Path) -> None:
    total_chars = sum(len(chunk.text) for chunk in chunks)
    avg_chars = total_chars // len(chunks) if chunks else 0

    print(f"\nOutput: {output_path}")
    print(f"Total chunks: {len(chunks)}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk guidelines for RAG")
    parser.add_argument(
        "--output",
        default="processed/chunks_for_rag.txt",
        help="Output path (default: processed/chunks_for_rag.txt)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=800,
        help="Target max characters per emitted chunk (default: 800)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=100,
        help="Overlap characters for fallback window splits (default: 100)",
    )
    parser.add_argument(
        "--max-section-chars",
        type=int,
        default=DEFAULT_MAX_SECTION_CHARS,
        help="Allow whole sections up to this size before subdividing (default: 1500)",
    )
    parser.add_argument(
        "--strategy",
        choices=("structured", "legacy"),
        default="structured",
        help="Chunking strategy to use (default: structured)",
    )
    parser.add_argument(
        "--jsonl-sidecar",
        help="Optional JSONL sidecar path for richer chunk metadata",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include all files, not just HIGH-relevance ones",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / args.output
    sidecar_path = (project_root / args.jsonl_sidecar) if args.jsonl_sidecar else None

    to_process, to_skip = collect_files(project_root, include_all=args.all)
    if not to_process:
        print("No markdown files found in processed/normalized.")
        return

    total = len(to_process)
    bar_width = 30
    all_chunks: list[Chunk] = []
    next_chunk_index = 1

    for i, md_path in enumerate(to_process, start=1):
        filled = int(bar_width * i / total)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"\r[{bar}] {i}/{total}  {md_path.stem[:40]:<40}", end="", flush=True)

        if args.strategy == "legacy":
            chunks, next_chunk_index = process_file_legacy(
                md_path=md_path,
                chunk_size=args.chunk_size,
                overlap=args.overlap,
                chunk_index_start=next_chunk_index,
            )
        else:
            chunks, next_chunk_index = process_file_structured(
                md_path=md_path,
                chunk_size=args.chunk_size,
                overlap=args.overlap,
                max_section_chars=args.max_section_chars,
                chunk_index_start=next_chunk_index,
            )

        all_chunks.extend(chunks)
        print(f"\r  [{i:>2}/{total}] {md_path.name:<45} {len(chunks):>4} chunks")

    if to_skip:
        print(f"\nSkipped ({len(to_skip)} files):")
        for md_path, reason in to_skip:
            print(f"  {reason:<12}  {md_path.name}")

    if not all_chunks:
        print("\nNo chunks produced — check that markdown files exist.")
        return

    write_output(all_chunks, output_path)
    if sidecar_path is not None:
        write_sidecar(all_chunks, sidecar_path)
        print(f"Metadata sidecar: {sidecar_path}")

    summarize_chunks(all_chunks, output_path)


if __name__ == "__main__":
    main()
