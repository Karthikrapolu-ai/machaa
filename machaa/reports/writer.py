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
) -> str:
    """Return Markdown. The page text is quoted as text, not followed as instructions."""

    requested = " ".join(instruction.split())
    performed = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    body = page_text.strip() or "(The page had no visible text.)"
    return (
        "# MACHAA research report\n\n"
        f"- **Task:** `{task_id}`\n"
        f"- **Requested:** {requested}\n"
        f"- **Page:** {page_url}\n"
        f"- **Page title:** {page_title or '(no title)'}\n"
        f"- **Saved:** {saved_at}\n\n"
        "## What Machaa did\n\n"
        f"{performed}\n\n"
        "## Page text\n\n"
        f"{body}\n"
    )
