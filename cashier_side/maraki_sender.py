import os
import sys
import json
import time
import shutil
import argparse
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = config.setup_logging('maraki_sender')

class MarakiSender:
    def __init__(self):
        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.out_dir = os.path.join(os.path.dirname(__file__), "out")
        self.sent_dir = os.path.join(os.path.dirname(__file__), "sent")
        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.sent_dir, exist_ok=True)
        
        self.headers = {
            "X-Auth": config.SHARED_SECRET,
            "X-Client-Id": config.CLIENT_ID
        }

    def get_manifests_to_send(self, target_date=None):
        manifests = []
        for filename in os.listdir(self.out_dir):
            if filename.endswith(".manifest.json"):
                if target_date and not filename.startswith(f"{target_date}.manifest"):
                    continue
                manifests.append(filename)
        return manifests

    def send_file(self, filepath):
        filename = os.path.basename(filepath)
        logger.info(f"Sending {filename} to {config.SENDER_HOST_URL}")
        
        try:
            with open(filepath, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                response = self.session.post(
                    config.SENDER_HOST_URL, 
                    files=files, 
                    headers=self.headers,
                    timeout=30
                )
                response.raise_for_status()
                logger.info(f"Successfully sent {filename}")
                return True
        except Exception as e:
            logger.error(f"Failed to send {filename}: {e}")
            return False

    def process_outbox(self, target_date=None):
        manifests = self.get_manifests_to_send(target_date)
        if not manifests:
            logger.info("No manifests found in outbox.")
            return

        for manifest_file in manifests:
            manifest_path = os.path.join(self.out_dir, manifest_file)
            try:
                with open(manifest_path, 'r') as f:
                    manifest_data = json.load(f)
            except Exception as e:
                logger.error(f"Could not read manifest {manifest_file}: {e}")
                continue

            all_success = True
            files_to_move = []
            
            # Send HTML files first
            for item in manifest_data:
                html_file = item["file"]
                html_path = os.path.join(self.out_dir, html_file)
                if not os.path.exists(html_path):
                    logger.error(f"Missing file referenced in manifest: {html_file}")
                    all_success = False
                    break
                    
                if self.send_file(html_path):
                    files_to_move.append(html_path)
                else:
                    all_success = False
                    break
            
            # Send manifest last if all HTML files succeeded
            if all_success:
                if self.send_file(manifest_path):
                    files_to_move.append(manifest_path)
                    
                    # Move to sent dir
                    for p in files_to_move:
                        shutil.move(p, os.path.join(self.sent_dir, os.path.basename(p)))
                    logger.info(f"Completed sending bundle for {manifest_file}")
                else:
                    logger.error(f"Failed to send manifest {manifest_file}")


def main():
    parser = argparse.ArgumentParser(description="Maraki Sender (Outbox Pattern)")
    parser.add_argument("--date", help="Specific date to send (YYYY-MM-DD). If omitted, sends all unsent.")
    args = parser.parse_args()

    sender = MarakiSender()
    sender.process_outbox(args.date)


if __name__ == "__main__":
    main()
