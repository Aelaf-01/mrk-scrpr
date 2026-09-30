import os
import datetime
from bs4 import BeautifulSoup
from database import insert_invoice_data

def parse_numeric(val):
    if not val:
        return 0.0
    val = val.replace(',', '').replace('-', '0').strip()
    try:
        return float(val)
    except:
        return 0.0

def a_extractor(html_content):
    print("Extracting Erca reports")
    soup = BeautifulSoup(html_content, "lxml")
    rows = soup.find_all('tr', class_='StyleReportDataTr')
    
    invoices = {}
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 14:
            continue
            
        customer = cols[0].text.strip()
        tin_no = cols[1].text.strip()
        desc = cols[2].text.strip()
        item_id = cols[3].text.strip() # e.g. 18s2
        
        # Extract base item_no and line_no from '18s2'
        item_no = item_id
        line_no = 1
        if 's' in item_id:
            parts = item_id.split('s')
            if len(parts) == 2:
                try:
                    item_no = int(parts[0])
                    line_no = int(parts[1])
                except ValueError:
                    pass
                
        qty = parse_numeric(cols[5].text)
        unit_price = parse_numeric(cols[6].text)
        subtotal_line = parse_numeric(cols[7].text)
        
        fs_no = cols[10].text.strip()
        trans_date = cols[11].text.strip()
        ref = cols[12].text.strip()
        mrc = cols[13].text.strip()
        
        if fs_no not in invoices:
            invoices[fs_no] = {
                'patient': {'full_name': customer, 'tin_no': tin_no, 'account_no': ''},
                'visit': {'visit_date': trans_date},
                'invoice': {
                    'fs_no': fs_no,
                    'reference_no': ref,
                    'transaction_date': trans_date,
                    'mrc_code': mrc,
                    'subtotal': 0.0 # Will sum up
                },
                'lines': []
            }
            
        invoices[fs_no]['lines'].append({
            'line_no': line_no,
            'item_no': item_no,
            'quantity': qty,
            'unit_price': unit_price,
            'subtotal': subtotal_line
        })
        invoices[fs_no]['invoice']['subtotal'] += subtotal_line
        
    return {"report_type": "erca", "data": list(invoices.values())}

def b_extractor(html_content):
    print("Extracting Sales report files")
    soup = BeautifulSoup(html_content, "lxml")
    rows = soup.find_all('tr', class_='StyleReportDataTr')
    
    invoices = []
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 11:
            continue
            
        ref_note = cols[0].text.strip()
        fs_no = cols[1].text.strip()
        trans_date = cols[2].text.strip()
        ref = cols[3].text.strip()
        customer = cols[4].text.strip()
        tin_no = cols[5].text.strip()
        store = cols[6].text.strip()
        user = cols[7].text.strip()
        subtotal = parse_numeric(cols[8].text)
        
        invoices.append({
            'patient': {'full_name': customer, 'tin_no': tin_no, 'account_no': ''},
            'visit': {'visit_date': trans_date},
            'invoice': {
                'fs_no': fs_no,
                'reference_no': ref,
                'ref_note': ref_note,
                'transaction_date': trans_date,
                'store_name': store,
                'username': user,
                'subtotal': subtotal
            },
            'lines': [] # No lines in this report
        })
        
    return {"report_type": "sales", "data": invoices}

def c_extractor(html_content):
    print("Extracting sales rep summary files")
    soup = BeautifulSoup(html_content, "lxml")
    rows = soup.find_all('tr', class_='StyleReportDataTr')
    
    data = []
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 7:
            continue
            
        trans_date = cols[0].text.strip()
        sales_rep = cols[1].text.strip()
        payment_type = cols[2].text.strip()
        subtotal = parse_numeric(cols[3].text)
        tax = parse_numeric(cols[4].text)
        total = parse_numeric(cols[6].text)
        
        data.append({
            'transaction_date': trans_date,
            'sales_rep': sales_rep,
            'payment_type': payment_type,
            'subtotal': subtotal,
            'tax': tax,
            'total': total
        })
        
    return {"report_type": "sales_rep", "data": data}

def d_extractor(html_content):
    print("Extracting sales summary by item sold files")
    soup = BeautifulSoup(html_content, "lxml")
    rows = soup.find_all('tr', class_='StyleReportDataTr')
    
    data = []
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 4:
            continue
            
        item_id = cols[0].text.strip()
        desc = cols[1].text.strip()
        qty = parse_numeric(cols[2].text)
        total = parse_numeric(cols[3].text)
        
        data.append({
            'item_id': item_id,
            'description': desc,
            'quantity': qty,
            'total': total
        })
        
    return {"report_type": "sales_summary_items", "data": data}

def get_extractor(filename):
    if "_a.html" in filename or "Erca" in filename:
        return a_extractor
    elif "_b.html" in filename or "Sales report" in filename:
        return b_extractor
    elif "_c.html" in filename or "Sales-Rep" in filename:
        return c_extractor
    elif "_d.html" in filename or "Item-sold" in filename:
        return d_extractor
    return None

def adapt_to_db(parsed_result):
    if not parsed_result or not parsed_result.get('data'):
        return
        
    data = parsed_result['data']
    report_type = parsed_result['report_type']
    print(f"Adapting parsed {report_type} data to DB. Found {len(data)} records.")
    
    if report_type in ['erca', 'sales']:
        for invoice_data in data:
            insert_invoice_data(invoice_data)
    else:
        print(f"Data insertion for {report_type} handles aggregations. Skipping base table inserts for this report type.")

def parse_htmls(base_dir, date_str, ip_folder):
    source_dir = os.path.join(base_dir, f"{date_str}html", ip_folder)
    
    if not os.path.exists(source_dir):
        print(f"Source directory {source_dir} does not exist.")
        return
        
    for filename in os.listdir(source_dir):
        if filename.endswith(".html"):
            file_path = os.path.join(source_dir, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()
                
            extractor_func = get_extractor(filename)
            if extractor_func:
                extracted_result = extractor_func(html_content)
                adapt_to_db(extracted_result)
            else:
                print(f"No extractor found for {filename}")

if __name__ == "__main__":
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join("htmls", f"{current_date}html")
    
    if os.path.exists(date_dir):
        for ip_folder in os.listdir(date_dir):
            print(f"Parsing files for client IP ending in {ip_folder}")
            parse_htmls("htmls", current_date, ip_folder)
    else:
        print(f"No htmls directory found for today ({date_dir}).")
