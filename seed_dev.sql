-- =====================================================================
-- SEED DATA (lookups taken from the reports)
-- =====================================================================
INSERT INTO store(store_name) VALUES ('GIT'),('STORE1'),('STORE2'),('STORE3');
INSERT INTO station VALUES (0,'N/A'),(1,'STATION 1');
INSERT INTO payment_type VALUES ('CASH'),('CREDIT');
INSERT INTO invoice_type VALUES ('CSI','Cash/standard sales invoice (assumed)'),
                                ('CRSI','Credit sales invoice (assumed)');
INSERT INTO fiscal_device VALUES ('BEN0031670');
INSERT INTO app_user(username) VALUES ('meaza'),('Bereket'),('emush'),('adanu'),('meser'),
  ('Birtukan'),('Sara'),('Aster'),('Netsanet'),('Beza'),('yemisrach'),('Misrak'),('Hewan');
INSERT INTO employee(full_name) VALUES ('EMPLOYEE 01'),('temsgen gebru'),('beminet tilahun'),('YEWUBINESH ANIKERSA');

INSERT INTO specialty(name) VALUES ('General Practitioner'),('Internist'),
  ('Endocrinologist'),('Internist / Endocrinologist');
INSERT INTO physician(full_name, specialty_id)      -- placeholders: replace with real names
SELECT NULL, specialty_id FROM specialty;

INSERT INTO service_category(name) VALUES ('Consultation'),('Laboratory'),('Ultrasound'),
  ('Radiology'),('Cardiology'),('Procedure');

-- item_no, description, category, specialty (consults only), price
WITH src(item_no, description, cat, spec, price) AS (VALUES
 (1,'Consultancy of GP Card','Consultation','General Practitioner',600),
 (2,'Consultancy of Internist Card','Consultation','Internist',800),
 (9,'Consultancy of Internist, Endocrinologist','Consultation','Internist / Endocrinologist',950),
 (425,'Consultancy of Endocronlogist','Consultation','Endocrinologist',950),
 (18,'CBC','Laboratory',NULL,450),(40,'ESR','Laboratory',NULL,150),(41,'Blood Film','Laboratory',NULL,200),
 (47,'CRP Quantitative','Laboratory',NULL,750),(53,'H.pylori Ab','Laboratory',NULL,500),
 (60,'FBS','Laboratory',NULL,100),(61,'RBS','Laboratory',NULL,100),(62,'HbA1c','Laboratory',NULL,950),
 (64,'SGOT','Laboratory',NULL,250),(65,'SGPT','Laboratory',NULL,250),(66,'ALP','Laboratory',NULL,250),
 (67,'Bilirubin (T)','Laboratory',NULL,250),(68,'Bilirubin (D)','Laboratory',NULL,250),
 (72,'BUN','Laboratory',NULL,250),(73,'Creatinine','Laboratory',NULL,250),(74,'Uric Acid','Laboratory',NULL,250),
 (76,'Triglyceride (TG)','Laboratory',NULL,250),(77,'Cholesterol','Laboratory',NULL,250),
 (78,'HDL','Laboratory',NULL,500),(79,'LDL','Laboratory',NULL,500),(87,'Urinalysis','Laboratory',NULL,200),
 (104,'Micro Albumin','Laboratory',NULL,300),(118,'PSA','Laboratory',NULL,900),(124,'TSH','Laboratory',NULL,1000),
 (125,'Free T3','Laboratory',NULL,900),(126,'Free T4','Laboratory',NULL,900),
 (127,'Electrolyte Panel','Laboratory',NULL,1500),(387,'25-OH-Vitamin D','Laboratory',NULL,2000),
 (316,'2 hour post prandial','Laboratory',NULL,200),
 (141,'Abdomen Ultrasound','Ultrasound',NULL,700),(142,'Abdominal + Pelvic Ultrasound','Ultrasound',NULL,800),
 (143,'Chest Ultrasound','Ultrasound',NULL,800),(159,'Thyroid Ultrasound','Ultrasound',NULL,800),
 (168,'Breast right','Ultrasound',NULL,850),(170,'Knee left Ultrasound','Ultrasound',NULL,800),
 (171,'Knee right Ultrasound','Ultrasound',NULL,800),
 (205,'Lumbar spine X-ray','Radiology',NULL,1000),
 (379,'ECG','Cardiology',NULL,1000),
 (317,'Blood Pressure Measurement (BP)','Procedure',NULL,50),
 (410,'IM injection','Procedure',NULL,75),(411,'IV injection','Procedure',NULL,100))
INSERT INTO service(item_no, description, category_id, specialty_id, default_price)
SELECT s.item_no, s.description, c.category_id, sp.specialty_id, s.price
FROM src s
JOIN service_category c ON c.name = s.cat
LEFT JOIN specialty sp ON sp.name = s.spec;

-- =====================================================================
-- WORKED EXAMPLE: invoice 00076196 (BEHASEN ABDI ISMAEL, 5,900.00)
-- =====================================================================
INSERT INTO patient(full_name) VALUES ('BEHASEN ABDI ISMAEL');

INSERT INTO visit(patient_id, visit_date)
SELECT patient_id, DATE '2026-09-29' FROM patient WHERE full_name='BEHASEN ABDI ISMAEL';

INSERT INTO invoice(fs_no, reference_no, invoice_type_code, ref_note, visit_id, patient_id,
                    transaction_date, store_id, station_id, user_id, payment_type,
                    mrc_code, subtotal)
SELECT '00076196','CSI-ST1-01-0068165','CSI','PAY-61675', v.visit_id, v.patient_id,
       DATE '2026-09-29',
       (SELECT store_id FROM store WHERE store_name='STORE1'), 1,
       (SELECT user_id FROM app_user WHERE username='meaza'),
       'CASH','BEN0031670', 5900
FROM visit v JOIN patient p USING (patient_id) WHERE p.full_name='BEHASEN ABDI ISMAEL';

INSERT INTO invoice_line(invoice_id, line_no, service_id, quantity, unit_price, subtotal)
SELECT i.invoice_id, d.line_no, s.service_id, 1, s.default_price, s.default_price
FROM invoice i
JOIN (VALUES (1,425),(2,18),(3,87),(4,60),(5,62),(6,64),(7,65),(8,66),(9,67),
             (10,68),(11,72),(12,73),(13,76),(14,77),(15,78),(16,79)) AS d(line_no,item_no) ON TRUE
JOIN service s ON s.item_no = d.item_no
WHERE i.fs_no = '00076196';