import psycopg2

# Database connection settings
DB_CONFIG = {
    'dbname': 'clinic_db',
    'user': 'postgres',
    'password': 'password',
    'host': 'localhost',
    'port': '5432'
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def insert_invoice_data(parsed_data):
    """
    Inserts structured parsed data into the PostgreSQL database.
    Expected parsed_data format:
    {
        'patient': {'full_name': '...', 'tin_no': '...', 'account_no': '...'},
        'visit': {'visit_date': '...'},
        'invoice': {
            'fs_no': '...', 'reference_no': '...', 'invoice_type_code': '...',
            'ref_note': '...', 'transaction_date': '...', 'store_name': '...',
            'username': '...', 'payment_type': '...', 'mrc_code': '...',
            'subtotal': ...
        },
        'lines': [
            {'line_no': 1, 'item_no': 18, 'quantity': 1, 'unit_price': 450, 'subtotal': 450},
            # ...
        ]
    }
    """
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # 1. Insert or get Patient
        cur.execute("SELECT patient_id FROM patient WHERE full_name = %s", (parsed_data['patient']['full_name'],))
        patient_row = cur.fetchone()
        if patient_row:
            patient_id = patient_row[0]
        else:
            cur.execute(
                "INSERT INTO patient (full_name, tin_no, account_no) VALUES (%s, %s, %s) RETURNING patient_id",
                (parsed_data['patient']['full_name'], parsed_data['patient'].get('tin_no'), parsed_data['patient'].get('account_no'))
            )
            patient_id = cur.fetchone()[0]

        # 2. Insert or get Visit
        cur.execute(
            "SELECT visit_id FROM visit WHERE patient_id = %s AND visit_date = %s",
            (patient_id, parsed_data['visit']['visit_date'])
        )
        visit_row = cur.fetchone()
        if visit_row:
            visit_id = visit_row[0]
        else:
            cur.execute(
                "INSERT INTO visit (patient_id, visit_date) VALUES (%s, %s) RETURNING visit_id",
                (patient_id, parsed_data['visit']['visit_date'])
            )
            visit_id = cur.fetchone()[0]

        # 3. Lookup lookup tables (store, app_user)
        cur.execute("SELECT store_id FROM store WHERE store_name = %s", (parsed_data['invoice'].get('store_name', 'STORE1'),))
        store_id = cur.fetchone()
        store_id = store_id[0] if store_id else 1

        cur.execute("SELECT user_id FROM app_user WHERE username = %s", (parsed_data['invoice'].get('username', 'meaza'),))
        user_id = cur.fetchone()
        user_id = user_id[0] if user_id else 1

        # 4. Insert Invoice
        cur.execute(
            """
            INSERT INTO invoice (
                fs_no, reference_no, invoice_type_code, ref_note, visit_id, patient_id,
                transaction_date, store_id, station_id, user_id, payment_type, mrc_code, subtotal
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING invoice_id
            """,
            (
                parsed_data['invoice']['fs_no'],
                parsed_data['invoice']['reference_no'],
                parsed_data['invoice'].get('invoice_type_code', 'CSI'),
                parsed_data['invoice'].get('ref_note'),
                visit_id,
                patient_id,
                parsed_data['invoice']['transaction_date'],
                store_id,
                1, # station_id default
                user_id,
                parsed_data['invoice'].get('payment_type', 'CASH'),
                parsed_data['invoice'].get('mrc_code'),
                parsed_data['invoice']['subtotal']
            )
        )
        invoice_id = cur.fetchone()[0]

        # 5. Insert Invoice Lines
        for line in parsed_data.get('lines', []):
            cur.execute("SELECT service_id FROM service WHERE item_no = %s", (line['item_no'],))
            service_row = cur.fetchone()
            if not service_row:
                print(f"Warning: Service item_no {line['item_no']} not found. Skipping line.")
                continue
            service_id = service_row[0]

            cur.execute(
                """
                INSERT INTO invoice_line (
                    invoice_id, line_no, service_id, quantity, unit_price, subtotal
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    invoice_id,
                    line['line_no'],
                    service_id,
                    line.get('quantity', 1),
                    line['unit_price'],
                    line['subtotal']
                )
            )

        conn.commit()
        print(f"Successfully inserted invoice {parsed_data['invoice']['fs_no']} into database.")

    except Exception as e:
        conn.rollback()
        print(f"Database insertion failed: {e}")
    finally:
        cur.close()
        conn.close()
