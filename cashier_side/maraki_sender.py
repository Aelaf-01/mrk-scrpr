import datetime
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

HOST = os.getenv("SENDER_HOST_URL", "http://192.168.1.46:5000/upload") # Web server endpoint for receiving files

def get_files_to_send():
    # Identify files for the previous date (or current date depending on cron configuration)
    yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
    date_filter = yesterday.strftime("%Y-%m-%d")
    
    # As a fallback for testing today, also check today's date
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    files_to_send = []
    for filename in os.listdir("."):
        if (date_filter in filename or today in filename) and filename.endswith(".html"):
            files_to_send.append(filename)
            
    return files_to_send

def send_files(files):
    for filename in files:
        print(f"Sending {filename} to {HOST}")
        try:
            with open(filename, "rb") as f:
                files_dict = {"file": (filename, f, "text/html")}
                response = requests.post(HOST, files=files_dict)
                if response.status_code == 200:
                    print(f"Successfully sent {filename}")
                else:
                    print(f"Failed to send {filename}: {response.status_code}")
        except Exception as e:
            print(f"Error sending {filename}: {e}")

if __name__ == "__main__":
    files = get_files_to_send()
    if files:
        send_files(files)
    else:
        print("No files found to send.")
