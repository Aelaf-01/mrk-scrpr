import os
import logging
from dotenv import load_dotenv

# Load from .env file
load_dotenv()

# --- Shared Config ---
SHARED_SECRET = os.getenv("SHARED_SECRET", "change-me-in-production")
CLIENT_ID = os.getenv("CLIENT_ID", "cashier-1")

# --- Cashier Config ---
MARAKI_BASE = os.getenv("MARAKI_BASE", "http://192.168.1.24/MarakiReports2012")
MARAKI_USER = os.getenv("MARAKI_USER", "admin")
MARAKI_PASS = os.getenv("MARAKI_PASS", "admin")
MARAKI_USER_FIELD = os.getenv("MARAKI_USER_FIELD", "txt_username")
MARAKI_PASS_FIELD = os.getenv("MARAKI_PASS_FIELD", "txt_password")

REPORT_IDS = {
    "a": os.getenv("REPORT_ID_A", "001-01-0000000040"),
    "b": os.getenv("REPORT_ID_B", "001-07-0000000001"),
    "c": os.getenv("REPORT_ID_C", "001-07-0000000009"),
    "d": os.getenv("REPORT_ID_D", "001-07-0000000053"),
}

SENDER_HOST_URL = os.getenv("SENDER_HOST_URL", "http://192.168.1.46:5000/upload")

# --- Host Config ---
RECEIVER_HOST = os.getenv("RECEIVER_HOST", "127.0.0.1")  # Don't use 0.0.0.0 for safety unless explicitly set
RECEIVER_PORT = int(os.getenv("RECEIVER_PORT", "5000"))
RECEIVER_BASE_DIR = os.getenv("RECEIVER_BASE_DIR", "htmls")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "clinic_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")

# --- Logging Setup ---
def setup_logging(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        
        # File handler
        fh = logging.FileHandler('pipeline.log')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
    return logger
