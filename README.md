# 📅 好時光女生運動樂園 Lesson to Calendar Scraper

![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Success-blue?logo=githubactions)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

An automated calendar scraping tool that runs daily via GitHub Actions. It reads your booking / cancellation history from the booking site and converts it into the standard `.ics` format, allowing you to subscribe via Google Calendar or iOS Calendar so you never miss a class.

> **Note**: This scraper is specifically designed for **好時光女生運動樂園**(studio name). It automates the process of fetching your reserved classes and syncing them to your personal calendar.

## ✨ Features
- **Tailored for 好時光女生運動樂園**: Handles specific login flows and table structures of the booking site.
- **Log-based sync**: Reads the point-transaction ledger (Account → Passes → Details) instead of the "Upcoming" list, so waitlists and layout changes on My schedule cannot break it. Every booking and cancellation is a real, timestamped record.
- **Incremental (cursor)**: Only rows newer than the last processed transaction are fetched each run.
- **Automated Sync**: Runs via GitHub Actions.
- **Private & Free**: Host your own calendar link using GitHub Pages. No names are stored.

## 🏗️ Workflow

![image](https://github.com/Kay-Zhang1625/update_ics/blob/main/ics_flow_chart.png)

1. **Trigger**: A **Daily Cron Job** (GitHub Actions) initiates the workflow every day at 22:00 Asia/Taipei.
2. **Runtime (Ubuntu)**:
   - **Step 1: Scrape the ledger**: Python + headless Chrome log in, open Account → Passes, expand every active pass's *Details* table and read the `預約課程` / `取消課程` rows newer than the stored cursor.
   - **Step 2: Apply & replay**: New rows are appended to `ledger.json` (append-only) and the whole log is replayed to get the set of active reservations (a cancellation removes its booking).
   - **Step 3: Build ICS**: `mycalendar.ics` is rebuilt from scratch. UIDs are derived from `date|start_time|title`, so subscribers see updates rather than duplicates. Class length is assumed to be 60 minutes (`DEFAULT_DURATION_MIN` in `ledger.py`).
3. **GitHub Repository**: `ledger.json` and `mycalendar.ics` are committed and pushed back to the repository.
4. **GitHub Pages**: The latest `.ics` file is deployed as a static site, generating a permanent link for subscription.
5. **Subscription**: The final output is synced to your **Google/iOS Calendar** via the provided URL.

### Files
| File | Role |
|---|---|
| `ledger.json` | Event store: `{"cursor": "<last txn datetime>", "entries": [...]}`. Never edited by hand, never has rows deleted, never contains the User column. |
| `mycalendar.ics` | Read model rebuilt from the ledger on every run. |
| `spider_goodtime.py` | Selenium login + Passes scraper. Selectors live in the `SELECTORS` block at the top. |
| `ledger.py` | Parsing, cursor/merge, replay, ICS event derivation. |
| `gen_ics.py` | ICS builder. |
| `import_history.py` | One-off: import an exported ledger CSV (`Date,Reason,Change`) into `ledger.json`. |

## 🛠️ Tech Stack
- **Language**: Python (Selenium & BeautifulSoup)
- **CI/CD**: GitHub Actions (Ubuntu Runner)
- **Deployment**: GitHub Pages

## 🚀 Usage & Deployment

This project is a **personal calendar synchronizer**. To use it for your own classes, host your own version:

### Step 1: Fork & Setup
1. **Fork** this repository to your own GitHub account.
2. Go to your Forked repo -> **Settings** -> **Secrets and variables** -> **Actions**.
3. Add two New repository secrets:
   - `ICS_GOODTIME_USERNAME`: Your 好時光 account ID.
   - `ICS_GOODTIME_PASSWORD`: Your 好時光 password.

   *The workflow maps them to the `CRAWLER_USERNAME` / `CRAWLER_PASSWORD` environment variables the script reads via `os.environ`, so your credentials remain private even if your repository is public.*

4. Delete the upstream `ledger.json` (it holds someone else's classes) or replace it with your own via `import_history.py`. The first run then starts from an empty ledger.
5. Enable **GitHub Pages** in your repo settings (deploy from `main` branch).

### Step 2: Subscribe to Your Calendar
Once the GitHub Action runs successfully (manually trigger it or wait for the daily cron), your calendar will be available at:

`https://[YOUR_USERNAME].github.io/[REPO_NAME]/mycalendar.ics`

### Subscription Guides:
* **Google Calendar**: Go to the web version -> Click "+" next to "Other calendars" -> Select "From URL".
* **iOS Calendar**: Click "File" -> Select "New Calendar Subscription".

## 🧰 Local run & maintenance

```bash
pip install -r requirements.txt
CRAWLER_USERNAME=... CRAWLER_PASSWORD=... python main.py            # incremental
CRAWLER_USERNAME=... CRAWLER_PASSWORD=... python main.py --full-resync   # ignore cursor, re-read everything
python -m pytest tests/                                               # browser-free tests
```

- **Import history**: `python import_history.py history.csv [--events events.json]` builds `ledger.json` from a CSV exported from the Passes table (columns `Date,Reason,Change`; leave the User column out).
- **Site changed?** Open the Passes page in a browser, check the table headers / Details toggle / pagination, and update the `SELECTORS` constants at the top of `spider_goodtime.py`.
- The run fails loudly (non-zero exit, nothing written) if no active pass is found, so a broken selector never wipes the calendar.

## 📄 License
This project is licensed under the [MIT License](LICENSE).
