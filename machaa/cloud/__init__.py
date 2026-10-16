"""Cloud seam. Day 1 has no cloud client and no credentials.

Do not add a hosted model, a storage bucket, or an account login here
until a later day explicitly decides to. Nothing in this package should
read an API key.
"""


def configured() -> bool:
    """Day 1 is local only."""

    return False
