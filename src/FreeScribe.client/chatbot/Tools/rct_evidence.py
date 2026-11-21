"""
Chatbot tools for evidence-based medical recommendations from the local
library of randomized controlled trial (RCT) study PDFs
(``chatbot/evidence/``, indexed by ``chatbot.rct_library``).

The tools form an agentic search toolkit: the LLM lists the available studies,
keyword-searches their content, then reads back the full passages or whole
sections of the studies it found, iterating until it can answer.
"""

import logging

from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.rct_library import DEFAULT_LIBRARY_DIR, get_rct_library


# How much of a hit's text is included with search results; the LLM reads the
# full chunk with read_rct_passages when it needs more context.
_SEARCH_SNIPPET_CHARS = 700

_EMPTY_LIBRARY_TEXT = (
    f"No study PDFs are indexed yet. Place the RCT / trial / guideline PDFs in "
    f"the '{DEFAULT_LIBRARY_DIR}' folder (next to the other chatbot data "
    f"folders) and ask again; they are indexed automatically."
)


def _parse_chunk_ids(raw) -> list[int]:
    """Accepts a list of ints, a list of numeric strings, or a comma/space
    separated string of chunk ids, and returns a list of ints."""
    if raw is None:
        return []
    if isinstance(raw, (int,)):
        return [raw]
    if isinstance(raw, str):
        parts = [p for p in raw.replace(",", " ").split() if p]
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = [raw]
    ids = []
    for part in parts:
        try:
            ids.append(int(str(part).strip()))
        except ValueError:
            continue
    return ids


@tool(
    category="evidence",
    description=(
        "Lists the randomized controlled trial (RCT) studies and clinical "
        "guidelines available in the local evidence library (PDFs previously "
        "placed in the evidence folder), with each study's title, year, "
        "design, sample size, and available sections. Use this FIRST when "
        "answering a medical evidence or recommendation question from the "
        "trial PDFs, to see what studies exist before searching them."
    ),
    context="Here are the studies available in the evidence library:",
    parameters={},
)
def list_rct_studies():
    """
    Lists the studies (PDFs) in the local evidence library.
    """
    try:
        library = get_rct_library()
        studies = library.list_studies()
        if not studies:
            return tr(label="Evidence library", send_to_ai=True,
                      query_results=_EMPTY_LIBRARY_TEXT, save_results="")

        lines = [f"{len(studies)} stud(ies) in the evidence library:"]
        for study in studies:
            bits = [f"'{study.display_name}' (file: {study.filename})"]
            if study.year:
                bits.append(str(study.year))
            if study.journal:
                bits.append(f"journal: {study.journal}")
            if study.study_design:
                bits.append(f"design: {study.study_design}")
            if study.sample_size:
                bits.append(f"n={study.sample_size}")
            if study.population_summary:
                bits.append(f"population: {study.population_summary}")
            sections = ", ".join(sorted(study.sections)) or "none"
            bits.append(f"sections: {sections}")
            if study.tags:
                bits.append(f"tags: {', '.join(study.tags)}")
            lines.append(" | ".join(bits))
        text = "\n".join(lines)
        return tr(label="Evidence library", send_to_ai=True,
                  query_results=text, save_results=text)
    except Exception as e:
        logging.getLogger(__name__).error("list_rct_studies failed: %s", e)
        return tr(label="Evidence library", send_to_ai=True,
                  query_results=f"Error listing the evidence library: {e}",
                  save_results="")


@tool(
    category="evidence",
    description=(
        "Keyword-searches the full text of the RCT study PDFs in the evidence "
        "library and returns the most relevant passages ranked by relevance. "
        "Each hit gives the study, section, page, a relevance score, a text "
        "snippet, and a chunk_id. Call with specific clinical terms (drug "
        "names, outcomes like 'hazard ratio', populations, endpoints). Use "
        "read_rct_passages with the returned chunk_ids to read a hit in full, "
        "and repeat the search with different terms if the first results are "
        "not on point. Set 'study' to restrict the search to one study."
    ),
    context="Here are the matching passages from the evidence library (use read_rct_passages with the chunk_ids for full text):",
    parameters={
        "query": "Clinical keywords to search the study texts for (e.g. 'icosapent ethyl hazard ratio')",
        "limit": "Maximum number of passages to return. Defaults to 6.",
        "study": "Optional study name (filename or title) to restrict the search to one study",
    },
)
def search_rct_studies(query: str, limit: int = 6, study: str = ""):
    """
    BM25 keyword search over the chunks of every indexed study PDF.
    """
    try:
        library = get_rct_library()
        if not library.list_studies():
            return tr(label="Evidence search", send_to_ai=True,
                      query_results=_EMPTY_LIBRARY_TEXT, save_results="")

        try:
            limit = max(1, min(int(limit), 12))
        except (TypeError, ValueError):
            limit = 6

        hits = library.search(query or "", limit=limit, study=study or "")
        if not hits:
            text = (f"No passages matched '{query}'"
                    + (f" in study '{study}'" if study else "")
                    + ". Try broader or alternate clinical terms.")
            return tr(label=f"Evidence search: {query}", send_to_ai=True,
                      query_results=text, save_results="")

        blocks = []
        sources = []
        for rank, (score, chunk) in enumerate(hits, 1):
            snippet = chunk.text[:_SEARCH_SNIPPET_CHARS]
            if len(chunk.text) > _SEARCH_SNIPPET_CHARS:
                snippet += " ..."
            blocks.append(
                f"[{rank}] study: {chunk.study} | section: {chunk.section} | "
                f"page: {chunk.page} | score: {score:.2f} | chunk_id: {chunk.chunk_id}\n{snippet}"
            )
            sources.append({
                "source_type": "study",
                "id": chunk.study,
                "data_type": chunk.section,
                "obs_date": None,
                "score": round(float(score), 3),
            })
        text = "\n\n".join(blocks)
        return tr(label=f"Evidence search: {query}", send_to_ai=True,
                  query_results=text, save_results=text, sources=sources)
    except ValueError as e:
        # Unknown study name: tell the LLM what is available so it can retry.
        return tr(label="Evidence search", send_to_ai=True,
                  query_results=f"Search failed: {e}", save_results="")
    except Exception as e:
        logging.getLogger(__name__).error("search_rct_studies failed: %s", e)
        return tr(label="Evidence search", send_to_ai=True,
                  query_results=f"Error searching the evidence library: {e}",
                  save_results="")


@tool(
    category="evidence",
    description=(
        "Reads back the FULL text of passages found by search_rct_studies, "
        "given their chunk_ids. Use after a search when the snippet was cut "
        "off or more context around a result is needed to answer."
    ),
    context="Here is the full text of the requested evidence passages:",
    parameters={
        "chunk_ids": "The chunk_id values returned by search_rct_studies, as a list or comma-separated string (e.g. [3, 7] or '3,7')",
    },
)
def read_rct_passages(chunk_ids):
    """
    Returns the full chunks for the given search-result chunk ids.
    """
    try:
        library = get_rct_library()
        ids = _parse_chunk_ids(chunk_ids)
        if not ids:
            return tr(label="Read evidence passages", send_to_ai=True,
                      query_results="No valid chunk_ids were provided. Pass the chunk_id values returned by search_rct_studies.",
                      save_results="")
        chunks = library.read_passages(ids)
        if not chunks:
            return tr(label="Read evidence passages", send_to_ai=True,
                      query_results=f"No passages found for chunk_ids {ids}. Re-run search_rct_studies to get valid ids.",
                      save_results="")
        found = {c.chunk_id for c in chunks}
        missing = [i for i in ids if i not in found]
        blocks = [
            f"chunk_id: {c.chunk_id} | study: {c.study} | section: {c.section} | page: {c.page}\n{c.text}"
            for c in chunks
        ]
        sources = [{
            "source_type": "study",
            "id": c.study,
            "data_type": c.section,
            "obs_date": None,
            "score": None,
        } for c in chunks]
        text = "\n\n".join(blocks)
        if missing:
            text += f"\n\n(No passage exists for chunk_ids {missing}; they may be from an outdated search.)"
        return tr(label="Read evidence passages", send_to_ai=True,
                  query_results=text, save_results=text, sources=sources)
    except Exception as e:
        logging.getLogger(__name__).error("read_rct_passages failed: %s", e)
        return tr(label="Read evidence passages", send_to_ai=True,
                  query_results=f"Error reading evidence passages: {e}",
                  save_results="")


@tool(
    category="evidence",
    description=(
        "Returns the full text of one section (abstract, introduction, "
        "methods, results, discussion, conclusions, references) of one study "
        "in the evidence library. Use when the whole section is needed, e.g. "
        "to review a trial's methods or full conclusions."
    ),
    context="Here is the requested section of the study:",
    parameters={
        "study": "Study name (filename or title), as shown by list_rct_studies or search results",
        "section": "Section to read: abstract, introduction, methods, results, discussion, conclusions, or references",
    },
)
def get_rct_study_section(study: str, section: str):
    """
    Returns one canonical section's text for a study.
    """
    try:
        library = get_rct_library()
        text = library.get_section(study or "", section or "")
        text = f"Study: {study} | Section: {section}\n\n{text}"
        matched = library.match_study(study or "")
        sources = [{
            "source_type": "study",
            "id": matched.filename if matched else study,
            "data_type": section,
            "obs_date": None,
            "score": None,
        }]
        return tr(label=f"Evidence section: {study} / {section}", send_to_ai=True,
                  query_results=text, save_results=text, sources=sources)
    except ValueError as e:
        return tr(label=f"Evidence section: {study} / {section}", send_to_ai=True,
                  query_results=f"Could not read section: {e}", save_results="")
    except Exception as e:
        logging.getLogger(__name__).error("get_rct_study_section failed: %s", e)
        return tr(label=f"Evidence section: {study} / {section}", send_to_ai=True,
                  query_results=f"Error reading study section: {e}", save_results="")
