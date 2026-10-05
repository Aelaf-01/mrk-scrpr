import os
import sys
import re
import json
import hashlib
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import tempfile

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = config.setup_logging('receive_html')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 # 50MB max

VALID_FILENAME_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})_([abcd])\.html$|^(\d{4}-\d{2}-\d{2})\.manifest\.json$')

def verify_manifest(date_dir, manifest_data):
    # Verify all files present and checksums match
    for item in manifest_data:
        filepath = os.path.join(date_dir, item['file'])
        if not os.path.exists(filepath):
            logger.warning(f"Manifest verification failed: missing {item['file']}")
            return False
        
        with open(filepath, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
            
        if file_hash != item['sha256']:
            logger.warning(f"Manifest verification failed: hash mismatch for {item['file']}")
            return False
            
    return True

@app.route('/upload', methods=['POST'])
def upload_file():
    auth_header = request.headers.get('X-Auth')
    if auth_header != config.SHARED_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
        
    client_id = request.headers.get('X-Client-Id', request.remote_addr)
    
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    filename = secure_filename(file.filename)
    match = VALID_FILENAME_RE.match(filename)
    if not match:
        return jsonify({"error": "Invalid filename format"}), 400
        
    # Extract date from filename
    date_str = match.group(1) or match.group(3)
    
    # Setup directory structure: RECEIVER_BASE_DIR / date / client_id
    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config.RECEIVER_BASE_DIR)
    target_dir = os.path.join(base_dir, date_str, client_id)
    os.makedirs(target_dir, exist_ok=True)
    
    target_path = os.path.join(target_dir, filename)
    
    # Write atomically
    fd, tmp_path = tempfile.mkstemp(dir=target_dir)
    try:
        with os.fdopen(fd, 'wb') as f:
            file.save(f)
        os.rename(tmp_path, target_path)
        logger.info(f"Received and saved {filename} from {client_id}")
    except Exception as e:
        os.remove(tmp_path)
        logger.error(f"Error saving {filename}: {e}")
        return jsonify({"error": "Server error saving file"}), 500

    # If it's a manifest, trigger verification and readiness
    if filename.endswith('.manifest.json'):
        try:
            with open(target_path, 'r') as f:
                manifest_data = json.load(f)
                
            if verify_manifest(target_dir, manifest_data):
                ready_marker = os.path.join(target_dir, '.ready')
                with open(ready_marker, 'w') as f:
                    f.write('ready')
                logger.info(f"Verified manifest and wrote .ready marker for {date_str} from {client_id}")
            else:
                logger.error(f"Manifest verification failed for {filename}")
                return jsonify({"error": "Manifest verification failed"}), 400
        except Exception as e:
            logger.error(f"Error processing manifest {filename}: {e}")
            return jsonify({"error": "Error processing manifest"}), 500

    return jsonify({"success": True, "message": f"File {filename} received"}), 200

if __name__ == '__main__':
    host = config.RECEIVER_HOST
    port = config.RECEIVER_PORT
    logger.info(f"Starting receiver on {host}:{port}")
    # In production, use waitress or gunicorn
    # pip install waitress
    # waitress-serve --host=127.0.0.1 --port=5000 host_side.receive_html:app
    app.run(host=host, port=port)
