"""Save a Word document from a draft. The file path is chosen by Machaa."""

from __future__ import annotations

import json
from pathlib import Path

from machaa.core.errors import MachaaError
from machaa.reports.creative import enrich_concepts


class DocumentError(MachaaError):
    """The draft could not be saved as a Word document."""


def write_brief(path: Path, title: str, body: str) -> None:
    """Write title, sections, and the source links Machaa already collected."""

    from docx import Document

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DocumentError("Machaa could not save the Word document.") from exc
    if not isinstance(payload, dict):
        raise DocumentError("Machaa could not save the Word document.")
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise DocumentError("Machaa could not save the Word document.")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(title.strip() or "Machaa brief", level=0)
    document.add_paragraph(
        "Machaa wrote this from public search results on this computer. "
        "The wording came from Gemini. The links below are the pages Machaa opened."
    )
    for section in sections[:8]:
        if not isinstance(section, dict):
            continue
        heading = " ".join(str(section.get("heading") or "").split())
        paragraphs = section.get("paragraphs")
        if not heading or not isinstance(paragraphs, list):
            continue
        document.add_heading(heading[:160], level=1)
        for paragraph in paragraphs[:6]:
            text = " ".join(str(paragraph).split())
            if text:
                document.add_paragraph(text[:1200])
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    kept = []
    for source in sources[:8]:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        label = " ".join(str(source.get("title") or "").split()) or url
        if url.startswith("http://") or url.startswith("https://"):
            kept.append((label[:200], url[:500]))
    if kept:
        document.add_heading("Sources", level=1)
        for label, url in kept:
            document.add_paragraph(f"{label} — {url}")
    document.save(str(path))


def write_social_document(path: Path, payload: dict, image_path: Path | None) -> None:
    """Write three editable post concepts and the image credit, or a placeholder label."""

    from docx import Document
    from docx.shared import Inches

    raw_concepts = payload.get("concepts") if isinstance(payload, dict) else None
    if not isinstance(raw_concepts, list) or len(raw_concepts) < 3:
        raise DocumentError("Machaa could not save the social post document.")
    concepts = enrich_concepts(raw_concepts, str(payload.get("tone") or ""))
    if len(concepts) < 3:
        raise DocumentError("Machaa could not save the social post document.")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    title = " ".join(str(payload.get("title") or "").split()) or "Social posts"
    document.add_heading(title[:200], level=0)
    document.add_paragraph(
        f"Brand: {_line(payload.get('brand'))}\n"
        f"Platform: {_line(payload.get('platform'))}\n"
        f"Audience: {_line(payload.get('audience'))}\n"
        f"Topic: {_line(payload.get('topic'))}\n"
        f"Tone: {_line(concepts[0].get('tone') if concepts else '')}"
    )
    image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    document.add_heading("Reference image", level=1)
    if image.get("placeholder"):
        document.add_paragraph(
            "This picture is a placeholder drawn by Machaa. "
            "It is not a photograph, and it is not a picture of the room."
        )
    else:
        document.add_paragraph(
            f"Title: {_line(image.get('title'))}. "
            f"Artist: {_line(image.get('artist'))}. "
            f"Licence: {_line(image.get('license_name'))}. "
            f"Licence page: {_line(image.get('license_url'))}. "
            f"Source: {_line(image.get('source_page'))}."
        )
    if image_path is not None and image_path.is_file():
        try:
            document.add_picture(str(image_path), width=Inches(5.5))
        except Exception:
            document.add_paragraph(
                "Machaa could not place that picture in the file. "
                "The picture above was not invented."
            )
    for index, concept in enumerate(concepts[:3], start=1):
        if not isinstance(concept, dict):
            raise DocumentError("Machaa could not save the social post document.")
        name = _line(concept.get("name")) or f"Post {index}"
        document.add_heading(f"Post {index}: {name}"[:160], level=1)
        caption = _line(concept.get("caption") or concept.get("short_caption"))
        if not caption:
            raise DocumentError("Machaa could not save the social post document.")
        document.add_paragraph("Hook: " + _line(concept.get("hook"))[:300])
        document.add_paragraph("Format: " + _line(concept.get("format")))
        document.add_paragraph("Short caption: " + caption[:800])
        document.add_paragraph(caption[:800])
        document.add_paragraph("Long caption: " + _line(concept.get("long_caption"))[:1200])
        document.add_paragraph("Call to action: " + _line(concept.get("cta"))[:300])
        tags = concept.get("hashtags") if isinstance(concept.get("hashtags"), list) else []
        document.add_paragraph("Hashtags: " + " ".join(str(tag) for tag in tags[:8]))
        document.add_paragraph("Visual direction: " + _line(concept.get("visual_direction"))[:400])
        document.add_paragraph("Image suggestion: " + _line(concept.get("image_suggestion"))[:400])
        urls = concept.get("source_urls") if isinstance(concept.get("source_urls"), list) else []
        kept = [
            str(url).strip()
            for url in urls
            if str(url).startswith("http://") or str(url).startswith("https://")
        ]
        if kept:
            document.add_paragraph("Sources: " + " ".join(kept[:4]))
    document.save(str(path))


def _line(value: object) -> str:
    return " ".join(str(value or "").split())
