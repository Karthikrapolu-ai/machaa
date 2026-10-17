# Security

Machaa Day 1 runs on your computer and talks only to you on localhost. It is not a hosted service.

## Report a vulnerability

Please do not open a public GitHub issue for a security problem. Use the repository's private security advisory, or email the maintainers if that is not enabled yet. Include what you did and what you expected. Give the maintainers time to fix it before writing about it in public.

## What Day 1 protects

The Guardian is enforced in `machaa/tools/gateway.py` before a tool handler runs. A request that looks safe cannot later call a tool that is not on the allowlist. The allowlist is:

- search the public web (Google first, then an optional Brave or Google Programmable Search key, then DuckDuckGo's public HTML form)
- ask Gemini to draft a Word document from those notes, only when `GEMINI_API_KEY` is set
- open one public http or https page
- read visible text
- take a screenshot
- save that task's Markdown report
- search Wikimedia Commons and Openverse for one reusable image (public domain, CC0, CC BY, or CC BY-SA)
- write a social-post Word document from the notes and that image credit

A social request is turned into a short plan first. The Guardian checks every action in that plan before the browser starts, and checks again when the action runs. The plan cannot add a shell command or any tool that is not on the list above. Page text is still saved as text. It is not treated as a new command.

Everything else is denied. That includes a shell, a click tool, an installer download, and any browser profile other than Machaa's. An image is fetched only from Wikimedia or Openverse, only over https, and only when the licence is reusable. Otherwise the document gets a labelled placeholder, not a made-up photo.

These requests are refused:

- purchases, payments, credit cards, checkout, and other financial transactions
- banking, PayPal, Stripe, Gmail, Google account login, ChatGPT, and Gemini
- downloads, including links that end in an installer or archive
- destructive computer actions such as erasing disks or running `rm -rf`
- private and loopback addresses, raw IP addresses, and `file:` URLs
- a hostname that resolves to a private or loopback address

The browser is Playwright's Chromium with `user_data_dir` set to a directory inside Machaa's data folder. That directory is kept between tasks so the session stays on this computer. The code refuses a path outside that folder and refuses a path that looks like a personal Chrome, Chromium, or Edge profile. It does not set a Chrome channel and does not attach to a running browser.

A Google robot check, unusual-traffic page, or consent page is detected and left alone. Machaa does not solve a CAPTCHA, does not use a proxy, and does not pretend to be another browser. The next search source is a configured official API or DuckDuckGo's public HTML form. `needs_human` is used only when every source returns nothing. Optional API keys stay in the environment. They are not written into reports, screenshots, Word documents, or the page address. Gemini's reply is saved as document text. Machaa does not run it as a command. A Word request with no key stops before any call to Google.

Text from a web page is written into the report. The research plan does not read that text to decide the next action.

Docker Compose binds `127.0.0.1:8787` only, runs as uid 1000, drops capabilities, sets `no-new-privileges`, keeps the root filesystem read-only, limits memory, CPU, and process count, and does not mount the Docker socket. Inside that container the Chromium sandbox is turned off because the process is already non-root and capability-dropped. Outside Docker, the sandbox stays on unless `MACHAA_CHROMIUM_NO_SANDBOX` is set.

## What Day 1 does not protect

- There is no login. Anyone who can open `http://127.0.0.1:8787` on that computer can send a task. Do not publish the port.
- The host denylist is a list, not a complete catalog of every payment site.
- A public website can still be malicious content. Machaa will not follow its instructions, but you should read the report before acting on it.
- The Windows Companion is a separate process on the PC. It checks a bearer token on every request and refuses public internet addresses. On Windows it can also accept Docker Desktop’s private network so the dashboard can reach it. The browser never sees that token. Desktop control is off until the owner turns it on, and it can be turned off immediately. Typing, saving, and reading a file wait for Approve and stay inside Documents\Machaa. The companion will not type into a window it did not open, will not run PowerShell, and will not click a UAC or other Windows security prompt. Click the microphone and Chrome or Edge types the words in the box. If that browser cannot do it, the short recording is sent to Gemini with the key already in .env and is not saved. Optional listening for "open Machaa" stays off unless the owner turns it on. A personal Chrome profile is still refused.
- Memory is a local SQLite file. Postgres and pgvector are not running and are not a security boundary yet.

## Secrets

Do not commit `.env`, cookies, browser profiles, screenshots, reports, databases, or logs. `.gitignore` is there so those files stay on your machine. `.env.example` lists the optional search key names and `GEMINI_API_KEY` with empty values. A real key belongs only in `.env` on your machine.
