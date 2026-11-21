"""
Local library of randomized controlled trial (RCT) studies for the chatbot.

Ingests the PDFs in a directory (default ``chatbot/evidence/``), extracts their
text (fast pypdf text-layer path with an OCR fallback for scanned PDFs), splits
them into standard paper sections, chunks the text, and keyword-searches the
chunks with Okapi BM25. Extracted pages are cached to disk keyed by the file's
content hash, so a PDF is only ever parsed once; restarts and unchanged files
reload from the cache in milliseconds.

Sidecar ``<pdf name>.json`` files (as produced alongside the PDFs in the
evidence folder) supply richer metadata (title, journal, sample size, tags)
when present; everything is best-effort extracted from the paper text
otherwise.
"""

import hashlib
import json
import logging
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


# Where the study PDFs live by default (relative to the client root / cwd).
DEFAULT_LIBRARY_DIR = os.path.join("chatbot", "evidence")

# Disk cache of extracted pages, stored inside the library directory.
CACHE_FILENAME = ".rct_index_cache.json"
CACHE_VERSION = 1

# Chunking targets (characters). Chunks stay within one (study, section, page).
CHUNK_CHAR_TARGET = 1200
CHUNK_CHAR_OVERLAP = 150

# Cap on the text returned for a single section read, to protect LLM context.
SECTION_CHAR_LIMIT = 8000

# Minimum characters of text before a pypdf extraction is considered usable
# and the (slow) OCR fallback is skipped.
MIN_EXTRACTED_CHARS = 500

# Canonical sections and the heading lines that introduce them. A line must
# consist ONLY of the heading (after optional numbering and a trailing colon)
# to count — inline structured-abstract labels like "Background: Patients
# with..." must NOT split sections.
_SECTION_PATTERNS = [
    ("abstract", r"(abstract|summary|background and objectives?|objectives?)"),
    ("introduction", r"(introduction|background|foreword)"),
    ("methods", r"(methods?|methodology|materials and methods|patients and methods|"
                r"study design|study population|participants|statistical analysis|"
                r"outcome measures?|interventions?|measurements|procedures|analyses|"
                r"trial design|study oversight)"),
    ("results", r"(results?|findings|outcomes?)"),
    ("discussion", r"(discussion|comment|limitations)"),
    ("conclusions", r"(conclusions?|summary and conclusions?|interpretation)"),
    ("references", r"(references?|bibliography|acknowledg(e)?ments?|appendix|"
                    r"supplementary material)"),
]
_DEFAULT_SECTION = "other"

# Small stopword list (kept tiny so clinical terms like "no" vs "not" survive;
# these are the classic BM25 stopwords that carry no retrieval signal).
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "had", "has", "have", "he", "her", "his", "if", "in", "into", "is",
    "it", "its", "of", "on", "or", "our", "she", "that", "the", "their", "them",
    "there", "these", "they", "this", "to", "was", "we", "were", "what", "which",
    "who", "will", "with", "would",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
_SAMPLE_SIZE_RE = re.compile(
    r"(\d[\d,]{2,8})\s*(patients|participants|subjects|adults|persons|women|men)\b",
    re.IGNORECASE,
)
_RCT_RE = re.compile(
    r"randomi[sz]ed\s+(controlled\s+)?trial|randomly\s+assign", re.IGNORECASE)
# A heading line: short and (optionally) numbered like "2. Methods".
_HEADING_LINE_MAX = 90

# BM25 parameters (classic Okapi defaults).
BM25_K1 = 1.5
BM25_B = 0.75

# Per-section score multipliers: reference lists match keyword queries easily
# but are rarely the evidence the user wants, so they rank below body text.
_SECTION_WEIGHTS = {
    "references": 0.35,
    "other": 0.85,
}


@dataclass
class RCTChunk:
    """A searchable text chunk from one study.

    Attributes:
        chunk_id: Unique id across the whole library (used by the read tool).
        study: Filename of the source PDF.
        section: Canonical section name (abstract/methods/results/...).
        page: 1-based page number the chunk came from (0 when unknown).
        text: The chunk text.
    """
    chunk_id: int
    study: str
    section: str
    page: int
    text: str


@dataclass
class RCTStudy:
    """Metadata and content for one ingested study PDF."""
    filename: str
    path: str
    file_hash: str
    title: str = ""
    journal: str | None = None
    authors: str | None = None
    year: int | None = None
    study_design: str | None = None
    population_summary: str | None = None
    sample_size: int | None = None
    tags: list[str] = field(default_factory=list)
    n_pages: int = 0
    sections: dict[str, str] = field(default_factory=dict)
    chunks: list[RCTChunk] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.title or os.path.splitext(self.filename)[0]


class RCTLibrary:
    """A searchable library of RCT study PDFs from one directory.

    Args:
        library_dir: Directory containing the study PDFs (and optional
            ``<name>.json`` sidecar metadata files).
        ocr_fallback: If True, PDFs without a usable text layer are OCR'd
            (slow, but cached afterwards). If False they are skipped.
    """

    def __init__(self, library_dir: str | None = None, ocr_fallback: bool = True):
        self.library_dir = library_dir or DEFAULT_LIBRARY_DIR
        self.ocr_fallback = ocr_fallback
        self.studies: list[RCTStudy] = []
        self._chunks: list[RCTChunk] = []
        # BM25 postings: term -> list of (chunk index, term frequency).
        self._postings: dict[str, list[tuple[int, int]]] = {}
        self._chunk_lengths: list[int] = []
        self._loaded = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Loading / ingestion
    # ------------------------------------------------------------------ #

    def ensure_loaded(self, force: bool = False) -> None:
        """Scans the library directory and builds the search index (once).

        Results are cached to disk keyed by each PDF's content hash; only new
        or changed files are re-extracted. Safe to call from any thread.
        """
        if self._loaded and not force:
            return
        with self._lock:
            if self._loaded and not force:
                return
            cache = self._load_cache()
            files = self._scan_pdfs()
            studies: list[RCTStudy] = []
            changed = False

            for filename, path, file_hash in files:
                entry = cache.get(file_hash)
                if entry is None:
                    pages = self._extract_pdf(path)
                    if not pages:
                        continue
                    entry = {"filename": filename, "pages": pages}
                    cache[file_hash] = entry
                    changed = True
                sidecar = self._load_sidecar(path)
                studies.append(self._study_from_pages(filename, path, file_hash, entry["pages"], sidecar))

            # Drop cache entries for PDFs that no longer exist.
            live_hashes = {f[2] for f in files}
            if set(cache) - live_hashes:
                cache = {h: e for h, e in cache.items() if h in live_hashes}
                changed = True

            if changed:
                self._save_cache(cache)

            # Deterministic order (sorted filenames) keeps chunk ids stable.
            studies.sort(key=lambda s: s.filename.lower())
            self.studies = studies
            self._rebuild_index()
            self._loaded = True
            logging.getLogger(__name__).info(
                "RCT library loaded: %d stud(ies), %d chunks from %s",
                len(self.studies), len(self._chunks), self.library_dir,
            )

    def _scan_pdfs(self) -> list[tuple[str, str, str]]:
        """Returns (filename, path, sha256) for every PDF in the library dir."""
        found: list[tuple[str, str, str]] = []
        if not os.path.isdir(self.library_dir):
            return found
        for filename in os.listdir(self.library_dir):
            path = os.path.join(self.library_dir, filename)
            if not filename.lower().endswith(".pdf") or not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                found.append((filename, path, file_hash))
            except Exception as e:
                logging.getLogger(__name__).warning("Could not hash %s: %s", filename, e)
        return found

    def _extract_pdf(self, path: str) -> list[str]:
        """Extracts per-page text from a PDF.

        Fast path uses the pypdf text layer. Falls back to OCR (whole file,
        cached by the caller) when the PDF has no usable text layer.

        Returns:
            List of page texts; empty list when nothing could be extracted.
        """
        pages: list[str] = []
        if PYPDF_AVAILABLE:
            try:
                reader = PdfReader(path)
                for page in reader.pages:
                    try:
                        pages.append(page.extract_text() or "")
                    except Exception:
                        pages.append("")
            except Exception as e:
                logging.getLogger(__name__).warning("pypdf failed on %s: %s", path, e)

        total_chars = sum(len(p.strip()) for p in pages)
        if total_chars >= MIN_EXTRACTED_CHARS:
            return [self._normalize_page(p) for p in pages]

        if not self.ocr_fallback:
            logging.getLogger(__name__).warning(
                "No text layer in %s and OCR fallback disabled; skipping.", path)
            return []

        # OCR fallback for scanned PDFs (slow, one-time thanks to the cache).
        try:
            from utils.read_files import pdf_image_to_text
            text = pdf_image_to_text(pdf_path=path)
            text = self._normalize_page(text or "")
            return [text] if len(text.strip()) >= MIN_EXTRACTED_CHARS else []
        except Exception as e:
            logging.getLogger(__name__).error("OCR fallback failed for %s: %s", path, e)
            return []

    @staticmethod
    def _normalize_page(text: str) -> str:
        """Cleans extracted text: de-hyphenates line breaks, trims junk lines."""
        lines = []
        for line in (text or "").replace("\r", "").split("\n"):
            # Join words hyphenated across a line break.
            if lines and lines[-1].endswith("-"):
                lines[-1] = lines[-1][:-1] + line.strip()
            else:
                lines.append(line.rstrip())
        cleaned = "\n".join(lines)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _load_sidecar(self, pdf_path: str) -> dict | None:
        """Loads ``<pdf>.json`` sidecar metadata next to the PDF, if present."""
        sidecar_path = os.path.splitext(pdf_path)[0] + ".json"
        try:
            if os.path.isfile(sidecar_path):
                with open(sidecar_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else None
        except Exception as e:
            logging.getLogger(__name__).warning("Bad sidecar %s: %s", sidecar_path, e)
        return None

    def _study_from_pages(
        self,
        filename: str,
        path: str,
        file_hash: str,
        pages: list[str],
        sidecar: dict | None,
    ) -> RCTStudy:
        """Builds an RCTStudy from extracted pages plus optional sidecar data."""
        study = RCTStudy(filename=filename, path=path, file_hash=file_hash, n_pages=len(pages))
        full_text = "\n\n".join(pages)
        self._fill_metadata(study, full_text, sidecar)
        paragraphs = self._section_paragraphs(pages)
        self._fill_sections(study, paragraphs)
        self._fill_chunks(study, paragraphs)
        return study

    def _fill_metadata(self, study: RCTStudy, full_text: str, sidecar: dict | None) -> None:
        """Merges sidecar metadata with best-effort extraction from the text."""
        meta = sidecar or {}
        head = full_text[:6000]

        study.title = str(meta.get("title") or "").strip()
        study.journal = meta.get("journal") or None
        study.authors = meta.get("authors") or None
        study.population_summary = meta.get("population_summary") or None
        study.tags = [str(t) for t in (meta.get("tags") or []) if str(t).strip()]
        study.sample_size = meta.get("sample_size") or None
        study.year = meta.get("publication_year") or None
        study.study_design = meta.get("study_design") or (
            "rct" if _RCT_RE.search(head) else None)

        if not study.title:
            study.title = os.path.splitext(study.filename)[0]
        if study.year is None:
            years = _YEAR_RE.findall(head) or _YEAR_RE.findall(full_text[:20000])
            study.year = int(Counter(years).most_common(1)[0][0]) if years else None
        if study.sample_size is None:
            best = 0
            for match in _SAMPLE_SIZE_RE.finditer(full_text[:30000]):
                n = int(match.group(1).replace(",", ""))
                if 10 <= n <= 200000 and n > best:
                    best = n
            study.sample_size = best or None
        if not study.tags:
            study.tags = [study.study_design] if study.study_design else []

    @staticmethod
    def _section_paragraphs(pages: list[str]) -> list[tuple[str, int, str]]:
        """Splits pages into paragraphs tagged with (section, page number)."""
        paragraphs: list[tuple[str, int, str]] = []
        current = _DEFAULT_SECTION
        for page_no, page in enumerate(pages, 1):
            for line in page.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                matched = RCTLibrary._match_heading(stripped)
                if matched:
                    current = matched
                    continue
                paragraphs.append((current, page_no, stripped))
        return paragraphs

    @staticmethod
    def _match_heading(line: str) -> str | None:
        """Returns the canonical section name when a line is a section heading.

        A heading line must be short, consist only of the heading text
        (optionally numbered, optionally colon-terminated) — inline labels
        like "Methods: We randomly assigned..." are not headings.
        """
        if len(line) > _HEADING_LINE_MAX:
            return None
        cleaned = re.sub(r"^\d+(\.\d+)*\.?\s*", "", line).strip()
        cleaned = cleaned.rstrip(":").strip()
        if not cleaned or len(cleaned) > _HEADING_LINE_MAX:
            return None
        for name, pattern in _SECTION_PATTERNS:
            if re.fullmatch(pattern, cleaned, re.IGNORECASE):
                return name
        return None

    def _fill_sections(self, study: RCTStudy, paragraphs: list[tuple[str, int, str]]) -> None:
        """Joins the paragraphs of each section into one text per section."""
        sections: dict[str, list[str]] = {}
        for section, _page, paragraph in paragraphs:
            sections.setdefault(section, []).append(paragraph)
        study.sections = {name: "\n".join(paras) for name, paras in sections.items()}

    def _fill_chunks(self, study: RCTStudy, paragraphs: list[tuple[str, int, str]]) -> None:
        """Chunks each section's text into ~CHUNK_CHAR_TARGET pieces.

        Chunk ids are assigned relative to the study here; the global ids the
        tools use are (re)assigned in _rebuild_index.
        """
        by_section: dict[str, list[tuple[int, str]]] = {}
        for section, page_no, paragraph in paragraphs:
            by_section.setdefault(section, []).append((page_no, paragraph))

        order = [s for s in ("abstract", "introduction", "methods", "results",
                             "discussion", "conclusions", "other", "references")
                 if s in by_section]
        order += [s for s in by_section if s not in order]

        chunks: list[RCTChunk] = []
        for section in order:
            paras = by_section[section]
            pieces = self._chunk_text("\n".join(p for _page, p in paras))
            if not pieces:
                continue
            # Map each piece to the page it starts on: walk the paragraph
            # boundaries (cumulative chars) as the pieces are consumed.
            boundaries: list[tuple[int, int]] = []
            running = 0
            for page, para in paras:
                running += len(para) + 1
                boundaries.append((running, page))
            page_no = paras[0][0]
            pages: list[int] = []
            consumed = 0
            for piece in pieces:
                while boundaries and consumed >= boundaries[0][0]:
                    _boundary, page_no = boundaries.pop(0)
                pages.append(page_no)
                consumed += len(piece)
            for piece, page in zip(pieces, pages):
                chunks.append(RCTChunk(
                    chunk_id=len(chunks), study=study.filename,
                    section=section, page=page, text=piece))
        study.chunks = chunks

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        """Splits text into overlapping chunks near CHUNK_CHAR_TARGET chars."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > CHUNK_CHAR_TARGET:
                # Very long "sentence" (e.g. a table): hard-split it.
                if current:
                    chunks.append(current.strip())
                    current = ""
                for i in range(0, len(sentence), CHUNK_CHAR_TARGET):
                    chunks.append(sentence[i:i + CHUNK_CHAR_TARGET].strip())
                continue
            if len(current) + len(sentence) + 1 > CHUNK_CHAR_TARGET and current:
                chunks.append(current.strip())
                # Keep a small overlap for continuity across the boundary.
                current = current[-CHUNK_CHAR_OVERLAP:] + " " + sentence
            else:
                current = (current + " " + sentence).strip()
        if current.strip():
            chunks.append(current.strip())
        return [c for c in chunks if len(c) > 40]

    # ------------------------------------------------------------------ #
    # Cache persistence
    # ------------------------------------------------------------------ #

    def _cache_path(self) -> str:
        return os.path.join(self.library_dir, CACHE_FILENAME)

    def _load_cache(self) -> dict:
        try:
            path = self._cache_path()
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("version") == CACHE_VERSION:
                    return data.get("files", {})
        except Exception as e:
            logging.getLogger(__name__).warning("RCT cache unreadable: %s", e)
        return {}

    def _save_cache(self, cache: dict) -> None:
        try:
            os.makedirs(self.library_dir, exist_ok=True)
            tmp = self._cache_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "files": cache}, f)
            os.replace(tmp, self._cache_path())
        except Exception as e:
            logging.getLogger(__name__).warning("Could not save RCT cache: %s", e)

    # ------------------------------------------------------------------ #
    # BM25 index
    # ------------------------------------------------------------------ #

    def _rebuild_index(self) -> None:
        """Builds BM25 postings over all chunks; assigns global chunk ids."""
        self._chunks = []
        for study in self.studies:
            for chunk in study.chunks:
                chunk.chunk_id = len(self._chunks)
                self._chunks.append(chunk)

        self._postings = {}
        self._chunk_lengths = []
        for idx, chunk in enumerate(self._chunks):
            tokens = self._tokenize(chunk.text)
            self._chunk_lengths.append(len(tokens))
            for term, freq in Counter(tokens).items():
                self._postings.setdefault(term, []).append((idx, freq))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]

    def _bm25_scores(self, query_tokens: list[str]) -> dict[int, float]:
        """Scores every chunk containing at least one query term (Okapi BM25)."""
        n_chunks = len(self._chunks)
        if not n_chunks:
            return {}
        avgdl = sum(self._chunk_lengths) / n_chunks or 1.0
        scores: dict[int, float] = {}
        for term in set(query_tokens):
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = math.log(1 + (n_chunks - len(postings) + 0.5) / (len(postings) + 0.5))
            for idx, freq in postings:
                dl = self._chunk_lengths[idx] or 1
                denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl)
                scores[idx] = scores.get(idx, 0.0) + idf * freq * (BM25_K1 + 1) / denom
        for idx, score in scores.items():
            scores[idx] = score * _SECTION_WEIGHTS.get(
                self._chunks[idx].section, 1.0)
        return scores

    # ------------------------------------------------------------------ #
    # Public search / read API
    # ------------------------------------------------------------------ #

    @property
    def chunks(self) -> list[RCTChunk]:
        self.ensure_loaded()
        return self._chunks

    def list_studies(self) -> list[RCTStudy]:
        self.ensure_loaded()
        return list(self.studies)

    def match_study(self, name: str) -> RCTStudy | None:
        """Finds a study by (partial) filename, title, tag, journal, or the
        paper's title lines (the head of its "other" section).

        Args:
            name: Full or partial study name, as returned by search results.

        Returns:
            The matched study, or None when nothing matches.
        """
        self.ensure_loaded()
        if not name:
            return None
        wanted = name.strip().lower()
        exact = os.path.basename(wanted)
        norm = re.sub(r"[^a-z0-9]+", "", wanted)
        for study in self.studies:
            candidates = [study.filename.lower(), study.title.lower(),
                          (study.journal or "").lower()]
            candidates += [t.lower() for t in study.tags]
            candidates.append(study.sections.get("other", "")[:150].lower())
            if exact in candidates:
                return study
        for study in self.studies:
            candidates = [study.filename.lower(), study.title.lower(),
                          (study.journal or "").lower()]
            candidates += [t.lower() for t in study.tags]
            candidates.append(study.sections.get("other", "")[:150].lower())
            if any(wanted in c or norm in re.sub(r"[^a-z0-9]+", "", c)
                   for c in candidates if c):
                return study
        return None

    def search(self, query: str, limit: int = 6, study: str = "") -> list[tuple[float, RCTChunk]]:
        """BM25 keyword search across all study chunks.

        Args:
            query: Free-text keyword query.
            limit: Maximum number of hits to return.
            study: Optional study name to restrict the search to.

        Returns:
            List of (score, chunk) sorted by descending relevance.
        """
        self.ensure_loaded()
        if not self._chunks or not query.strip():
            return []

        restrict: set[str] | None = None
        if study:
            matched = self.match_study(study)
            if matched is None:
                raise ValueError(f"No study matching '{study}'")
            restrict = {matched.filename}

        tokens = self._tokenize(query)
        # Also boost study tags that match the query terms.
        scores = self._bm25_scores(tokens)
        if restrict is not None:
            scores = {i: s for i, s in scores.items() if self._chunks[i].study in restrict}

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        return [(score, self._chunks[idx]) for idx, score in ranked]

    def read_passages(self, chunk_ids: list[int]) -> list[RCTChunk]:
        """Returns the full chunks for the given ids (as produced by search)."""
        self.ensure_loaded()
        by_id = {c.chunk_id: c for c in self._chunks}
        found = []
        for cid in chunk_ids:
            chunk = by_id.get(int(cid))
            if chunk is not None:
                found.append(chunk)
        return found

    def get_section(self, study_name: str, section: str) -> str:
        """Returns one canonical section's text for a study (capped).

        Raises:
            ValueError: When the study or section is not found.
        """
        study = self.match_study(study_name)
        if study is None:
            raise ValueError(f"No study matching '{study_name}'")

        wanted = section.strip().lower()
        # Fuzzy section match: exact, then prefix, then substring.
        keys = list(study.sections)
        match = None
        for key in keys:
            if key == wanted:
                match = key
                break
        if match is None:
            for key in keys:
                if key.startswith(wanted) or wanted.startswith(key):
                    match = key
                    break
        if match is None:
            for key in keys:
                if wanted in key:
                    match = key
                    break
        if match is None:
            available = ", ".join(sorted(study.sections)) or "none"
            raise ValueError(
                f"Section '{section}' not found in '{study.display_name}'. "
                f"Available sections: {available}")

        text = study.sections[match].strip()
        if not text:
            return "(section is empty)"
        if len(text) > SECTION_CHAR_LIMIT:
            text = text[:SECTION_CHAR_LIMIT] + "\n... [truncated]"
        return text


# Module-level singleton so the PDF library is parsed and indexed once per
# process no matter how many tools or workflows touch it.
_LIBRARY_LOCK = threading.Lock()
_LIBRARY_INSTANCE: RCTLibrary | None = None


def get_rct_library(library_dir: str | None = None) -> RCTLibrary:
    """Returns the shared RCTLibrary instance, creating it on first use."""
    global _LIBRARY_INSTANCE
    if _LIBRARY_INSTANCE is None:
        with _LIBRARY_LOCK:
            if _LIBRARY_INSTANCE is None:
                _LIBRARY_INSTANCE = RCTLibrary(library_dir)
    return _LIBRARY_INSTANCE
