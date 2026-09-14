from pathlib import Path
import unittest


class ReceptionFilterRegressionTests(unittest.TestCase):
    def test_detail_render_has_no_content_mutation_observer(self):
        template = Path(__file__).parents[1] / "frontend" / "templates" / "reception.html"
        source = template.read_text(encoding="utf-8")
        self.assertNotIn("const detailObserver=new MutationObserver", source)
        self.assertIn("La IP se consulta únicamente en", source)


if __name__ == "__main__":
    unittest.main()
