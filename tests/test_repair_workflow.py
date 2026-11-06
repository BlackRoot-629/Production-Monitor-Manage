import ast
import unittest
from pathlib import Path

from models import Assembly, AssemblyWorkflowHistory, Line
from services import validate_repair_transition

ROOT = Path(__file__).resolve().parents[1]


class RepairWorkflowLogicTests(unittest.TestCase):
    def test_happy_path_transitions(self):
        path = [
            (None, "REPAIR_QUEUE"),
            ("REPAIR_QUEUE", "IN_REPAIR"),
            ("IN_REPAIR", "QC_QUEUE"),
            ("QC_QUEUE", "EXIT_QUEUE"),
            ("EXIT_QUEUE", "CLOSED"),
        ]
        for old, new in path:
            with self.subTest(old=old, new=new):
                validate_repair_transition(old, new)

    def test_qc_rejection_returns_to_repair_queue(self):
        validate_repair_transition("QC_QUEUE", "REPAIR_QUEUE")

    def test_exit_queue_can_be_reopened_for_repair(self):
        validate_repair_transition("EXIT_QUEUE", "REPAIR_QUEUE")

    def test_invalid_skips_and_final_station_bypass_are_rejected(self):
        for old, new in [
            ("REPAIR_QUEUE", "QC_QUEUE"),
            ("IN_REPAIR", "EXIT_QUEUE"),
            ("QC_QUEUE", "CLOSED"),
            ("REPAIR_QUEUE", "CLOSED"),
        ]:
            with self.subTest(old=old, new=new):
                with self.assertRaises(ValueError):
                    validate_repair_transition(old, new)

    def test_existing_assembly_is_extended_and_audited(self):
        fields = set(Assembly.__table__.columns.keys())
        self.assertTrue({
            "repair_stage", "origin_line_id", "assigned_technician",
            "qc_note", "qc_return_count", "workflow_created_at",
            "closed_at"
        }.issubset(fields))
        self.assertEqual(AssemblyWorkflowHistory.__tablename__, "assembly_workflow_history")
        self.assertTrue({"tea_time", "lunch_time"}.issubset(set(Line.__table__.columns.keys())))
        indexes = {index.name for index in Assembly.__table__.indexes}
        self.assertIn("uq_assemblies_open_repair_serial", indexes)

    def test_migration_is_additive_and_backfills_legacy_repairs(self):
        migration = (ROOT / "migrations/001_repair_workflow.sql").read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS repair_stage", migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS origin_line_id", migration)
        self.assertIn("SET repair_stage = 'REPAIR_QUEUE'", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS assembly_workflow_history", migration)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS uq_assemblies_open_repair_serial", migration)
        self.assertIn("Resolve duplicate assemblies before retrying", migration)
        self.assertIn("BEGIN;", migration)
        self.assertIn("COMMIT;", migration)
        break_times_migration = (ROOT / "migrations/002_line_break_times.sql").read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS tea_time TIME", break_times_migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS lunch_time TIME", break_times_migration)

    def test_backend_parses_and_has_workflow_routes(self):
        source = (ROOT / "app.py").read_text()
        ast.parse(source)
        for route in (
            "/api/repair/start", "/api/repair/complete",
            "/api/repair/qc-review", "/api/repair/monitor",
            "/api/repair/monitor/overview", "/api/repair/monitor/stream",
            "/api/admin/repair-dashboard", "/repair/monitor",
            "/api/supervisor/break-times/{line_id}",
            "/api/repair/history/{line_id}/{serial_number}"
        ):
            self.assertIn(route, source)
        monitor = (ROOT / "templates/repair_monitor.html").read_text()
        for label in ("Unrepaired", "In Repair", "QC Queue", "Exit Queue", "Overall Total"):
            self.assertIn(label, monitor)
        self.assertIn("new EventSource('/api/repair/monitor/stream')", monitor)
        dashboard = (ROOT / "templates/dashboard.html").read_text()
        self.assertIn('id="repairTabPanel"', dashboard)
        self.assertIn("row.returned_to_line_times", dashboard)
        self.assertIn('"Not found"', dashboard)
        self.assertIn('new persianDate(localDate.getTime()).toCalendar("persian")', dashboard)
        self.assertIn('personnelShowAllLeaves ? filteredLeaves : filteredLeaves.slice(0, 5)', dashboard)
        self.assertIn('togglePersonnelShowAllLeaves()', dashboard)
        self.assertIn('id="personnelEmployeeSearch"', dashboard)
        self.assertIn('id="personnelLeaveSearch"', dashboard)
        self.assertIn('id="repairLineFilter"', dashboard)
        self.assertIn('params.set("line_id", lineFilter)', dashboard)
        login_page = (ROOT / "templates/login.html").read_text()
        self.assertIn('<html lang="en" dir="ltr">', login_page)
        self.assertIn('addEventListener("submit"', login_page)
        self.assertIn('if (event.key === "Enter")', login_page)
        user_admin_page = (ROOT / "templates/admin_users.html").read_text()
        self.assertIn('lineId = rawLineId ? Number(rawLineId) : null', user_admin_page)
        self.assertIn('Array.isArray(result.detail)', user_admin_page)
        self.assertIn('detail || result.error', user_admin_page)
        self.assertIn('id="teaTime"', (ROOT / "templates/supervisor.html").read_text())
        for name in ("templates/monitor.html", "templates/assembly_monitor.html"):
            monitor_page = (ROOT / name).read_text()
            self.assertIn("isInBreakWindow(lunchTime, 45)", monitor_page)
            self.assertIn("isInBreakWindow(teaTime, 15)", monitor_page)
            self.assertIn("updateBreakAlert(data.tea_time, data.lunch_time)", monitor_page)
            self.assertNotIn('id="breakTimes"', monitor_page)
        self.assertIn("formatPersonnelDateWithWeekday(l.start_date)", dashboard)
        self.assertIn('assembly.origin_line_id != data.line_id', source)
        self.assertIn('assembly.repair_stage == "EXIT_QUEUE"', source)
        self.assertIn('reopen_after_qc = previous_stage == "EXIT_QUEUE"', source)
        self.assertNotIn('Assembly operator credentials are required', source)
        assembly_page = (ROOT / "templates/assembly.html").read_text()
        self.assertNotIn("operatorPassword", assembly_page)
        monitor_page = (ROOT / "templates/repair_workflow.html").read_text()
        self.assertIn("boardGeneration", monitor_page)
        self.assertIn("result.repair_stage!==expected", monitor_page)


if __name__ == "__main__":
    unittest.main()
