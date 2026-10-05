import os
import sys
import json
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = config.setup_logging('database')

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASS,
            host=config.DB_HOST,
            port=config.DB_PORT
        )
        self.conn.autocommit = False

    def close(self):
        if self.conn:
            self.conn.close()

    def get_or_create_store(self, store_name):
        if not store_name:
            return None
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO store (name, location)
                VALUES (%s, 'Unknown')
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """, (store_name,))
            return cur.fetchone()[0]

    def get_or_create_user(self, username):
        if not username:
            return None
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_user (username, role)
                VALUES (%s, 'Cashier')
                ON CONFLICT (username) DO UPDATE SET username = EXCLUDED.username
                RETURNING id;
            """, (username,))
            return cur.fetchone()[0]

    def get_or_create_employee(self, name):
        if not name:
            return None
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO employee (first_name, role)
                VALUES (%s, 'Sales Rep')
                ON CONFLICT (first_name, last_name) DO UPDATE SET first_name = EXCLUDED.first_name
                RETURNING id;
            """, (name,))
            return cur.fetchone()[0]

    def get_or_create_mrc(self, mrc_code):
        if not mrc_code:
            return None
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO fiscal_device (mrc_code, device_type)
                VALUES (%s, 'Default')
                ON CONFLICT (mrc_code) DO UPDATE SET mrc_code = EXCLUDED.mrc_code
                RETURNING id;
            """, (mrc_code,))
            return cur.fetchone()[0]

    def get_or_create_invoice_type(self, code):
        if not code:
            code = 'CSI'
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO invoice_type (code, description)
                VALUES (%s, 'Auto-generated type')
                ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
                RETURNING id;
            """, (code,))
            return cur.fetchone()[0]

    def get_or_create_patient(self, name, tin):
        if not name:
            name = "Unknown Customer"
        with self.conn.cursor() as cur:
            # NOTE: names are not unique. This accepts the risk for simplicity
            cur.execute("""
                INSERT INTO patient (full_name, tin_no)
                VALUES (%s, %s)
                ON CONFLICT (full_name) DO UPDATE SET tin_no = COALESCE(EXCLUDED.tin_no, patient.tin_no)
                RETURNING id;
            """, (name, tin))
            return cur.fetchone()[0]

    def get_or_create_visit(self, patient_id, date):
        with self.conn.cursor() as cur:
            # Simplified visit creation
            cur.execute("""
                INSERT INTO visit (patient_id, visit_date, status)
                VALUES (%s, %s, 'Completed')
                RETURNING id;
            """, (patient_id, date))
            return cur.fetchone()[0]

    def get_or_create_service(self, item_no, description, unit_price):
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM service WHERE item_no = %s", (item_no,))
            res = cur.fetchone()
            if res:
                return res[0]
            
            logger.warning(f"New service detected: {item_no} - {description}")
            cur.execute("""
                INSERT INTO service (item_no, name, category, default_price)
                VALUES (%s, %s, 'Uncategorized', %s)
                RETURNING id;
            """, (item_no, description, unit_price))
            return cur.fetchone()[0]

    def log_issue(self, report_date, kind, ref, expected, actual):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO reconciliation_issue (report_date, kind, ref, expected, actual)
                VALUES (%s, %s, %s, %s, %s)
            """, (report_date, kind, ref, expected, actual))

    def is_file_ingested(self, sha256):
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM ingest_log WHERE file_sha256 = %s AND status = 'SUCCESS'", (sha256,))
            return cur.fetchone() is not None

    def log_ingest(self, report_date, report_type, sha256, rows_count, status, error=None):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ingest_log (report_date, report_type, file_sha256, rows_count, status, error)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (report_date, report_type, file_sha256) 
                DO UPDATE SET status = EXCLUDED.status, error = EXCLUDED.error, ingested_at = CURRENT_TIMESTAMP
            """, (report_date, report_type, sha256, rows_count, status, error))

    def merge_day(self, report_date, A_data, B_data):
        # A_data is invoices from A (lines), B_data is invoices from B (headers)
        a_map = {inv['fs_no']: inv for inv in A_data}
        b_map = {inv['fs_no']: inv for inv in B_data}
        
        all_fs = set(a_map.keys()) | set(b_map.keys())
        
        for fs_no in all_fs:
            a_inv = a_map.get(fs_no)
            b_inv = b_map.get(fs_no)
            
            if not a_inv:
                self.log_issue(report_date, 'MISSING_IN_A', fs_no, 'Present in B', 'Missing in A')
            if not b_inv:
                self.log_issue(report_date, 'MISSING_IN_B', fs_no, 'Present in A', 'Missing in B')
                
            # Use data from both, preferring B for header, A for fallback
            header_src = b_inv or a_inv
            lines = a_inv['lines'] if a_inv else []
            
            reference = header_src.get('reference') or header_src.get('reference_no') or ''
            invoice_type_code = reference.split('-')[0] if '-' in reference else 'CSI'
            payment_type = 'CREDIT' if reference.startswith('CRSI') else 'CASH'
            
            try:
                # Use a savepoint per invoice
                with self.conn.cursor() as cur:
                    cur.execute("SAVEPOINT invoice_sp")
                    
                    store_id = self.get_or_create_store(header_src.get('store'))
                    user_id = self.get_or_create_user(header_src.get('user'))
                    mrc_id = self.get_or_create_mrc(a_inv.get('mrc_code') if a_inv else None)
                    type_id = self.get_or_create_invoice_type(invoice_type_code)
                    
                    customer = header_src.get('customer') or header_src.get('client')
                    tin = a_inv.get('tin') if a_inv else None
                    patient_id = self.get_or_create_patient(customer, tin)
                    
                    visit_id = self.get_or_create_visit(patient_id, header_src.get('date', report_date))
                    
                    # Upsert Invoice
                    cur.execute("""
                        INSERT INTO invoice (
                            fs_no, reference_no, ref_note, invoice_type_id, payment_type,
                            visit_id, store_id, user_id, fiscal_device_id,
                            subtotal, tax_amount, total_amount, status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active'
                        ) ON CONFLICT (fs_no) DO UPDATE SET
                            reference_no = EXCLUDED.reference_no,
                            ref_note = EXCLUDED.ref_note,
                            invoice_type_id = EXCLUDED.invoice_type_id,
                            payment_type = EXCLUDED.payment_type,
                            subtotal = EXCLUDED.subtotal,
                            tax_amount = EXCLUDED.tax_amount,
                            total_amount = EXCLUDED.total_amount
                        RETURNING id;
                    """, (
                        fs_no, reference, header_src.get('ref_note'), type_id, payment_type,
                        visit_id, store_id, user_id, mrc_id,
                        header_src.get('subtotal', 0), header_src.get('tax', 0), header_src.get('total', 0)
                    ))
                    invoice_id = cur.fetchone()[0]
                    
                    # Delete existing lines for idempotency
                    cur.execute("DELETE FROM invoice_line WHERE invoice_id = %s", (invoice_id,))
                    
                    # Insert lines
                    for line in lines:
                        service_id = self.get_or_create_service(line['item_no'], line['description'], line['unit_price'])
                        
                        calc_subtotal = Decimal(line['qty']) * Decimal(line['unit_price'])
                        actual_subtotal = Decimal(line['subtotal'])
                        if abs(calc_subtotal - actual_subtotal) > Decimal('0.01'):
                            logger.warning(f"Subtotal mismatch for FS {fs_no} line {line['line_no']}: {calc_subtotal} vs {actual_subtotal}")
                        
                        cur.execute("""
                            INSERT INTO invoice_line (
                                invoice_id, service_id, line_no, quantity, 
                                unit_price, subtotal, tax_amount
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s
                            )
                        """, (
                            invoice_id, service_id, line['line_no'], line['qty'],
                            line['unit_price'], line['subtotal'], line['tax']
                        ))
                    
                    cur.execute("RELEASE SAVEPOINT invoice_sp")
                    
            except Exception as e:
                logger.error(f"Error processing invoice {fs_no}: {e}")
                self.conn.rollback() # Rollback to start or we must rollback to savepoint if we catch it inside
                # Let's properly rollback to savepoint if caught outside with block (not possible, so we do it here)
                with self.conn.cursor() as cur:
                    cur.execute("ROLLBACK TO SAVEPOINT invoice_sp")
                    self.log_issue(report_date, 'INVOICE_ERROR', fs_no, 'Success', str(e))

    def store_C(self, report_date, rows):
        with self.conn.cursor() as cur:
            for r in rows:
                if not r.get('sales_rep'):
                    continue
                cur.execute("""
                    INSERT INTO daily_payment_summary (
                        report_date, sales_rep, payment_type, subtotal, tax, total
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (report_date, sales_rep, payment_type) 
                    DO UPDATE SET subtotal = EXCLUDED.subtotal, tax = EXCLUDED.tax, total = EXCLUDED.total
                """, (
                    report_date, r['sales_rep'], r['payment_type'], 
                    r['subtotal'], r['tax'], r['total']
                ))

    def store_D(self, report_date, rows):
        with self.conn.cursor() as cur:
            for r in rows:
                if not r.get('item_id'):
                    continue
                cur.execute("""
                    INSERT INTO daily_item_summary (
                        report_date, item_id, description, qty, total
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (report_date, item_id) 
                    DO UPDATE SET qty = EXCLUDED.qty, total = EXCLUDED.total
                """, (
                    report_date, r['item_id'], r['description'], r['qty'], r['total']
                ))

    def commit(self):
        self.conn.commit()

