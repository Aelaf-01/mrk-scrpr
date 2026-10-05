import os
import sys
import glob
import argparse
import datetime

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from host_side.parse_html import parse_file
from host_side.database import Database
from host_side.reconcile import reconcile_date

logger = config.setup_logging('run_day')

def process_day(date_str, client_id=None):
    logger.info(f"Processing day {date_str} for client {client_id or 'all'}")
    
    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config.RECEIVER_BASE_DIR, date_str)
    if not os.path.exists(base_dir):
        logger.error(f"No data directory found for {date_str}")
        return False
        
    client_dirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    if client_id:
        client_dirs = [d for d in client_dirs if os.path.basename(d) == client_id]
        
    success = True
    for c_dir in client_dirs:
        logger.info(f"Processing client {os.path.basename(c_dir)}")
        
        # Check if files exist
        a_file = glob.glob(os.path.join(c_dir, "*_a.html"))
        b_file = glob.glob(os.path.join(c_dir, "*_b.html"))
        c_file = glob.glob(os.path.join(c_dir, "*_c.html"))
        d_file = glob.glob(os.path.join(c_dir, "*_d.html"))
        
        if not (a_file and b_file and c_file and d_file):
            logger.error(f"Missing HTML files for {date_str} in {c_dir}")
            success = False
            continue
            
        try:
            db = Database()
            
            # Parse A and B
            logger.info("Parsing A (Lines) and B (Headers)")
            a_data = parse_file(a_file[0])
            b_data = parse_file(b_file[0])
            
            # Merge and ingest A & B
            logger.info("Merging and ingesting into DB")
            db.merge_day(date_str, a_data['invoices'], b_data['invoices'])
            
            # Parse and ingest C
            logger.info("Parsing and ingesting C (Payment Summary)")
            c_data = parse_file(c_file[0])
            db.store_C(date_str, c_data['rows'])
            
            # Parse and ingest D
            logger.info("Parsing and ingesting D (Item Summary)")
            d_data = parse_file(d_file[0])
            db.store_D(date_str, d_data['rows'])
            
            db.commit()
            
            # Mark ready file as done
            ready_marker = os.path.join(c_dir, '.ready')
            if os.path.exists(ready_marker):
                os.rename(ready_marker, os.path.join(c_dir, '.done'))
                
            logger.info(f"Successfully processed data for {date_str}")
            
        except Exception as e:
            logger.error(f"Error processing {date_str}: {e}")
            if 'db' in locals() and db.conn:
                db.conn.rollback()
            success = False
        finally:
            if 'db' in locals():
                db.close()
                
    if success:
        logger.info("Running reconciliation...")
        try:
            reconcile_date(date_str)
        except SystemExit as e:
            if e.code != 0:
                logger.error("Reconciliation found issues")
                return False
    return success

def main():
    parser = argparse.ArgumentParser(description="Maraki Report Daily Parser & Ingester")
    parser.add_argument("--date", help="Date to parse in YYYY-MM-DD format")
    parser.add_argument("--client", help="Optional client ID to process")
    parser.add_argument("--backfill-start", help="Start date for backfill (YYYY-MM-DD)")
    parser.add_argument("--backfill-end", help="End date for backfill (YYYY-MM-DD)")
    args = parser.parse_args()

    dates_to_process = []
    if args.backfill_start and args.backfill_end:
        start = datetime.datetime.strptime(args.backfill_start, "%Y-%m-%d").date()
        end = datetime.datetime.strptime(args.backfill_end, "%Y-%m-%d").date()
        delta = datetime.timedelta(days=1)
        curr = start
        while curr <= end:
            dates_to_process.append(curr.strftime("%Y-%m-%d"))
            curr += delta
    elif args.date:
        dates_to_process.append(args.date)
    else:
        # Default to yesterday if not specified (typical cron job)
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        dates_to_process.append(yesterday)

    all_success = True
    for d in dates_to_process:
        if not process_day(d, args.client):
            all_success = False

    if not all_success:
        sys.exit(1)

if __name__ == "__main__":
    main()
