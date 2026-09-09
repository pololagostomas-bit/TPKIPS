from pathlib import Path
import unittest


class ReceptionStageTabsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")

    def test_zone_and_assignment_are_step_two_panels(self):
        self.assertIn('data-reception-panel="zona"', self.source)
        self.assertIn("zona:'2. Zona de recepción'", self.source)
        self.assertIn("admin:'2. Asignación'", self.source)

    def test_arrival_panel_does_not_capture_location(self):
        arrival = self.source.split('data-reception-panel="bultos"', 1)[1].split('data-reception-panel="zona"', 1)[0]
        self.assertNotIn("receipt-location-", arrival)
        self.assertIn("Paso 1 · Llegada", arrival)

    def test_stage_tabs_only_include_reached_stages_for_workers(self):
        self.assertIn("stage>=0&&stage<=current", self.source)
        self.assertIn("id==='admin'?isAdmin()&&current>=states.indexOf('ARRIBADO')", self.source)


if __name__ == "__main__":
    unittest.main()
