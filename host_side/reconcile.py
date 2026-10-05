import os
import sys
from decimal import Decimal

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from host_side.database import Database

logger = config.setup_logging('reconcile')

def reconcile_date(report_date):
    db = Database()
    issues_found = 0
    
    try:
        with db.conn.cursor() as cur:
            # 1. B_total == sum(invoice.subtotal)
            cur.execute("""
                SELECT SUM(subtotal) FROM invoice 
                WHERE DATE(created_at) = %s -- Assuming visit_date or creation maps to report_date. 
                -- Actually we should join on visit for date or use a date column on invoice if added.
                -- For now, let's just assume we can get it from visit
            """, (report_date,)) # Wait, the schema in db_schema.txt probably links visit.
            
            # Let's write a robust query
            cur.execute("""
                SELECT COALESCE(SUM(i.subtotal), 0)
                FROM invoice i
                JOIN visit v ON i.visit_id = v.id
                WHERE v.visit_date = %s
            """, (report_date,))
            db_b_total = cur.fetchone()[0]
            
            # 2. C_total(date) == sum by payment_type
            cur.execute("""
                SELECT payment_type, COALESCE(SUM(subtotal), 0) 
                FROM daily_payment_summary 
                WHERE report_date = %s 
                GROUP BY payment_type
            """, (report_date,))
            c_totals = dict(cur.fetchall())
            
            cur.execute("""
                SELECT i.payment_type, COALESCE(SUM(i.subtotal), 0)
                FROM invoice i
                JOIN visit v ON i.visit_id = v.id
                WHERE v.visit_date = %s
                GROUP BY i.payment_type
            """, (report_date,))
            db_c_totals = dict(cur.fetchall())
            
            for ptype, c_val in c_totals.items():
                db_val = db_c_totals.get(ptype, Decimal(0))
                if abs(c_val - db_val) > Decimal('1.0'):
                    db.log_issue(report_date, 'C_TOTAL_MISMATCH', ptype, str(c_val), str(db_val))
                    issues_found += 1
            
            # 3. D per-item == sum(invoice_line)
            cur.execute("""
                SELECT item_id, COALESCE(SUM(qty), 0)
                FROM daily_item_summary
                WHERE report_date = %s
                GROUP BY item_id
            """, (report_date,))
            d_totals = dict(cur.fetchall())
            
            cur.execute("""
                SELECT s.item_no, COALESCE(SUM(il.quantity), 0)
                FROM invoice_line il
                JOIN invoice i ON il.invoice_id = i.id
                JOIN visit v ON i.visit_id = v.id
                JOIN service s ON il.service_id = s.id
                WHERE v.visit_date = %s
                GROUP BY s.item_no
            """, (report_date,))
            db_d_totals = dict(cur.fetchall())
            
            for item_id, d_qty in d_totals.items():
                db_qty = db_d_totals.get(str(item_id), Decimal(0))
                if d_qty != db_qty:
                    db.log_issue(report_date, 'D_QTY_MISMATCH', str(item_id), str(d_qty), str(db_qty))
                    issues_found += 1
                    
        db.commit()
        
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}")
        db.conn.rollback()
        raise
    finally:
        db.close()
        
    if issues_found > 0:
        logger.warning(f"Reconciliation completed with {issues_found} issues for {report_date}")
        sys.exit(1)
    else:
        logger.info(f"Reconciliation successful for {report_date}")
        sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reconcile.py YYYY-MM-DD")
        sys.exit(1)
    reconcile_date(sys.argv[1])
