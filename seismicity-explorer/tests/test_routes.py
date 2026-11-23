import unittest

from app import create_app
from app.routes import _filters


PANEL = {
    "description": (
        "Porub 138 708\n"
        "1, -458381, -1103315\n"
        "2, -457807, -1103568\n"
        "3, -457826, -1103726\n"
        "Dobývání porubu od 1. 9. 1989 do 1. 12. 1990"
    )
}


class PanelRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_preview_returns_transformed_boundary_and_parsed_fields(self):
        response = self.client.post("/api/panels/preview", json=PANEL)
        self.assertEqual(response.status_code, 200)
        preview = response.get_json()
        self.assertEqual(preview["identifier"], "138 708")
        self.assertEqual(preview["mining_start"], "1989-09-01")
        self.assertEqual(preview["monitoring_geojson"]["type"], "Polygon")

    def test_preview_reports_invalid_polygon_input(self):
        response = self.client.post("/api/panels/preview", json={"description": "Porub 42"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("vertices", response.get_json()["error"])

    def test_homepage_serves_the_application_shell(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Seismicity Explorer", response.data)
        self.assertIn(b'<option value="mining" selected>', response.data)
        self.assertNotIn(b'id="show-boreholes"', response.data)
        self.assertNotIn(b'id="show-grid"', response.data)

    def test_api_filter_defaults_to_the_panel_mining_period(self):
        with self.client.application.test_request_context("/api/events?panel_id=1"):
            filters = _filters()
        self.assertEqual(filters[1], "mining")

    def test_coordinate_grid_returns_projected_x_and_y_lines(self):
        response = self.client.get(
            "/api/coordinate-grid"
            "?west=18.45&south=49.82&east=18.47&north=49.84&spacing=500"
        )
        self.assertEqual(response.status_code, 200)
        grid = response.get_json()
        self.assertEqual(grid["type"], "FeatureCollection")
        self.assertEqual(grid["spacing_m"], 500)
        features = grid["features"]
        self.assertTrue(any(feature["properties"]["axis"] == "X" for feature in features))
        self.assertTrue(any(feature["properties"]["axis"] == "Y" for feature in features))
        self.assertTrue(all(
            feature["geometry"]["type"] == "LineString"
            and len(feature["geometry"]["coordinates"]) > 2
            for feature in features
        ))

    def test_coordinate_grid_rejects_unsupported_spacing(self):
        response = self.client.get(
            "/api/coordinate-grid"
            "?west=18.45&south=49.82&east=18.47&north=49.84&spacing=1"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("spacing", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
