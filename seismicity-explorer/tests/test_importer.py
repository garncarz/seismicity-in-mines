import unittest
from datetime import datetime

from app.importer import (
    _coordinate_columns,
    _event_datetime,
    _numeric,
    _project_coordinates,
    _source_transformer,
    infer_source_type,
)
from app.importer import ImportInputError


class ImporterTests(unittest.TestCase):
    def test_mining_workbook_coordinate_labels_follow_existing_loader(self):
        headers = ["Datum", "hh:mm:ss.sss", "!-Y", "!-X", "Z", "Magn", "Energie"]
        self.assertEqual(_coordinate_columns(headers), (2, 3))
        self.assertEqual(infer_source_type(headers), "seismic_events")

    def test_infers_depth_dataset_types(self):
        self.assertEqual(
            infer_source_type(["ID", "x-coord", "y-coord", "hloubka sloje 40"]),
            "borehole_depths",
        )
        self.assertEqual(
            infer_source_type(["X", "Y", "hloubka sloje 40"]),
            "interpolated_depth_grid",
        )

    def test_parses_excel_date_and_mining_time_fields(self):
        headers = ["Datum", "hh:mm:ss.sss"]
        row = (datetime(2013, 7, 1), "04:41:12.091")
        self.assertEqual(
            _event_datetime(row, headers, {}),
            datetime(2013, 7, 1, 4, 41, 12, 91000),
        )

    def test_numeric_parser_accepts_decimal_comma_and_rejects_bad_values(self):
        self.assertEqual(_numeric("1.234,56"), 1234.56)
        self.assertIsNone(_numeric("unknown"))

    def test_source_crs_is_explicitly_transformed_to_mining_coordinates(self):
        crs, transformer = _source_transformer("EPSG:4326")
        x, y = _project_coordinates(18.4539020939, 49.8291231061, transformer)
        self.assertEqual(crs, "EPSG:4326")
        self.assertAlmostEqual(x, -458381, delta=0.1)
        self.assertAlmostEqual(y, -1103315, delta=0.1)

    def test_rejects_invalid_source_crs(self):
        with self.assertRaises(ImportInputError):
            _source_transformer("not-a-crs")


if __name__ == "__main__":
    unittest.main()
