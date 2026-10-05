
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- =====================================================================
-- Senay Higher Clinic - billing / visit schema (PostgreSQL)
-- Derived from: ERCA Report 1, Sales Report, Sales by Sales Rep Summary,
--               Sales Summary by Item Sold  (report date 2026-09-29)
--
-- Key findings from the data that shaped the design
--  * "Item ID" (e.g. 18s2) = <catalog item no. 18><'s'><line no. 2 on the invoice>.
--    It is NOT a catalog key, so it is split into service_id + line_no.
--  * One invoice = one FS number = one reference (CSI-... / CRSI-...) = one patient.
--  * The same patient appears on several invoices/day -> visit table groups them.
--  * Physician NAMES are not in the source. Consultations only name a specialty
--    (GP / Internist / Endocrinologist), so physician.full_name is nullable and
--    services link to a specialty. Fill physician names when available.
--  * Only DATE is present (no time) -> transaction_time is nullable.
--  * Report 3 (daily by cash/credit) and Report 4 (by item) are aggregates,
--    so they are provided as VIEWS, not tables.
-- =====================================================================

-- ---------- Lookup / reference tables --------------------------------
CREATE TABLE store (
    store_id     SERIAL PRIMARY KEY,
    store_name   VARCHAR(30) NOT NULL UNIQUE          -- GIT, STORE1, STORE2, STORE3
);

CREATE TABLE station (
    station_id   SMALLINT PRIMARY KEY,                 -- 0 = N/A, 1 = STATION 1
    station_name VARCHAR(30) NOT NULL UNIQUE
);

CREATE TABLE app_user (                                -- cashiers / billing operators
    user_id      SERIAL PRIMARY KEY,
    username     VARCHAR(50) NOT NULL UNIQUE,          -- meaza, Bereket, ...
    display_name VARCHAR(100)
);

CREATE TABLE employee (                                -- "Sales Rep" in report 3
    employee_id  SERIAL PRIMARY KEY,
    full_name    VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE fiscal_device (                           -- "MRC" column (ERCA machine reg. code)
    mrc_code     VARCHAR(20) PRIMARY KEY               -- e.g. BEN0031670
);

CREATE TABLE payment_type (
    payment_type VARCHAR(10) PRIMARY KEY CHECK (payment_type IN ('CASH','CREDIT'))
);

CREATE TABLE invoice_type (                            -- prefix of the Reference number
    invoice_type_code VARCHAR(6) PRIMARY KEY,          -- CSI, CRSI
    description       VARCHAR(80)
);

-- ---------- Clinical staff -------------------------------------------
CREATE TABLE specialty (
    specialty_id SERIAL PRIMARY KEY,
    name         VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE physician (
    physician_id SERIAL PRIMARY KEY,
    full_name    VARCHAR(120),                         -- not present in source data
    specialty_id INT NOT NULL REFERENCES specialty(specialty_id),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------- Service catalogue ----------------------------------------
CREATE TABLE service_category (
    category_id  SERIAL PRIMARY KEY,
    name         VARCHAR(40) NOT NULL UNIQUE           -- Consultation, Laboratory, Ultrasound, ...
);

CREATE TABLE service (
    service_id     SERIAL PRIMARY KEY,
    item_no        INT NOT NULL UNIQUE,                -- number before the 's' in Item ID
    description    VARCHAR(120) NOT NULL,
    category_id    INT NOT NULL REFERENCES service_category(category_id),
    specialty_id   INT REFERENCES specialty(specialty_id),   -- set for consultations
    default_price  NUMERIC(12,2) NOT NULL CHECK (default_price >= 0),
    base_sku       VARCHAR(10) NOT NULL DEFAULT 'SQM'
);

-- ---------- Patients and visits --------------------------------------
CREATE TABLE patient (
    patient_id   BIGSERIAL PRIMARY KEY,
    full_name    VARCHAR(150) NOT NULL,                -- "Customer" (names are not unique -> surrogate key)
    tin_no       VARCHAR(20),                          -- blank in source
    account_no   VARCHAR(30)                           -- "Customer Acc#" filter in Sales Report
);
CREATE INDEX ix_patient_name ON patient (LOWER(full_name));

CREATE TABLE visit (                                   -- one patient, one day (groups several invoices)
    visit_id     BIGSERIAL PRIMARY KEY,
    patient_id   BIGINT NOT NULL REFERENCES patient(patient_id),
    visit_date   DATE NOT NULL,
    visit_time   TIME,
    physician_id INT REFERENCES physician(physician_id),
    UNIQUE (patient_id, visit_date)
);

-- ---------- Invoices --------------------------------------------------
CREATE TABLE invoice (
    invoice_id        BIGSERIAL PRIMARY KEY,
    fs_no             VARCHAR(12) NOT NULL UNIQUE,     -- 00076188
    reference_no      VARCHAR(30) NOT NULL UNIQUE,     -- CSI-ST1-01-0068158 / CRSI-ST1-01-0008214
    invoice_type_code VARCHAR(6)  NOT NULL REFERENCES invoice_type(invoice_type_code),
    ref_note          VARCHAR(20),                     -- PAY-61667
    visit_id          BIGINT NOT NULL REFERENCES visit(visit_id),
    patient_id        BIGINT NOT NULL REFERENCES patient(patient_id),
    transaction_date  DATE NOT NULL,
    transaction_time  TIME,
    store_id          INT NOT NULL REFERENCES store(store_id),
    station_id        SMALLINT REFERENCES station(station_id),
    user_id           INT NOT NULL REFERENCES app_user(user_id),
    employee_id       INT REFERENCES employee(employee_id),      -- sales rep (blank in data)
    payment_type      VARCHAR(10) NOT NULL REFERENCES payment_type(payment_type),
    mrc_code          VARCHAR(20) REFERENCES fiscal_device(mrc_code),
    is_void           BOOLEAN NOT NULL DEFAULT FALSE,
    subtotal          NUMERIC(14,2) NOT NULL DEFAULT 0,
    tax_amt           NUMERIC(14,2) NOT NULL DEFAULT 0,
    withholding       NUMERIC(14,2) NOT NULL DEFAULT 0,
    total             NUMERIC(14,2) GENERATED ALWAYS AS (subtotal + tax_amt) STORED
);
CREATE INDEX ix_invoice_date    ON invoice (transaction_date);
CREATE INDEX ix_invoice_patient ON invoice (patient_id);

CREATE TABLE invoice_line (
    line_id      BIGSERIAL PRIMARY KEY,
    invoice_id   BIGINT NOT NULL REFERENCES invoice(invoice_id) ON DELETE CASCADE,
    line_no      SMALLINT NOT NULL CHECK (line_no > 0),        -- the number after 's' in Item ID
    service_id   INT NOT NULL REFERENCES service(service_id),
    physician_id INT REFERENCES physician(physician_id),       -- performing / consulting physician
    quantity     NUMERIC(10,2) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price   NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    subtotal     NUMERIC(14,2) NOT NULL,
    tax_amt      NUMERIC(14,2) NOT NULL DEFAULT 0,
    withholding  NUMERIC(14,2) NOT NULL DEFAULT 0,
    UNIQUE (invoice_id, line_no),
    CONSTRAINT ck_line_subtotal CHECK (subtotal = quantity * unit_price)
);
CREATE INDEX ix_line_service ON invoice_line (service_id);

-- Rebuild the report-style Item ID (e.g. 18s2) when needed
CREATE VIEW v_invoice_line_detail AS
SELECT  il.line_id, i.invoice_id, i.fs_no, i.reference_no, i.transaction_date,
        p.full_name AS patient_name,
        s.item_no || 's' || il.line_no AS item_id,
        s.description, sc.name AS category,
        ph.full_name AS physician_name, sp.name AS physician_specialty,
        il.quantity, il.unit_price, il.subtotal, il.tax_amt, il.withholding,
        i.mrc_code, i.is_void
FROM invoice_line il
JOIN invoice i          ON i.invoice_id = il.invoice_id
JOIN patient p          ON p.patient_id = i.patient_id
JOIN service s          ON s.service_id = il.service_id
JOIN service_category sc ON sc.category_id = s.category_id
LEFT JOIN physician ph  ON ph.physician_id = il.physician_id
LEFT JOIN specialty sp  ON sp.specialty_id = COALESCE(ph.specialty_id, s.specialty_id);

-- ---------- Views reproducing the source reports ----------------------
-- Sales Report (one row per invoice)
CREATE VIEW v_sales_report AS
SELECT i.ref_note, i.fs_no, i.transaction_date, i.reference_no, p.full_name AS customer,
       st.store_name, u.username AS "user", i.subtotal, i.tax_amt AS tax, i.total
FROM invoice i
JOIN patient p ON p.patient_id = i.patient_id
JOIN store st  ON st.store_id  = i.store_id
JOIN app_user u ON u.user_id   = i.user_id
WHERE NOT i.is_void;

-- Sales by Sales Rep Summary (daily, by cash/credit)
CREATE VIEW v_daily_sales_by_payment AS
SELECT i.transaction_date, e.full_name AS sales_rep, i.payment_type,
       SUM(i.subtotal) AS subtotal, SUM(i.tax_amt) AS tax, SUM(i.total) AS total
FROM invoice i LEFT JOIN employee e ON e.employee_id = i.employee_id
WHERE NOT i.is_void
GROUP BY i.transaction_date, e.full_name, i.payment_type;

-- Sales Summary by Item Sold (grouped by service; report grouped by full item id)
CREATE VIEW v_item_sales_summary AS
SELECT i.transaction_date, s.item_no, s.description,
       SUM(il.quantity) AS quantity, SUM(il.subtotal) AS total
FROM invoice_line il
JOIN invoice i ON i.invoice_id = il.invoice_id
JOIN service s ON s.service_id = il.service_id
WHERE NOT i.is_void
GROUP BY i.transaction_date, s.item_no, s.description;

-- Revenue per specialty / physician (uses consult services when no physician is named)
CREATE VIEW v_revenue_by_specialty AS
SELECT i.transaction_date, COALESCE(sp.name,'(non-consult)') AS specialty,
       COUNT(DISTINCT i.invoice_id) AS invoices, SUM(il.subtotal) AS revenue
FROM invoice_line il
JOIN invoice i ON i.invoice_id = il.invoice_id
JOIN service s ON s.service_id = il.service_id
LEFT JOIN physician ph ON ph.physician_id = il.physician_id
LEFT JOIN specialty sp ON sp.specialty_id = COALESCE(ph.specialty_id, s.specialty_id)
WHERE NOT i.is_void
GROUP BY i.transaction_date, COALESCE(sp.name,'(non-consult)');


CREATE TABLE IF NOT EXISTS daily_payment_summary (
    report_date DATE NOT NULL,
    sales_rep VARCHAR(255) NOT NULL,
    payment_type VARCHAR(50) NOT NULL,
    subtotal DECIMAL(15,2),
    tax DECIMAL(15,2),
    total DECIMAL(15,2),
    PRIMARY KEY (report_date, sales_rep, payment_type)
);

CREATE TABLE IF NOT EXISTS daily_item_summary (
    report_date DATE NOT NULL,
    item_id INT NOT NULL,
    description TEXT,
    qty DECIMAL(15,2),
    total DECIMAL(15,2),
    PRIMARY KEY (report_date, item_id)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    report_type VARCHAR(10) NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    rows_count INT,
    status VARCHAR(50),
    error TEXT,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (report_date, report_type, file_sha256)
);

CREATE TABLE IF NOT EXISTS reconciliation_issue (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    kind VARCHAR(50) NOT NULL,
    ref VARCHAR(255),
    expected TEXT,
    actual TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
