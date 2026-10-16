"""Background work seam.

Day 1 enqueues each task on an in-process asyncio task with a limit of
one browser at a time. A later worker can replace that with a durable
queue. The task id, history, step limit, timeout, and stop flag stay
on the task record either way.
"""
