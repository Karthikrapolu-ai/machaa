"""Work and code agent. Not implemented on Day 1.

Later this agent may edit a repository and run a project's tests.
Day 1 does not run a shell and does not write outside a task's report folder.
"""

from machaa.agents.base import AgentInfo

WORK_AGENT = AgentInfo(
    name="work",
    available=False,
    summary=(
        "The work agent is not built yet. "
        "Day 1 can search Google or open a public website."
    ),
)
