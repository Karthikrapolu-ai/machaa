"""A labelled stand-in for Gemini, used only when no key is configured.

The dashboard summary says the writing was a stand-in. It is not described
as a live Gemini reply.
"""

from __future__ import annotations

import re

from machaa.agents.planning import parse_research_request
from machaa.agents.planner import default_social_actions

_URL = re.compile(r"https?://[^\s<>\"']+")


class FixtureGemini:
    """Return a fixed, valid plan and three captions. No network call."""

    model = "stand-in"

    def __init__(self) -> None:
        self.calls = 0
        self.tokens_used = 0

    @property
    def configured(self) -> bool:
        return True

    def reset_budget(self) -> None:
        self.tokens_used = 0

    def draft(self, instruction: str, sources: str) -> dict:
        self.calls += 1
        return {
            "title": "Machaa brief",
            "sections": [
                {
                    "heading": "Notes",
                    "paragraphs": [
                        "This paragraph was written by the Machaa stand-in, not by Gemini."
                    ],
                }
            ],
            "model": self.model,
        }

    def plan_actions(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list[dict]:
        self.calls += 1
        plan = parse_research_request(instruction)
        brand = plan.brand if plan and plan.brand else "the brand"
        topic = plan.query if plan and plan.query else "the topic"
        platform = plan.platform if plan and plan.platform else "Instagram"
        audience = plan.audience if plan and plan.audience else "people who might hire this brand"
        actions = default_social_actions(brand, topic, platform, audience)[:max_steps]
        return [
            {"tool": action.tool, "arguments": action.arguments, "label": action.label}
            for action in actions
        ]

    def plan_workflow(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list[dict]:
        self.calls += 1
        from machaa.agents.planning import parse_research_request
        from machaa.agents.workflow import skeleton_actions

        plan = parse_research_request(instruction)
        if plan is None or plan.kind != "workflow":
            plan = parse_research_request(
                "research interiors, prepare Instagram captions, create a DOCX, "
                "save it in Documents/Machaa, and open it."
            )
        actions = skeleton_actions(plan)[:max_steps]
        return [
            {
                "tool": action.tool,
                "arguments": action.arguments,
                "label": action.label,
                "group": action.group,
            }
            for action in actions
        ]

    def plan_desktop(self, instruction: str, feedback: str = "", max_steps: int = 8) -> list[dict]:
        self.calls += 1
        from machaa.agents.desktop import NotepadMemory, local_desktop_actions

        actions = local_desktop_actions(instruction, NotepadMemory())[:max_steps]
        return [
            {"tool": action.tool, "arguments": action.arguments, "label": action.label}
            for action in actions
        ]

    def write_social(
        self,
        brand: str,
        topic: str,
        platform: str,
        audience: str,
        sources: str,
        image_note: str,
    ) -> dict:
        self.calls += 1
        urls = [match.rstrip(".,);") for match in _URL.findall(sources + "\n" + image_note)]
        urls = [url for url in urls if url.startswith("http")][:4] or [
            "https://commons.wikimedia.org/"
        ]
        angles = [
            (
                "Light and layout",
                "reel",
                f"One light, one path through the room.",
                f"{brand}: {topic}, with a finished look and room left to walk.",
                f"Keep {topic} to a single warm light and a clear walkway. {brand} shows the room as it is, for {audience}.",
                "Save this layout before you move a sofa.",
            ),
            (
                "One strong wall",
                "carousel",
                f"One wall does the work.",
                f"For {audience}, this {platform} idea keeps {topic} to one material and one colour.",
                f"Slide through the wall, the floor, and the window. {brand} stays with {topic} and does not add a second pattern.",
                "Send this to the person choosing the paint.",
            ),
            (
                "Evening light",
                "static",
                "Warm lamps, clear surfaces.",
                f"{brand} on {platform}: {topic} after dark, with warm lamps and clear surfaces.",
                f"After dark, {topic} is the lamps and the empty floor. {brand} leaves the rest quiet.",
                "Keep this for the evening photos.",
            ),
        ]
        tags = ["#InteriorDesign", "#2BHK", "#HomeInspo", "#AffordableLuxury", "#VistaaraInteriors"]
        concepts = []
        for index, (name, post_format, hook, caption, long_caption, cta) in enumerate(angles):
            concepts.append(
                {
                    "name": name,
                    "hook": hook,
                    "caption": caption,
                    "short_caption": caption,
                    "long_caption": long_caption,
                    "cta": cta,
                    "format": post_format,
                    "hashtags": tags[index : index + 3],
                    "visual_direction": (
                        f"A wide view of {topic}. Use the licensed photo only, with its credit."
                    ),
                    "image_suggestion": (
                        f"A wide photo showing {topic}, used only when the licence allows it."
                    ),
                    "source_urls": urls[:2],
                }
            )
        return {
            "title": f"{brand} on {platform}",
            "concepts": concepts,
            "model": self.model,
        }
