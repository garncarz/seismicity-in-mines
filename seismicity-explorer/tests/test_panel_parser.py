import unittest

from app.panel_parser import PanelInputError, parse_panel


EXAMPLE = """Souřadnice lomových bodů porubu 138 708 (1 až 6 po směru hodinových ručiček

1, -458381, -1103315
2, -457807, -1103568
3, -457826, -1103726
4, -458238, -1103545
5, -458261, -1103487
6, -458414, -1103420

Dobývání porubu od 1. 9. 1989 do 1. 12. 1990
Oblast pro sledování seismicity: vlastní plocha porubu + plocha 100 m vně obrysu porubu.
"""


class PanelParserTests(unittest.TestCase):
    def test_parses_project_example_and_buffer(self):
        parsed = parse_panel(EXAMPLE)
        self.assertEqual(parsed["identifier"], "138 708")
        self.assertEqual(parsed["vertices"][0], [-458381.0, -1103315.0])
        self.assertEqual(parsed["mining_start"], "1989-09-01")
        self.assertEqual(parsed["mining_end"], "1990-12-01")
        self.assertEqual(parsed["buffer_m"], 100)
        self.assertEqual(parsed["boundary_geojson"]["type"], "Polygon")

    def test_defaults_optional_dates_and_buffer(self):
        parsed = parse_panel(
            "Porub 42\n1 -458000 -1103000\n2 -457900 -1103000\n3 -457900 -1102900"
        )
        self.assertIsNone(parsed["mining_start"])
        self.assertIsNone(parsed["mining_end"])
        self.assertEqual(parsed["buffer_m"], 100)

    def test_accepts_identifier_punctuation_and_buffer_in_metres(self):
        parsed = parse_panel(
            "Porubu č. 42/7\n"
            "1, 0, 0\n2, 20, 0\n3, 20, 20\n"
            "sledovací oblast 75 metrů vně obrysu"
        )
        self.assertEqual(parsed["identifier"], "42 7")
        self.assertEqual(parsed["buffer_m"], 75)

    def test_rejects_self_intersecting_boundary(self):
        with self.assertRaisesRegex(PanelInputError, "invalid"):
            parse_panel(
                "Porub 42\n1, 0, 0\n2, 10, 10\n3, 0, 10\n4, 10, 0"
            )

    def test_rejects_duplicate_vertex_numbers(self):
        with self.assertRaisesRegex(PanelInputError, "unique"):
            parse_panel(
                "Porub 42\n1, 0, 0\n1, 10, 0\n3, 10, 10"
            )


if __name__ == "__main__":
    unittest.main()
