# Contributing

Machaa is Apache-2.0. By opening a pull request you agree that your contribution is under that license.

## Setup

Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest
```

On Windows, activate the virtual environment with `.venv\Scripts\activate`.

`pytest` runs the Guardian, API, security, Chromium smoke, and dashboard acceptance tests. The smoke test opens `https://example.com`. The acceptance test searches for interior-design ideas. When Google shows a robot check, the test still expects real result links from the next source. It does not expect anyone to solve that check.

## What to keep true

- The Guardian stays in the tool gateway. Do not rely on a prompt to block a payment, a download, or a destructive action.
- Browser code must keep using Playwright's Chromium and the dedicated profile under the data directory. Do not attach to a personal Chrome profile.
- Day 2 does not require a paid API. Search works with no key. A Word document uses an optional free Gemini key that stays in the environment. Do not commit it. Tests that write a document use a stand-in reply, not a live key.
- Do not commit `.env`, cookies, `data/`, browser profiles, screenshots, reports, databases, or logs.
- New browser actions need an allowlist entry, a Guardian check, and a test that a dangerous call does not reach the handler.

## Pull requests

Keep a change focused. Say what a person can now do, and paste the pytest result. If a browser test fails because a site showed a robot check, say that plainly. Do not describe it as a pass.

The product is aimed at someone who is not a programmer. README quick start instructions should stay short enough to follow without reading the code.

## Conduct

Be respectful in reviews. Assume the other person wants the project to be safe and understandable.
