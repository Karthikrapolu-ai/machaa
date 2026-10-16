# MACHAA

Machaa is an open-source personal AI computer you run on your own machine. You type a request in a local chat window. Machaa opens a browser that belongs to it, does the task, and shows you the screenshot and a short report.

Day 1 is deliberately small. It can search Google and open one public website. It cannot spend money, download files, or control your desktop. Those limits are in code, not only in a prompt.

No API key. No cloud account. No login to ChatGPT, Gemini, Gmail, or a bank.

## Quick start

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and open it. Then:

| | What you do |
| --- | --- |
| **Windows** | Unzip this project. Double-click `start.bat`. |
| **Mac** | Open Terminal in this folder and run `./start.sh`. |
| **Linux** | Open a terminal in this folder and run `./start.sh`. |

Leave that window open. In your web browser, go to:

**http://127.0.0.1:8787**

Type this and press Send:

```text
Open Google and search for simple 2BHK interior design ideas
```

Machaa opens Chromium and searches Google. The report lists the result titles and links, and the card shows a screenshot of that results page. The browser profile lives in Machaa's data folder (`data/browser-profile`, or the Docker volume) and is kept for the next time you start Machaa. That profile belongs to Machaa. A personal Chrome profile is refused.

If Google shows a robot check or a consent page, Machaa leaves that page alone and uses DuckDuckGo's public results instead. The card still says **Completed** when those results come back. A person is asked only when every source comes back empty. No API key is required. A free Brave Search key or a free Google Programmable Search key can be added in `.env` if you want those official APIs used first. See `.env.example`.

To stop Machaa, click the terminal window and press Ctrl+C.

You do not need Python, an API key, or a GitHub login to run it this way.

## Try a blocked request

```text
Buy a sofa and pay with my credit card at checkout
```

The card turns **Blocked**. Chromium does not open. The same thing happens for a checkout link, a file download, or a request to erase the disk.

## What Day 1 does

- Search Google, and use DuckDuckGo (or an optional free search API) when Google shows a check.
- Open one public `http` or `https` website.
- Read the visible text.
- Save a Markdown research report and a screenshot.
- Show the task, the steps, and a Stop button in the dashboard.
- Keep a local history of task ids.

A task stops on its own if it takes more than 120 seconds or more than 8 actions.

## What it will not do

- Buy, pay, check out, or type a credit card.
- Open banking, PayPal, Gmail, ChatGPT, or Gemini.
- Download a file.
- Run a shell command, delete files, or shut the computer down.
- Attach to your personal Chrome, Chromium, or Edge profile.
- Call a paid AI API. The steps above are fixed. A later release can add planning. See [ROADMAP.md](ROADMAP.md).

## How it is put together

```mermaid
flowchart TD
  you[You, in the MACHAA window] --> api[FastAPI on this computer]
  api --> guardian[Guardian]
  guardian -->|search or one public page| research[Research agent]
  guardian -->|payment, download, or destructive| blocked[Blocked task]
  research --> gateway[Tool gateway]
  gateway --> guardian
  gateway --> browser[Playwright Chromium, dedicated profile]
  browser --> report[Report and screenshot]
  report --> you
```

The pieces that are only seams today: the orchestrator, a computer agent, a work/code agent, Postgres with pgvector, a background queue, an optional cloud runtime, and a desktop companion. The folders are in the repository. They do not run yet. [ROADMAP.md](ROADMAP.md) says what they are for, including saying "open Machaa" out loud.

## Safety

The Guardian's allowlist is checked in the tool gateway before a browser action runs. Wording the request nicely does not bypass it. Page text is saved into the report. It is not treated as a new command.

The Docker setup is local and restricted:

- The process runs as user `machaa`, not root.
- Memory is limited to 2 GB, CPU to 2, and the process count is capped.
- The filesystem is read-only except for Machaa's data volume and a small temp folder.
- The Docker socket is not mounted. The container is not privileged.
- The site is published on `127.0.0.1` only.

Day 1 has no password. Do not forward port 8787 to the internet. Details are in [SECURITY.md](SECURITY.md).

## Develop

For people changing the code. You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest
```

`python -m machaa` starts the same dashboard without Docker, at http://127.0.0.1:8787. Copy `.env.example` to `.env` only if you want to change a port, a limit, or an optional search key. Leave the key lines empty to run with no key. Do not commit a filled-in `.env`.

Runtime files under `data/` (the browser profile, cookies, screenshots, reports, and the database) are gitignored. Do not commit them.

## License

Apache-2.0. See [LICENSE](LICENSE). Contributions are welcome under the same license. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
