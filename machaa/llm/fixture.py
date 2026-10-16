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
                f"{brand}: {topic}, with a finished look and room left to walk.",
            ),
            (
                "One strong wall",
                f"For {audience}, this {platform} idea keeps {topic} to one material and one colour.",
            ),
            (
                "Evening light",
                f"{brand} on {platform}: {topic} after dark, with warm lamps and clear surfaces.",
            ),
        ]
        tags = ["#InteriorDesign", "#2BHK", "#HomeInspo", "#AffordableLuxury", "#VistaaraInteriors"]
        concepts = []
        for index, (name, caption) in enumerate(angles):
            concepts.append(
                {
                    "name": name,
                    "caption": caption,
                    "hashtags": tags[index : index + 3],
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
