**Language:** [Русский](README.md) · English

# Backlink Checker 1.6.0

A free Windows and macOS app that checks donor pages for links to your sites, inspects those links, and optionally looks up whether the page is in Google’s index.

Pages are opened in a real Chromium browser, so links that appear after JavaScript are visible too.

Website: [artemakulov.ru/backlink-checker](https://artemakulov.ru/backlink-checker/)  
Telegram: [t.me/akulov_pro](https://t.me/akulov_pro)  
Download for Windows x64: [BacklinkChecker.exe](https://github.com/AkulovArtem/Backlink-Checker/releases/download/v1.6.0/BacklinkChecker.exe)  
Download for macOS (Apple Silicon, M1–M6): [BacklinkChecker-1.6.0-macos-arm64.dmg](https://github.com/AkulovArtem/Backlink-Checker/releases/download/v1.6.0/BacklinkChecker-1.6.0-macos-arm64.dmg)

## What’s new in 1.6.0

- Third Google-index provider: [JSON SEO](https://jsonseo.ru/docs#google-xml) alongside XMLRiver and XMLStock
- Submit unindexed donors to [SpeedyIndex](https://speedyindex.com/): automatically after a check, or manually from Actions
- Excel: “Submitted for indexing” column, submission date, and a SpeedyIndex summary
- JSON SEO and SpeedyIndex keys live in Settings; balances load automatically

## Who it’s for

- SEO specialists: bulk link-profile checks after placements
- site owners: monitoring paid links
- link builders: auditing new and existing donors
- SEO analysts: structured backlink data with Excel export

## Features

- Full JS rendering via headless Chromium
- Page scrolling to load lazy content; infinite pagination stops on its own
- Finds links to the target domains you specify, including subdomains
- Up to 100,000 donors and 50 target domains per task
- Add new donors and target domains (acceptors) to a finished task; already-checked donors are not re-run
- Resume a stopped check: already-checked rows are kept
- Optional Google index check via XMLRiver, XMLStock, or JSON SEO (only donors with a found backlink, top-10 SERP)
- Submit unindexed donors to SpeedyIndex (automatically after the check and manually from Actions)
- Pick the provider in the task form, with a live balance; URLs and keys are set in Settings
- Wipe the task database from Settings (service URLs, keys, and theme are kept)
- Multiple threads, light and dark theme, SQLite next to the exe

### Link analysis

- `rel`: dofollow, nofollow, ugc, sponsored
- anchor type: text or image (`img` + `alt`)
- anchor text: from the link, `alt`, or `title`
- HTML context: ±200 characters around the link
- canonical URL

### Indexability

For each page, separately for Google, Yandex, Bing, and Baidu:

- `robots` / `googlebot` / `yandexbot` (and similar) meta tags
- `X-Robots-Tag` HTTP header
- in the report and Excel: “Open” / “Closed” (robots), separate from “In Google index”

### Google index

- Yes / No / Error / not checked
- “IN GOOGLE” column filter in the report
- in Excel — separate columns for “In Google index”, “Google index error”, “Submitted for indexing”, and the submission date

### Technical data

HTTP status, title, HTML snippet, internal and external link counts, error codes when a page is unavailable.

## How to use

1. Run `Backlink Checker.exe` as administrator. On first launch a database is created next to the exe.
2. Open Settings and paste your XMLRiver and/or XMLStock URL and/or JSON SEO key. For indexing submissions, add a SpeedyIndex key. The balance loads automatically. Buttons: Cancel and Save. You can also wipe the task database there.
3. On the main screen click “+ Create task” and fill in the fields. For a Google index check, enable the checkbox and pick XMLRiver, XMLStock, or JSON SEO — the balance is shown next to it. To submit unindexed URLs after the check, enable “Send for indexing” (SpeedyIndex). In a finished report you can do the same manually: Actions → Send for indexing (HTTP 200, acceptor found, not in Google).
4. The check runs in several threads. Click a task to open the live report.
5. If a check was stopped: ⋮ menu → Resume check. “Retry failed” re-runs load errors only.
6. To add links or acceptors to a finished task: ⋮ menu → Add links. Only new donors are checked; old results stay.
7. Review results in the app or export to Excel (5 sheets: summary, domains, donors, backlinks, top anchors).

## Statuses and errors

| Status | Meaning |
|---|---|
| Found | page loaded, a link to a target domain is present |
| Not found | page loaded, no such link |
| Not loaded | page unavailable; see the error code |

| Code | Meaning |
|---|---|
| `TIMEOUT` | the page did not respond in time |
| `NET_ERROR` | network error (DNS, connection refused) |
| `HTTP_4xx` / `HTTP_5xx` | client or server HTTP error |
| `NO_RESPONSE` | the browser received no response |
| `PARSE_ERROR` | HTML parse error |

## System requirements

- Windows 10 / 11, 64-bit **or** macOS 12+ on Apple Silicon (M1, M2, M3, M4, M5, M6)
- 4 GB RAM minimum (8+ GB recommended with many threads)
- No installer: Windows is a single exe, macOS is a `.app` from the DMG
- Chromium is bundled; you do not need a separate browser

On Windows the database and log sit next to the exe. On macOS they live in `~/Library/Application Support/Backlink Checker/`. Log: `backlink_checker.log` (rotated at 5 MB × 3 files).

The macOS build is not signed with an Apple Developer ID. On first launch: right-click the app → Open.

## Build from source

Python 3.13 is required.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

Windows EXE:

```bat
build.bat
```

Or GitHub Actions: **Actions → Build Windows EXE → Run workflow**. Artifact: `BacklinkChecker.exe`.

macOS DMG (Apple Silicon, M1–M6):

```bash
./build_macos.sh
```

## Screenshots

[UI](https://artemakulov.ru/media/posts/63/gallery/backlink-checker-screenshot.jpg) · [Excel report](https://artemakulov.ru/media/posts/63/gallery/22.jpg)

More screenshots on the [product page](https://artemakulov.ru/backlink-checker/).
