import os
import sys
import pytest
from decimal import Decimal
from bs4 import BeautifulSoup
import tempfile
import json
import shutil

# Add root directory to python path for config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from host_side.parse_html import parse_number, parse_item_id, extract_A, extract_B, extract_C, extract_D, read_html
from host_side.database import Database

def test_parse_number():
    assert parse_number("1,234.56") == Decimal("1234.56")
    assert parse_number("-5.00") == Decimal("-5.00")
    assert parse_number("-") == Decimal("0.0")
    assert parse_number("&nbsp;") == Decimal("0.0")
    assert parse_number("") == Decimal("0.0")

def test_parse_item_id():
    assert parse_item_id("18s2") == (18, 2)
    assert parse_item_id("68s10") == (68, 10)
    assert parse_item_id("42") == (42, 1)

def test_extractor_counts():
    # Use fixtures
    base_dir = os.path.dirname(os.path.abspath(__file__))
    a_path = os.path.join(base_dir, 'Erca-report_files', 'home.html')
    b_path = os.path.join(base_dir, 'Sales report_files', 'home.html')
    c_path = os.path.join(base_dir, 'Sales-Rep-Summary_files', 'home.html')
    d_path = os.path.join(base_dir, 'Sales-Summary-by -Item-sold_files', 'home.html')

    # A
    soup_a = read_html(a_path)
    data_a = extract_A(soup_a, "2026-09-29_a.html")
    lines_count = sum(len(inv['lines']) for inv in data_a['invoices'])
    assert lines_count == 244  # based on spec

    # B
    soup_b = read_html(b_path)
    data_b = extract_B(soup_b, "2026-09-29_b.html")
    assert len(data_b['invoices']) == 64
    
    # D
    soup_d = read_html(d_path)
    data_d = extract_D(soup_d, "2026-09-29_d.html")
    assert len(data_d['rows']) == 127
    total_qty = sum(r['qty'] for r in data_d['rows'])
    assert total_qty == Decimal('242')

def test_reconciliation_anomaly():
    # A total is 111,925 while B is 111,325 (600 diff)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    a_path = os.path.join(base_dir, 'Erca-report_files', 'home.html')
    b_path = os.path.join(base_dir, 'Sales report_files', 'home.html')

    soup_a = read_html(a_path)
    data_a = extract_A(soup_a, "2026-09-29_a.html")
    
    soup_b = read_html(b_path)
    data_b = extract_B(soup_b, "2026-09-29_b.html")

    sum_a = sum(sum(l['subtotal'] for l in inv['lines']) for inv in data_a['invoices'])
    sum_b = sum(inv['subtotal'] for inv in data_b['invoices'])
    
    assert sum_a == Decimal("111925.0")
    assert sum_b == Decimal("111325.0")
    assert sum_a - sum_b == Decimal("600.0")

@pytest.fixture
def test_db():
    # Attempt to connect; skip DB tests if no DB is available
    import psycopg2
    import config
    try:
        conn = psycopg2.connect(
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASS,
            host=config.DB_HOST,
            port=config.DB_PORT
        )
        conn.close()
    except psycopg2.OperationalError:
        pytest.skip("Test database not available")
        return None

    db = Database()
    
    # Ensure fresh state
    with db.conn.cursor() as cur:
        cur.execute("TRUNCATE invoice CASCADE;")
        cur.execute("TRUNCATE reconciliation_issue CASCADE;")
        cur.execute("TRUNCATE invoice_line CASCADE;")
        cur.execute("TRUNCATE service CASCADE;")
    db.commit()
    
    yield db
    
    # Teardown
    with db.conn.cursor() as cur:
        cur.execute("TRUNCATE invoice CASCADE;")
        cur.execute("TRUNCATE reconciliation_issue CASCADE;")
        cur.execute("TRUNCATE invoice_line CASCADE;")
        cur.execute("TRUNCATE service CASCADE;")
    db.commit()
    db.close()

def test_db_idempotency_and_logic(test_db):
    if not test_db:
        return
        
    date_str = "2026-09-29"
    
    # Mock data
    a_invoices = [{
        'fs_no': '001',
        'reference_no': 'CRSI-01',
        'transaction_date': date_str,
        'mrc_code': 'MRC123',
        'customer': 'Test Cust',
        'tin': '1234',
        'lines': [{
            'line_no': 1,
            'item_no': 9999, # Unknown item
            'description': 'Unknown Service Test',
            'qty': Decimal('2'),
            'unit_price': Decimal('50.0'),
            'subtotal': Decimal('100.0'),
            'tax': Decimal('0'),
            'withholding': Decimal('0')
        }]
    }]
    
    b_invoices = [{
        'ref_note': 'NOTE-01',
        'fs_no': '001',
        'date': date_str,
        'reference': 'CRSI-01',
        'customer': 'Test Cust',
        'client': 'Test Cust',
        'store': 'STORE1',
        'user': 'admin',
        'subtotal': Decimal('100.0'),
        'tax': Decimal('0'),
        'total': Decimal('100.0')
    }]
    
    # Run first ingest
    test_db.merge_day(date_str, a_invoices, b_invoices)
    test_db.commit()
    
    with test_db.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM invoice")
        assert cur.fetchone()[0] == 1
        
        cur.execute("SELECT count(*) FROM invoice_line")
        assert cur.fetchone()[0] == 1
        
        # Check CRSI -> CREDIT
        cur.execute("SELECT payment_type FROM invoice WHERE fs_no = '001'")
        assert cur.fetchone()[0] == 'CREDIT'
        
        # Check unknown item created
        cur.execute("SELECT name FROM service WHERE item_no = 9999")
        assert cur.fetchone()[0] == 'Unknown Service Test'
        
    # Double ingest (idempotency)
    test_db.merge_day(date_str, a_invoices, b_invoices)
    test_db.commit()
    
    with test_db.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM invoice")
        assert cur.fetchone()[0] == 1
        
        cur.execute("SELECT count(*) FROM invoice_line")
        assert cur.fetchone()[0] == 1
