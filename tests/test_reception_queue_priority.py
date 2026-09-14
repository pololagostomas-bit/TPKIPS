from pathlib import Path
import unittest


class ReceptionQueuePriorityTests(unittest.TestCase):
    def test_queue_prioritizes_complete_fr_before_arrivals_and_other_rows(self):
        source = (Path(__file__).parents[1] / "backend" / "services" / "reception.py").read_text(encoding="utf-8")
        order = source.split("query += \"\"\" ORDER BY", 1)[1].split('LIMIT ?', 1)[0]
        self.assertIn("s.accounting_status = 'PENDIENTE EM' THEN 0", order)
        self.assertIn("s.app_status = 'PROGRAMADO' AND COALESCE(s.scheduled_date, '') <> '' THEN 1", order)
        self.assertIn("s.app_status = 'CERRADO' THEN 5", order)
        self.assertIn("LIMIT ?", source)


if __name__ == "__main__":
    unittest.main()
