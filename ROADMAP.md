# Roadmap

Day 1 is a local research action with a Guardian. Nothing below is implemented. The packages exist so later work has a place to land.

## Orchestrator

`machaa/core/orchestrator.py` routes one sentence to a single agent. A later orchestrator can split work across the research, computer, and work agents, and can hand long jobs to the background queue.

## Research agent

Today this agent searches Google or opens one public page, then saves a screenshot and a Markdown report. Later it can follow a few public sources, compare them, and cite them. It should keep ignoring instructions that are written on the page.

## Computer agent

`machaa/agents/computer.py` is a stub. Personal desktop control, the mouse, and the keyboard belong here, behind the Guardian. Day 1 does not move the pointer or type into other apps.

## Work and code agent

`machaa/agents/work.py` is a stub. Editing a repository and running that project's tests belong here. Day 1 does not run a shell.

## Memory

`machaa/memory` stores a short note in SQLite after a task. The planned store is Postgres with pgvector, behind the same `add` and `search` methods. Day 1 does not run Postgres.

## Background tasks

The API process runs one browser task at a time. A later queue can run work after the dashboard is closed and can retry a failed task. Task ids, history, step limits, timeouts, and the stop flag should stay.

## Cloud

`machaa/cloud` is empty on purpose. An optional cloud runtime would be off unless the owner turns it on, and it would not ship with a credential in the repository. Day 1 uses no paid API and no cloud resource.

## Desktop companion and voice

`machaa/companion` runs on the owner's Windows PC, outside Docker. It can open Notepad, Calculator, and File Explorer, type into the Notepad it opened, and save a text file in Documents\Machaa after approval. The phrase "open Machaa" focuses the dashboard while that companion is running. Optional wake listening stays off unless the owner turns it on. The companion must not point Machaa at a personal Chrome profile. Unrestricted mouse and keyboard control are still not built.

## Planning

Search and Word documents still use a fixed list of steps. A social post asks Gemini (or a labelled stand-in when no key is set) for a short list of allowlisted actions. The Guardian checks the whole list before anything runs, and checks each action again at execution. The model cannot run a shell. Later planning can cover more of the same allowlist. The Guardian still has to approve every tool call.
