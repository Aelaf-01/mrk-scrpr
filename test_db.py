import sys
sys.path.append('host_side')
from parse_html import a_extractor
from database import insert_invoice_data
import json

def test():
    content = open('Erca-report_files/home.html', 'r', encoding='utf-8', errors='ignore').read()
    res = a_extractor(content)
    first_invoice = res['data'][0]
    print(f"Total invoices parsed: {len(res['data'])}")
    print(f"Attempting to insert invoice {first_invoice['invoice']['fs_no']} into database...")
    insert_invoice_data(first_invoice)

if __name__ == '__main__':
    test()
