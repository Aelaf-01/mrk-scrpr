from flask import Flask, request
import os
import datetime
import re
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

app = Flask(__name__)

BASE_DIR = os.getenv("RECEIVER_BASE_DIR", "htmls")
RECEIVER_HOST = os.getenv("RECEIVER_HOST", "0.0.0.0")
RECEIVER_PORT = int(os.getenv("RECEIVER_PORT", "5000"))

def identify_client_folder(ip):
    # Extracts the last octet (YY) from IP (XXX.ZZZ.W.YY)
    match = re.match(r"\d+\.\d+\.\d+\.(\d+)", ip)
    if match:
        return match.group(1)
    return "unknown"

@app.route('/upload', methods=['POST'])
def receive_html():
    if 'file' not in request.files:
        return "No file part", 400
        
    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400
        
    client_ip = request.remote_addr
    last_octet = identify_client_folder(client_ip)
    
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    date_dir = f"{current_date}html"
    
    folder_path = os.path.join(BASE_DIR, date_dir, last_octet)
    os.makedirs(folder_path, exist_ok=True)
    
    file_path = os.path.join(folder_path, file.filename)
    file.save(file_path)
    print(f"Saved file from {client_ip} to {file_path}")
    
    return "File uploaded successfully", 200

if __name__ == "__main__":
    # Ensure BASE_DIR exists
    os.makedirs(BASE_DIR, exist_ok=True)
    app.run(host=RECEIVER_HOST, port=RECEIVER_PORT)
