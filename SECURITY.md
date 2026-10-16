# Security

Machaa Day 1 runs on your computer and talks only to you on localhost. It is not a hosted service.

## Report a vulnerability

Please do not open a public GitHub issue for a security problem. Use the repository's private security advisory, or email the maintainers if that is not enabled yet. Include what you did and what you expected. Give the maintainers time to fix it before writing about it in public.

## What Day 1 protects

The Guardian is enforced in `machaa/tools/gateway.py` before a tool handler runs. A request that looks safe cannot later call a tool that is not on the allowlist. The allowlist is:

- search Google
- open one public http or https page
- read visible text
- take a screenshot
- save that task's Markdown report

Everything else is denied. That includes a shell, a click tool, a download tool, and any browser profile other than Machaa's.

These requests are refused:

- purchases, payments, credit cards, checkout, and other financial transactions
- banking, PayPal, Stripe, Gmail, Google account login, ChatGPT, and Gemini
- downloads, including links that end in an installer or archive
- destructive computer actions such as erasing disks or running `rm -rf`
- private and loopback addresses, raw IP addresses, and `file:` URLs
- a hostname that resolves to a private or loopback address

The browser is Playwright's Chromium with `user_data_dir` set to a directory inside Machaa's data folder. The code refuses a path outside that folder and refuses a path that looks like a personal Chrome, Chromium, or Edge profile. It does not set a Chrome channel and does not attach to a running browser.

Text from a web page is written into the report. The research plan does not read that text to decide the next action.

Docker Compose binds `127.0.0.1:8787` only, runs as uid 1000, drops capabilities, sets `no-new-privileges`, keeps the root filesystem read-only, limits memory, CPU, and process count, and does not mount the Docker socket. Inside that container the Chromium sandbox is turned off because the process is already non-root and capability-dropped. Outside Docker, the sandbox stays on unless `MACHAA_CHROMIUM_NO_SANDBOX` is set.

## What Day 1 does not protect

- There is no login. Anyone who can open `http://127.0.0.1:8787` on that computer can send a task. Do not publish the port.
- The host denylist is a list, not a complete catalog of every payment site.
- A public website can still be malicious content. Machaa will not follow its instructions, but you should read the report before acting on it.
- Advanced planning, voice activation ("open Machaa"), and personal desktop control are not built. Do not assume they are sandboxed until they exist and have their own review.
- Memory is a local SQLite file. Postgres and pgvector are not running and are not a security boundary yet.

## Secrets

Do not commit `.env`, cookies, browser profiles, screenshots, reports, databases, or logs. `.gitignore` is there so those files stay on your machine. `.env.example` has no keys because Day 1 does not use any.
