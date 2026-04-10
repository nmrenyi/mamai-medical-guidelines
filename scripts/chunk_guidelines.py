"""
chunk_guidelines.py — Chunk normalized guideline markdowns for RAG ingestion.

Strategy: structure-first.
1. Parse markdown into heading-aware sections while tracking page markers as
   metadata.
2. Emit one chunk per section when the section is reasonably sized.
3. Subdivide only oversized sections, preferring block boundaries (paragraphs,
   lists, tables) before falling back to overlapping text windows.

Output format (<sep>-delimited, compatible with Android's memorizeChunks()):

    <sep>[SOURCE:WHO_PositiveBirth_2018|PAGE:42]
    chunk content...
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


# Minimum chunk character length — shorter chunks are discarded.
MIN_CHUNK_CHARS = 80

# Hard upper bound on any emitted chunk. Text beyond this is split with
# overlapping windows before being stored. Gecko's token limit is 1024
# (~4000 chars at 4 chars/token); 2500 gives comfortable headroom.
MAX_CHUNK_CHARS = 2500

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
SUP_RE = re.compile(r"<sup[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
INTERNAL_LINK_RE = re.compile(r"\[([^\]]+)\]\(#[^)]*\)")
MANUAL_INDEX_REF_RE = re.compile(r"\b[A-Z]-\d+(?:[\-–]\d+)?\b")
# Body text that is purely a cross-reference pointer, e.g. "Recommendations 1.2.15 to 1.2.22"
XREF_ONLY_RE = re.compile(
    r"^\s*Recommendations?\s+[\d.]+(?:\s*(?:,|and|to|–|-)\s*[\d.]+)*\.?\s*$",
    re.IGNORECASE,
)

BOILERPLATE_SECTION_PATTERNS = (
    "contents",
    "table of contents",
    "index",
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
    "contributors",
    "your responsibility",
    "recommendations for research",
    "key recommendations for research",
    "other recommendations for research",
    "declarations of conflicts",
    "declarations of conflict",
    "conflict of interest",
    "conflicts of interest",
    "guideline development group members",
    "members of the guideline development group",
    "members of the who steering group",
    "members of the who secretariat",
    "membership of the programme development group",
    "membership of the guideline committee",
    "programme development group",
    "nice project team",
    "external contractors",
    "external experts and who staff involved in the preparation of this guideline",
    "external resource experts",
    "who secretariat",
    "evidence secretariat",
    "guideline working party",
    "stakeholder consultation",
    "committee details",
    "update information",
)

BOILERPLATE_SUBTREE_PATTERNS = (
    "contents",
    "table of contents",
    "index",
    "acknowledg",
    "glossary",
    "acronym",
    "abbreviat",
    "foreword",
    "preface",
    "disclaimer",
    "list participants",
    "contributors",
    "your responsibility",
    "recommendations for research",
    "key recommendations for research",
    "other recommendations for research",
    "guideline development group members",
    "members of the guideline development group",
    "members of the who steering group",
    "members of the who secretariat",
    "membership of the programme development group",
    "membership of the guideline committee",
    "programme development group",
    "nice project team",
    "external contractors",
    "external experts and who staff involved in the preparation of this guideline",
    "external resource experts",
    "who secretariat",
    "evidence secretariat",
    "guideline working party",
    "stakeholder consultation",
    "committee details",
    "update information",
)

TEMPLATE_SECTION_PATTERNS = (
    re.compile(r"\bforms?\b"),
    re.compile(r"\bchecklists?\b"),
    re.compile(r"\brecord forms?\b"),
    re.compile(r"\breport forms?\b"),
    re.compile(r"\bobservation charts?\b"),
    re.compile(r"\blogs?\b"),
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
    def prefixed_text(self) -> str:
        return f"[SOURCE:{self.source}|PAGE:{self.page_start}]\n{self.text}"


def strip_inline_markdown(text: str) -> str:
    """Best-effort normalization for filtering and sidecar metadata."""
    text = LINK_RE.sub(r"\1", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = EMPHASIS_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_text_for_rag(text: str) -> str:
    """Strip HTML artifacts and dead links that survive into chunk text."""
    text = SUP_RE.sub("", text)                  # <sup>3</sup> footnote refs
    text = BR_RE.sub(" ", text)                  # <br> → space
    text = HTML_TAG_RE.sub("", text)             # any remaining HTML tags
    text = INTERNAL_LINK_RE.sub(r"\1", text)     # [text](#anchor) → text
    text = strip_footer_artifacts(text)
    text = re.sub(r"[ \t]{2,}", " ", text)       # collapse runs of spaces
    return text


def has_blank_data_rows(body: str) -> bool:
    """Return True if body is a pure table where >50% of data rows are all-blank.

    This detects blank form templates (e.g. an empty 'Health Facility:' table)
    that have no retrieval value.  Clinical tables with occasional blank
    separator rows (common in large outcome tables) are NOT filtered because
    those blank rows are a small fraction of the total.
    """
    lines = [l.rstrip() for l in body.splitlines() if l.strip()]
    if not lines:
        return False
    # Must be entirely table lines — any paragraph text disqualifies
    if not all(l.startswith("|") and l.endswith("|") for l in lines):
        return False
    data_rows = 0
    blank_rows = 0
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Skip separator rows (|---|---|)
        if all(re.match(r"^[-: ]+$", c) for c in cells):
            continue
        data_rows += 1
        clean = [HTML_TAG_RE.sub("", c).strip() for c in cells]
        if all(not c for c in clean):
            blank_rows += 1
    if data_rows == 0:
        return True  # nothing but separators
    return blank_rows / data_rows > 0.5


def is_sparse_template_table(section: Section) -> bool:
    """Return True for table-dominant form/checklist templates with mostly blank cells."""
    heading_candidates = " ".join(section.heading_path) if section.heading_path else (section.heading_text or "")
    heading_norm = normalize_heading_text(heading_candidates)
    if not any(pattern.search(heading_norm) for pattern in TEMPLATE_SECTION_PATTERNS):
        return False

    lines = [line.rstrip() for line in section.body_text().splitlines() if line.strip()]
    if not lines:
        return False

    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) < 3:
        return False
    if len(table_lines) / len(lines) < 0.7:
        return False

    data_rows = 0
    max_cols = 0
    total_cells = 0
    nonempty_cells = 0

    for line in table_lines:
        cells = [HTML_TAG_RE.sub("", cell).strip() for cell in line.strip("|").split("|")]
        if all(re.match(r"^[-: ]+$", cell) for cell in cells):
            continue
        data_rows += 1
        max_cols = max(max_cols, len(cells))
        total_cells += len(cells)
        nonempty_cells += sum(bool(cell) for cell in cells)

    if data_rows == 0 or total_cells == 0:
        return True

    fill_ratio = nonempty_cells / total_cells
    return max_cols >= 5 and fill_ratio < 0.45


def is_footer_like_line(line: str) -> bool:
    normalized = strip_inline_markdown(line.replace("|", " ")).strip().lower()
    if not normalized:
        return False
    if re.fullmatch(r"_+", normalized):
        return True
    if normalized.startswith("revision no."):
        return True
    if re.fullmatch(r"page\s+[ivxlcdm\d]+\s+of\s+\d+", normalized):
        return True
    if re.fullmatch(r"revision\s+no\.\s*\d+\s+page\s+[ivxlcdm\d]+\s+of\s+\d+", normalized):
        return True
    return False


def is_empty_table_artifact_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.fullmatch(r"\|?[-:\s|]+\|?", stripped):
        return True
    if stripped.startswith("|") and stripped.endswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        return all(not cell for cell in cells)
    return False


def strip_footer_artifacts(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if is_footer_like_line(line):
            i += 1
            while i < len(lines) and is_empty_table_artifact_line(lines[i]):
                i += 1
            continue
        kept.append(line)
        i += 1

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def looks_like_manual_index(section: Section) -> bool:
    rendered = strip_inline_markdown(section.render())
    if len(MANUAL_INDEX_REF_RE.findall(rendered)) < 5:
        return False

    heading = strip_inline_markdown(section.heading_text or "")
    heading_is_indexish = bool(heading) and heading == heading.upper() and len(heading) <= 24
    return heading_is_indexish or "see also" in rendered.lower()


def normalize_heading_text(text: str) -> str:
    return strip_inline_markdown(text).strip(": ").lower()


def heading_matches(text: str | None, patterns: tuple[str, ...]) -> bool:
    if not text:
        return False
    normalized = normalize_heading_text(text)
    return any(pattern in normalized for pattern in patterns)


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
    if heading_matches(section.heading_text, BOILERPLATE_SECTION_PATTERNS):
        return True

    for heading in section.heading_path[:-1]:
        if heading_matches(heading, BOILERPLATE_SUBTREE_PATTERNS):
            return True

    # Heading-only sections have no body of their own — their heading is
    # captured as a breadcrumb in child sections, so emitting them as
    # standalone chunks adds noise with no retrieval value.
    if not section.body_text().strip():
        return True

    # Cross-reference-only body: "Recommendations 1.2.15 to 1.2.22" with no
    # actual content — just a pointer to the real recommendation text elsewhere.
    # body_text() is raw markdown so strip links before matching.
    if XREF_ONLY_RE.match(strip_inline_markdown(section.body_text())):
        return True

    # Pure tables with all-blank data rows are blank form templates — no value.
    if has_blank_data_rows(section.body_text()):
        return True
    if is_sparse_template_table(section):
        return True
    if looks_like_manual_index(section):
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
    index: int,
) -> Chunk | None:
    """Create a single Chunk from already-assembled text. Returns None if too short."""
    text = clean_text_for_rag(text.strip())
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
    )


def split_and_emit(
    section: Section,
    body: str,
    page_start: int,
    page_end: int,
    chunk_type: str,
    index_start: int,
    chunk_size: int,
    overlap: int,
) -> tuple[list[Chunk], int]:
    """Split body if needed, prepend breadcrumb+heading to every piece, emit chunks.

    By splitting the body *before* prepending context, every emitted chunk
    is self-contained — even pieces 2, 3, ... of an oversized section carry
    the breadcrumb and heading that identify their topic.
    """
    # Build the fixed context header that goes on every piece
    breadcrumb = build_breadcrumb(section)
    heading = section.heading_raw or ""
    header_parts = [p for p in [breadcrumb, heading] if p]
    header = "\n\n".join(header_parts)

    # Enforce a hard cap on the header so body always has room.
    # PDF misparsing sometimes produces multi-kilobyte "headings" (e.g. a table
    # flattened into a single heading line).  Reserve at least chunk_size chars
    # for the body so that every emitted chunk stays ≤ MAX_CHUNK_CHARS.
    _max_header = MAX_CHUNK_CHARS - chunk_size - 2  # -2 for the "\n\n" separator
    if len(header) > _max_header:
        header = header[:_max_header - 1] + "…"

    # How much of MAX_CHUNK_CHARS remains for the body?
    header_cost = len(header) + 2 if header else 0  # +2 for the separating "\n\n"
    body_budget = MAX_CHUNK_CHARS - header_cost  # always ≥ chunk_size

    body = body.strip()
    if len(body) <= body_budget:
        pieces = [body]
    else:
        # Split using body_budget so each piece fits when header is prepended
        pieces = [p for p in chunk_text(body, body_budget, overlap) if p.strip()]

    result: list[Chunk] = []
    idx = index_start
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        full_text = (header + "\n\n" + piece) if header else piece
        chunk = make_chunk(
            source=section.source,
            text=full_text,
            page_start=page_start,
            page_end=page_end,
            section=section,
            chunk_type=chunk_type,
            index=idx,
        )
        if chunk:
            result.append(chunk)
            idx += 1
    return result, idx


def chunk_section(
    section: Section,
    chunk_size: int,
    overlap: int,
    max_section_chars: int,
    chunk_index_start: int,
) -> tuple[list[Chunk], int]:
    rendered = section.render()
    if should_skip_section(section):
        return [], chunk_index_start

    if len(rendered) <= max_section_chars:
        return split_and_emit(
            section=section,
            body=section.body_text(),
            page_start=section.page_start,
            page_end=section.page_end,
            chunk_type="section",
            index_start=chunk_index_start,
            chunk_size=chunk_size,
            overlap=overlap,
        )

    blocks = split_section_into_blocks(section)
    if not blocks:
        return split_and_emit(
            section=section,
            body=section.body_text(),
            page_start=section.page_start,
            page_end=section.page_end,
            chunk_type="section",
            index_start=chunk_index_start,
            chunk_size=chunk_size,
            overlap=overlap,
        )

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
        chunk_type = current_types.pop() if len(current_types) == 1 else "mixed"
        new_chunks, next_index = split_and_emit(
            section=section,
            body=body,
            page_start=current_page_start,
            page_end=current_page_end,
            chunk_type=chunk_type,
            index_start=next_index,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        chunks.extend(new_chunks)
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
            chunk_index_start=next_index,
        )
        chunks.extend(section_chunks)

    return chunks, next_index


def collect_files(project_root: Path) -> tuple[list[Path], list[tuple[Path, str]]]:
    intl_dir = project_root / "processed" / "normalized" / "international"
    tanzania_dir = project_root / "processed" / "normalized" / "tanzania"

    intl_files = sorted(intl_dir.glob("*.md")) if intl_dir.exists() else []
    tanzania_files = sorted(tanzania_dir.glob("*.md")) if tanzania_dir.exists() else []

    to_process: list[Path] = []
    to_skip: list[tuple[Path, str]] = []

    for md_path in intl_files + tanzania_files:
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
        "--jsonl-sidecar",
        help="Optional JSONL sidecar path for richer chunk metadata",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / args.output
    sidecar_path = (project_root / args.jsonl_sidecar) if args.jsonl_sidecar else None

    to_process, to_skip = collect_files(project_root)
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

    # Deduplicate by chunk body text, keeping first occurrence per source file.
    # Repeated identical chunks arise from tables whose rows repeat verbatim
    # across sections (e.g. a rubric table appearing 31× in a curriculum doc).
    seen_texts: set[str] = set()
    deduped: list[Chunk] = []
    for chunk in all_chunks:
        if chunk.text not in seen_texts:
            seen_texts.add(chunk.text)
            deduped.append(chunk)
    n_dupes = len(all_chunks) - len(deduped)
    if n_dupes:
        print(f"Deduplication: removed {n_dupes} duplicate chunks ({len(deduped)} unique).")
    all_chunks = deduped

    write_output(all_chunks, output_path)
    if sidecar_path is not None:
        write_sidecar(all_chunks, sidecar_path)
        print(f"Metadata sidecar: {sidecar_path}")

    summarize_chunks(all_chunks, output_path)


if __name__ == "__main__":
    main()
