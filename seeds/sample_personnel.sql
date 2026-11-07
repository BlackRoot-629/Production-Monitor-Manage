-- DEMO DATA ONLY. These names and personnel codes are fictitious.
-- Apply migrations/003_employee_personnel_units.sql first.
BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM generate_series(1, 6) AS expected(id)
        LEFT JOIN lines ON lines.id = expected.id
        WHERE lines.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Production lines 1 through 6 must exist before loading sample personnel';
    END IF;
END $$;

-- Add the 19 known work stations on every production line.
INSERT INTO stations (station_name, line_id, is_active)
SELECT station.station_name, line_id, 1
FROM generate_series(1, 6) AS lines(line_id)
CROSS JOIN (
    VALUES
        ('S'), ('L'), ('A1'), ('A2'), ('A3'), ('A4'), ('A5'), ('A6'),
        ('A7'), ('A8'), ('A9'), ('T1'), ('T2'), ('B'),
        ('P1'), ('P2'), ('P3'), ('P4'), ('P5')
) AS station(station_name)
ON CONFLICT (line_id, station_name) DO NOTHING;

INSERT INTO employees (personnel_code, full_name, line_id, unit, position, is_active)
SELECT
    format('DEMO-L%s-%s', lpad(line_id::text, 2, '0'), lpad(person_no::text, 2, '0')),
    format('Line %s Employee %s', line_id, lpad(person_no::text, 2, '0')),
    line_id,
    NULL,
    CASE person_no
        WHEN 1 THEN 'SUPERVISOR'
        WHEN 2 THEN 'LOADING'
        ELSE 'STAFF'
    END,
    1
FROM generate_series(1, 6) AS lines(line_id)
CROSS JOIN generate_series(1, 19) AS people(person_no)
ON CONFLICT (personnel_code) DO NOTHING;

INSERT INTO employees (personnel_code, full_name, line_id, unit, position, is_active)
SELECT
    format('DEMO-ADM-%s', lpad(person_no::text, 2, '0')),
    format('Administration Employee %s', lpad(person_no::text, 2, '0')),
    NULL,
    'ADMINISTRATION',
    'STAFF',
    1
FROM generate_series(1, 6) AS people(person_no)
ON CONFLICT (personnel_code) DO NOTHING;

INSERT INTO employees (personnel_code, full_name, line_id, unit, position, is_active)
SELECT
    format('DEMO-SUP-%s', lpad(person_no::text, 2, '0')),
    format('Support Employee %s', lpad(person_no::text, 2, '0')),
    NULL,
    'SUPPORT',
    CASE person_no WHEN 1 THEN 'SUPERVISOR' ELSE 'STAFF' END,
    1
FROM generate_series(1, 5) AS people(person_no)
ON CONFLICT (personnel_code) DO NOTHING;

COMMIT;
