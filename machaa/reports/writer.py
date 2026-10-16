"""Write the research note the dashboard shows."""

from __future__ import annotations


def render_report(
    *,
    task_id: str,
    instruction: str,
    page_url: str,
    page_title: str,
    page_text: str,
    steps: list[str],
    saved_at: str,
    hits: list[dict] | None = None,
    source_note: str = "",
) -> str:
    """Return Markdown. The page text is quoted as text, not followed as instructions."""

    requested = " ".join(instruction.split())
    performed = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    body = page_text.strip() or "(The page had no visible text.)"
    note = f"{source_note.strip()}\n\n" if source_note.strip() else ""
    results = ""
    if hits is not None:
        results = "## Results\n\n" + _results_section(hits) + "\n\n"
    return (
        "# MACHAA research report\n\n"
        f"- **Task:** `{task_id}`\n"
        f"- **Requested:** {requested}\n"
        f"- **Page:** {page_url}\n"
        f"- **Page title:** {page_title or '(no title)'}\n"
        f"- **Saved:** {saved_at}\n\n"
        f"{results}"
        f"{note}"
        "## What Machaa did\n\n"
        f"{performed}\n\n"
        "## Page text\n\n"
        f"{body}\n"
    )


def _results_section(hits: list[dict]) -> str:
    lines: list[str] = []
    for hit in hits:
        title = " ".join(str(hit.get("title") or "").split())
        url = str(hit.get("url") or "").strip()
        snippet = " ".join(str(hit.get("snippet") or "").split())
        if not title or not url.startswith("http"):
            continue
        safe_title = title.replace("[", "(").replace("]", ")")
        line = f"{len(lines) + 1}. [{safe_title}]({url})"
        if snippet:
            line += f"\n   {snippet}"
        lines.append(line)
        if len(lines) >= 8:
            break
    if not lines:
        return "(No result links were found.)"
    return "\n".join(lines)
