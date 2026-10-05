# Maraki Report Pipeline

Moves daily sales reports out of the legacy **MarakiReports2012** web app and into a PostgreSQL database (`clinic_db`) for the clinic's billing data, with automatic reconciliation between reports.

The pipeline has two machines:

- **Cashier side** – a PC on the clinic LAN that can reach the Maraki server. It logs in, downloads four reports per day, and uploads them.
- **Host side** – a server that receives the files, parses the HTML, loads PostgreSQL, and checks that the numbers agree.

```
 Maraki server          Cashier PC                               Host server
 (192.168.1.24)
┌────────────┐  login+POST  ┌──────────────────┐   HTTP upload   ┌────────────────┐
│ Reports    │ ───────────► │ maraki_scraper   │                 │ receive_html   │
│ (HTML)     │              │   → out/*.html   │                 │  (Flask)       │
└────────────┘              │   → out/*.json   │                 │   → htmls/     │
                            │ maraki_sender ───┼───────────────► │     DATE/      │
                            │   → sent/        │  X-Auth header  │      CLIENT/   │
                            └──────────────────┘                 └───────┬────────┘
                                                                         │ .ready marker
                                                                 ┌───────▼────────┐
                                                                 │ run_day.py     │
                                                                 │  parse_html    │
                                                                 │  database      │──► PostgreSQL
                                                                 │  reconcile     │
                                                                 └────────────────┘
```

## The four reports

| Key | Report | Contains | Stored in |
|-----|--------|----------|-----------|
| `a` | ERCA report | Invoice **lines** (item, qty, price, MRC, TIN) | `invoice_line` |
| `b` | Sales report | Invoice **headers** (customer, store, user, totals) | `invoice` |
| `c` | Sales by Sales Rep summary | Daily totals by cash/credit | `daily_payment_summary` |
| `d` | Sales summary by item sold | Daily quantity/total per item | `daily_item_summary` |

Report IDs are configurable via `.env` (`REPORT_ID_A` … `REPORT_ID_D`).

## Repository layout

```
config.py                     Settings loaded from .env, logging setup
.env.example                  Template for local configuration
seed_dev.sql                  Lookup data + one worked example invoice
test_pipeline.py              Parser and DB tests (pytest)
test_db.py                    Manual smoke test: parse report A, insert one invoice

cashier_side/
  maraki_scraper.py           Log in, fetch reports a–d for a date, write out/ + manifest
  maraki_sender.py            Upload out/ bundles to the host (outbox pattern)

host_side/
  receive_html.py             Flask upload endpoint, manifest verification
  parse_html.py               HTML → dicts for reports A, B, C, D
  database.py                 PostgreSQL access, invoice merge, summaries
  run_day.py                  Orchestrates parse → ingest → reconcile for a date
  reconcile.py                Cross-checks the reports against the database
  migrations/001_init.sql     Schema, views, summary and audit tables

tools/
  scraper.py                  Playwright crawler for exploring the Maraki site
```

## Setup

Requires Python 3.9+ and PostgreSQL.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# Cashier side
pip install requests beautifulsoup4 python-dotenv

# Host side
pip install flask waitress psycopg2-binary beautifulsoup4 python-dotenv

# Development / tools
pip install pytest playwright && playwright install chromium

cp .env.example .env                 # then edit values
```

Create the database and apply the schema:

```bash
createdb clinic_db
psql clinic_db -f host_side/migrations/001_init.sql
psql clinic_db -f seed_dev.sql       # optional dev data
```

### Configuration (`.env`)

| Variable | Used by | Purpose |
|----------|---------|---------|
| `SHARED_SECRET` | both | Value of the `X-Auth` header. **Change it.** |
| `CLIENT_ID` | cashier | Identifies this cashier PC; becomes a folder name on the host |
| `MARAKI_BASE`, `MARAKI_USER`, `MARAKI_PASS` | cashier | Maraki site and credentials |
| `MARAKI_USER_FIELD`, `MARAKI_PASS_FIELD` | cashier | Login form field names |
| `REPORT_ID_A`–`D` | cashier | Report IDs on the Maraki server |
| `SENDER_HOST_URL` | cashier | e.g. `http://192.168.1.46:5000/upload` |
| `RECEIVER_HOST`, `RECEIVER_PORT`, `RECEIVER_BASE_DIR` | host | Bind address, port, storage folder (default `htmls`) |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS` | host | PostgreSQL connection |

Never commit `.env`; it is git-ignored.

## Usage

### Cashier side (daily)

```bash
python cashier_side/maraki_scraper.py                       # today
python cashier_side/maraki_scraper.py --date 2026-09-29
python cashier_side/maraki_scraper.py --backfill-start 2026-09-01 --backfill-end 2026-09-30

python cashier_side/maraki_sender.py                        # send everything unsent
python cashier_side/maraki_sender.py --date 2026-09-29
```

The scraper writes `cashier_side/out/<date>_{a,b,c,d}.html` and `<date>.manifest.json` (file name, SHA-256, size, row count). The sender uploads the HTML files first and the manifest last, then moves the bundle to `cashier_side/sent/`. Because the manifest arrives last, the host never sees a partial day as ready.

### Host side

Start the receiver:

```bash
python host_side/receive_html.py                            # development
waitress-serve --host=127.0.0.1 --port=5000 host_side.receive_html:app   # production
```

When a manifest arrives and every checksum matches, the receiver writes `htmls/<date>/<client>/.ready`.

Process a day (defaults to yesterday, suitable for cron):

```bash
python host_side/run_day.py
python host_side/run_day.py --date 2026-09-29 --client cashier-1
python host_side/run_day.py --backfill-start 2026-09-01 --backfill-end 2026-09-30
```

`run_day.py` parses A and B and merges them into `invoice`/`invoice_line`, stores C and D, renames `.ready` to `.done`, then runs reconciliation. Exit code is non-zero if anything failed or reconciliation found issues.

Run reconciliation alone:

```bash
python host_side/reconcile.py 2026-09-29
```

### Reconciliation checks

Mismatches are written to `reconciliation_issue`.

| Kind | Meaning |
|------|---------|
| `MISSING_IN_A` / `MISSING_IN_B` | An FS number is present in only one of the line/header reports |
| `INVOICE_ERROR` | An invoice failed to insert |
| `C_TOTAL_MISMATCH` | Report C total by payment type differs from invoices by more than 1.0 |
| `D_QTY_MISMATCH` | Report D item quantity differs from the sum of invoice lines |

### Site crawler (`tools/scraper.py`)

A three-stage Playwright tool for discovering reports and form fields on the Maraki site. It opens a visible browser so you can log in manually.

```bash
python tools/scraper.py map          # crawl links  → output/link_map.json
python tools/scraper.py structure    # page details → output/site_structure.json
python tools/scraper.py scrape       # data tables  → output/tables/
python tools/scraper.py all
```

It skips links that look destructive (logout, delete, remove, drop, truncate) and stays under `/MarakiReports2012/`.

## Data notes

- **Item ID** such as `18s2` means catalogue item 18, line 2 on the invoice. It is split into `service.item_no` and `invoice_line.line_no`.
- `CRSI-…` references are credit invoices; everything else is treated as cash.
- Reports are served as cp1252 and saved as UTF-8.
- Physician names are not in the source data; only specialties are known.

## Testing

```bash
pytest test_pipeline.py
```

- Parser tests need the saved fixture folders (`Erca-report_files/`, `Sales report_files/`, etc.), which are git-ignored and must be supplied locally.
- Database tests skip if PostgreSQL is unreachable. **They `TRUNCATE` tables in the configured database, so point `DB_NAME` at a throwaway database.**

## Security notes

- Change `SHARED_SECRET` and the default `admin/admin` Maraki credentials before deployment.
- The receiver binds to `127.0.0.1` by default; put it behind a reverse proxy or VPN if cashier PCs are remote. Traffic is plain HTTP.

## Known issues

See the *Known issues* section in [CHANGELOG.md](CHANGELOG.md).
