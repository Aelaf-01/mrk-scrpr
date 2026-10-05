import os
import sys
import time
import json
import hashlib
import argparse
import datetime
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = config.setup_logging('maraki_scraper')

class MarakiScraper:
    def __init__(self):
        self.session = requests.Session()
        # Setup retries for transient errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.out_dir = os.path.join(os.path.dirname(__file__), "out")
        os.makedirs(self.out_dir, exist_ok=True)

    def is_login_page(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        return len(soup.find_all('input', type='password')) > 0

    def login(self):
        login_url = f"{config.MARAKI_BASE}/index.php"
        logger.info(f"Logging in to {login_url}")
        
        # We might need to get the page first to capture any CSRF tokens if they exist
        try:
            resp = self.session.get(login_url)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to access login page: {e}")
            raise

        data = {
            config.MARAKI_USER_FIELD: config.MARAKI_USER,
            config.MARAKI_PASS_FIELD: config.MARAKI_PASS,
            "btn_login": "Login"  # common submit button name
        }
        
        resp = self.session.post(login_url, data=data)
        resp.raise_for_status()
        
        if self.is_login_page(resp.text):
            raise Exception("Login failed. Check credentials and field names.")
            
        logger.info("Login successful.")

    def fetch_report(self, key, date, retry=True):
        url = f"{config.MARAKI_BASE}/reports/MasterReportSummary03.php"
        
        form_data = {
            "sel_report_ID": config.REPORT_IDS[key],
            "mode": "0",
            "btn_show": "Show", # typical submit button
        }
        
        if key in ['a', 'b']:
            form_data.update({
                "op_trans_date": "Between",
                "txt_trans_date": date,
                "txt2_trans_date": date,
                "txt_is_void": "0"
            })
        elif key == 'd':
            form_data.update({
                "op_varTransDate": "Between",
                "txt_varTransDate": date,
                "txt2_varTransDate": date
            })
        elif key == 'c':
            form_data.update({
                "op_trans_date": "Between",
                "txt_trans_date": date,
                "txt2_trans_date": date
            })

        logger.info(f"Fetching report {key} for date {date}")
        resp = self.session.post(url, data=form_data)
        resp.raise_for_status()
        
        # Decode as cp1252
        resp.encoding = 'cp1252'
        html = resp.text

        if self.is_login_page(html):
            if retry:
                logger.warning("Session expired. Re-logging in and retrying...")
                self.login()
                return self.fetch_report(key, date, retry=False)
            else:
                raise Exception("Session expired and retry failed.")

        if 'StyleReportDataTr' not in html and 'No Data Found' not in html and 'No records found' not in html:
            logger.error(f"Unexpected response for report {key}: 'StyleReportDataTr' not found")
            raise Exception(f"Failed to fetch valid report {key}. HTML snippet: {html[:200]}")

        return html

    def process_date(self, date_str):
        manifest_path = os.path.join(self.out_dir, f"{date_str}.manifest.json")
        manifest = []
        
        for key in ['a', 'b', 'c', 'd']:
            html = self.fetch_report(key, date_str)
            
            # Count rows roughly
            soup = BeautifulSoup(html, 'html.parser')
            rows = len(soup.find_all('tr', class_='StyleReportDataTr'))
            
            # Re-encode to utf-8 and update charset
            if soup.meta and soup.meta.get('charset'):
                soup.meta['charset'] = 'utf-8'
            
            utf8_html = str(soup)
            html_bytes = utf8_html.encode('utf-8')
            sha256_hash = hashlib.sha256(html_bytes).hexdigest()
            size = len(html_bytes)
            
            filename = f"{date_str}_{key}.html"
            filepath = os.path.join(self.out_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(html_bytes)
                
            logger.info(f"Saved {filename} ({rows} rows)")
            
            manifest.append({
                "file": filename,
                "sha256": sha256_hash,
                "bytes": size,
                "row_count": rows
            })
            
            time.sleep(1) # Polite delay
            
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"Saved manifest for {date_str}")


def main():
    parser = argparse.ArgumentParser(description="Maraki Report Scraper")
    parser.add_argument("--date", help="Date to scrape in YYYY-MM-DD format (default: today)")
    parser.add_argument("--backfill-start", help="Start date for backfill (YYYY-MM-DD)")
    parser.add_argument("--backfill-end", help="End date for backfill (YYYY-MM-DD)")
    args = parser.parse_args()

    scraper = MarakiScraper()
    scraper.login()

    dates_to_process = []
    if args.backfill_start and args.backfill_end:
        start = datetime.datetime.strptime(args.backfill_start, "%Y-%m-%d").date()
        end = datetime.datetime.strptime(args.backfill_end, "%Y-%m-%d").date()
        delta = datetime.timedelta(days=1)
        curr = start
        while curr <= end:
            dates_to_process.append(curr.strftime("%Y-%m-%d"))
            curr += delta
    else:
        date_str = args.date or datetime.date.today().strftime("%Y-%m-%d")
        dates_to_process.append(date_str)

    for d in dates_to_process:
        scraper.process_date(d)


if __name__ == "__main__":
    main()
