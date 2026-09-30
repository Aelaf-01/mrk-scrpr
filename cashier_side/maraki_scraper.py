import time
import datetime
import requests
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Placeholder for actual parsing logic
def parser(link):
    try:
        response = requests.get(link)
        return response.text
    except Exception as e:
        print(f"Error scraping {link}: {e}")
        return f"<html><body>Dummy data for {link}</body></html>"

def run_scraper(links):
    current_time = datetime.datetime.now()
    # Check if end session or midnight (simulated with 00:00 check)
    if current_time.hour == 0 and current_time.minute == 0 or True: # Added 'or True' for testing/running immediately
        current_date_str = current_time.strftime("%Y-%m-%d")
        
        for identifier, link in links.items():
            html_content = parser(link)
            filename = f"{current_date_str}_{identifier}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"Saved {filename}")

if __name__ == "__main__":
    links_to_scrape = {
        "a": os.getenv("SCRAPER_LINK_A", "http://example.com/erca"),
        "b": os.getenv("SCRAPER_LINK_B", "http://example.com/sales"),
        "c": os.getenv("SCRAPER_LINK_C", "http://example.com/sales_rep"),
        "d": os.getenv("SCRAPER_LINK_D", "http://example.com/sales_summary")
    }
    
    print("Running scraper...")
    run_scraper(links_to_scrape)
