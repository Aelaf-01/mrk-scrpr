import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from host_side.parse_html import extract_A, read_html
from host_side.database import Database

def test():
    content_path = 'Erca-report_files/home.html'
    print(f"Reading {content_path}...")
    soup = read_html(content_path)
    
    print("Extracting A (Lines)...")
    res = extract_A(soup, "2026-09-29_a.html")
    
    invoices = res['invoices']
    print(f"Total invoices parsed: {len(invoices)}")
    
    if invoices:
        first_invoice = invoices[0]
        print(f"Attempting to insert lines for invoice {first_invoice['fs_no']} into database...")
        
        # NOTE: merge_day expects both A and B, but we can pass empty B for testing lines
        db = Database()
        try:
            db.merge_day(res['report_date'], [first_invoice], [])
            db.commit()
            print("Successfully inserted.")
        except Exception as e:
            print(f"Failed to insert: {e}")
            db.conn.rollback()
        finally:
            db.close()

if __name__ == '__main__':
    test()
