import math
from datetime import date

from flask import Blueprint, jsonify, render_template, request
from pyproj import Transformer
from werkzeug.exceptions import HTTPException
from psycopg.types.json import Jsonb

from .db import connect, geojson_value
from .importer import ImportInputError, import_workbook
from .panel_parser import PanelInputError, parse_panel
from shapely.geometry import Polygon


api = Blueprint("api", __name__)
_GRID_SPACINGS = {100, 250, 500, 1000, 2500, 5000, 10000}


@api.get("/")
def index():
    return render_template("index.html")


@api.get("/api/health")
def health():
    with connect() as connection:
        connection.execute("SELECT 1")
    return jsonify({"status": "ok"})


@api.get("/api/coordinate-grid")
def coordinate_grid():
    bounds = [
        request.args.get(name, type=float)
        for name in ("west", "south", "east", "north")
    ]
    if any(value is None or not math.isfinite(value) for value in bounds):
        return jsonify({"error": "Valid west, south, east, and north bounds are required."}), 400
    west, south, east, north = bounds
    if (
        not -180 <= west < east <= 180
        or not -90 <= south < north <= 90
        or east - west > 20
    ):
        return jsonify({"error": "Map bounds must cover a valid local area."}), 400
    spacing = request.args.get("spacing", default=1000, type=int)
    if spacing not in _GRID_SPACINGS:
        return jsonify({"error": "Unsupported coordinate-grid spacing."}), 400

    to_mining = Transformer.from_crs("EPSG:4326", "EPSG:5514", always_xy=True)
    to_geographic = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
    edge_points = []
    steps = 20
    for step in range(steps + 1):
        ratio = step / steps
        longitude = west + (east - west) * ratio
        latitude = south + (north - south) * ratio
        edge_points.extend(
            ((longitude, south), (longitude, north), (west, latitude), (east, latitude))
        )
    projected = [
        to_mining.transform(longitude, latitude)
        for longitude, latitude in edge_points
    ]
    projected = [(x, y) for x, y in projected if math.isfinite(x) and math.isfinite(y)]
    if not projected:
        return jsonify({"error": "Map bounds could not be transformed to EPSG:5514."}), 400
    min_x = min(point[0] for point in projected)
    max_x = max(point[0] for point in projected)
    min_y = min(point[1] for point in projected)
    max_y = max(point[1] for point in projected)
    x_values = range(
        math.ceil(min_x / spacing) * spacing,
        math.floor(max_x / spacing) * spacing + 1,
        spacing,
    )
    y_values = range(
        math.ceil(min_y / spacing) * spacing,
        math.floor(max_y / spacing) * spacing + 1,
        spacing,
    )
    if len(x_values) + len(y_values) > 160:
        return jsonify(
            {"error": "Zoom in to view the coordinate grid at this spacing."}
        ), 400

    features = []
    for axis, values, start, end in (
        ("X", x_values, min_y, max_y),
        ("Y", y_values, min_x, max_x),
    ):
        for value in values:
            line = []
            for step in range(steps + 1):
                position = start + (end - start) * step / steps
                x, y = (value, position) if axis == "X" else (position, value)
                longitude, latitude = to_geographic.transform(x, y)
                if math.isfinite(longitude) and math.isfinite(latitude):
                    line.append([longitude, latitude])
            if len(line) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": line},
                    "properties": {"axis": axis, "value": value},
                }
            )
    return jsonify(
        {
            "type": "FeatureCollection",
            "spacing_m": spacing,
            "features": features,
        }
    )


@api.errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"error": error.description}), error.code
    return error


@api.get("/api/panels")
def list_panels():
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, identifier, seam, mining_start, mining_end, buffer_m, "
            "ST_AsGeoJSON(ST_Transform(boundary, 4326)), "
            "ST_AsGeoJSON(ST_Transform(monitoring_area, 4326)) "
            "FROM mining_panels ORDER BY identifier, id"
        ).fetchall()
    return jsonify(
        [
            {
                "id": row[0],
                "identifier": row[1],
                "seam": row[2],
                "mining_start": row[3].isoformat() if row[3] else None,
                "mining_end": row[4].isoformat() if row[4] else None,
                "buffer_m": row[5],
                "boundary": geojson_value(row[6]),
                "monitoring_area": geojson_value(row[7]),
            }
            for row in rows
        ]
    )


@api.get("/api/panels/<int:panel_id>")
def get_panel(panel_id: int):
    with connect() as connection:
        row = connection.execute(
            "SELECT id, identifier, seam, mining_start, mining_end, buffer_m, "
            "original_description, vertices FROM mining_panels WHERE id = %s",
            (panel_id,),
        ).fetchone()
    if not row:
        return jsonify({"error": "Panel not found."}), 404
    return jsonify(
        {
            "id": row[0],
            "identifier": row[1],
            "seam": row[2],
            "mining_start": row[3].isoformat() if row[3] else None,
            "mining_end": row[4].isoformat() if row[4] else None,
            "buffer_m": row[5],
            "description": row[6],
            "vertices": row[7],
        }
    )


def _panel_input():
    data = request.get_json(silent=True) or {}
    description = data.get("description")
    if not isinstance(description, str):
        return None, None, (jsonify({"error": "Panel description is required."}), 400)
    try:
        parsed = parse_panel(description)
    except PanelInputError as exc:
        return None, None, (jsonify({"error": str(exc)}), 400)
    seam = data.get("seam")
    if seam is not None and not isinstance(seam, str):
        return None, None, (jsonify({"error": "Seam must be text."}), 400)
    seam = seam.strip() if seam else None
    return parsed, seam or None, None


@api.post("/api/panels/preview")
def preview_panel():
    parsed, _seam, error = _panel_input()
    if error:
        return error
    return jsonify(parsed)


@api.post("/api/panels")
def create_panel():
    parsed, seam, error = _panel_input()
    if error:
        return error
    polygon = Polygon(parsed["vertices"])
    with connect() as connection:
        row = connection.execute(
            "INSERT INTO mining_panels "
            "(identifier, seam, mining_start, mining_end, buffer_m, original_description, "
            "vertices, boundary, monitoring_area) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, "
            "ST_SetSRID(ST_GeomFromText(%s), 5514), "
            "ST_Multi(ST_Buffer(ST_SetSRID(ST_GeomFromText(%s), 5514), %s))) "
            "RETURNING id",
            (
                parsed["identifier"],
                seam,
                parsed["mining_start"],
                parsed["mining_end"],
                parsed["buffer_m"],
                request.get_json()["description"],
                Jsonb(parsed["vertices"]),
                polygon.wkt,
                polygon.wkt,
                parsed["buffer_m"],
            ),
        ).fetchone()
    return jsonify({"id": row[0], "identifier": parsed["identifier"]}), 201


@api.put("/api/panels/<int:panel_id>")
def update_panel(panel_id: int):
    parsed, seam, error = _panel_input()
    if error:
        return error
    polygon = Polygon(parsed["vertices"])
    with connect() as connection:
        row = connection.execute(
            "UPDATE mining_panels SET identifier = %s, seam = %s, mining_start = %s, "
            "mining_end = %s, buffer_m = %s, original_description = %s, vertices = %s, "
            "boundary = ST_SetSRID(ST_GeomFromText(%s), 5514), "
            "monitoring_area = ST_Multi(ST_Buffer(ST_SetSRID(ST_GeomFromText(%s), 5514), %s)), "
            "updated_at = now() WHERE id = %s RETURNING id",
            (
                parsed["identifier"],
                seam,
                parsed["mining_start"],
                parsed["mining_end"],
                parsed["buffer_m"],
                request.get_json()["description"],
                Jsonb(parsed["vertices"]),
                polygon.wkt,
                polygon.wkt,
                parsed["buffer_m"],
                panel_id,
            ),
        ).fetchone()
    if not row:
        return jsonify({"error": "Panel not found."}), 404
    return jsonify({"id": panel_id, "identifier": parsed["identifier"]})


@api.delete("/api/panels/<int:panel_id>")
def delete_panel(panel_id: int):
    with connect() as connection:
        result = connection.execute(
            "DELETE FROM mining_panels WHERE id = %s RETURNING id", (panel_id,)
        ).fetchone()
    if not result:
        return jsonify({"error": "Panel not found."}), 404
    return jsonify({"deleted": panel_id})


@api.post("/api/import")
def import_file():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose an .xlsx workbook to import."}), 400
    if not upload.filename.casefold().endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files are supported in this version."}), 400
    requested_type = request.form.get("source_type", "auto")
    source_crs = request.form.get("source_crs", "EPSG:5514")
    try:
        data = upload.read()
        with connect() as connection:
            result = import_workbook(
                data, upload.filename, requested_type, connection, source_crs
            )
    except ImportInputError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@api.get("/api/sources")
def list_sources():
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, filename, source_type, source_crs, sheet_name, imported_at, rows_seen, "
            "accepted_rows, skipped_rows, duplicate_events, warnings, report "
            "FROM source_files ORDER BY imported_at DESC, id DESC"
        ).fetchall()
    return jsonify(
        [
            {
                "id": row[0],
                "filename": row[1],
                "source_type": row[2],
                "source_crs": row[3],
                "sheet_name": row[4],
                "imported_at": row[5].isoformat(),
                "rows_seen": row[6],
                "accepted_rows": row[7],
                "skipped_rows": row[8],
                "duplicate_events": row[9],
                "warnings": row[10],
                "issues": row[11].get("issues", []),
            }
            for row in rows
        ]
    )


def _filters():
    panel_id = request.args.get("panel_id", type=int)
    if not panel_id:
        return None, None, None, None, None, (
            jsonify({"error": "Select a mining panel first."}),
            400,
        )
    mode = request.args.get("period", "all")
    if mode not in {"mining", "range", "all"}:
        return None, None, None, None, None, (
            jsonify({"error": "Period must be 'mining', 'range', or 'all'."}),
            400,
        )
    start = end = None
    if mode == "range":
        try:
            start = date.fromisoformat(request.args.get("start", ""))
            end = date.fromisoformat(request.args.get("end", ""))
        except ValueError:
            return None, None, None, None, None, (
                jsonify({"error": "Provide valid start and end dates (YYYY-MM-DD)."}),
                400,
            )
        if start > end:
            return None, None, None, None, None, (
                jsonify({"error": "Start date must not be after end date."}),
                400,
            )
    min_energy = _optional_nonnegative("min_energy")
    if isinstance(min_energy, tuple):
        return None, None, None, None, None, min_energy
    min_magnitude = _optional_finite("min_magnitude")
    if isinstance(min_magnitude, tuple):
        return None, None, None, None, None, min_magnitude
    return panel_id, mode, start, end, (min_energy, min_magnitude), None


def _optional_nonnegative(name: str):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except ValueError:
        return jsonify({"error": f"{name} must be a number."}), 400
    if not math.isfinite(number) or number < 0:
        return jsonify({"error": f"{name} must be a finite non-negative number."}), 400
    return number


def _optional_finite(name: str):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except ValueError:
        return jsonify({"error": f"{name} must be a number."}), 400
    if not math.isfinite(number):
        return jsonify({"error": f"{name} must be a finite number."}), 400
    return number


def _where_filters(panel_id, mode, start, end, minimums):
    clauses = ["ST_Intersects(e.geom, p.monitoring_area)"]
    params: list[object] = []
    if mode == "mining":
        clauses.extend(
            [
                "p.mining_start IS NOT NULL",
                "p.mining_end IS NOT NULL",
                "e.observed_at >= p.mining_start::timestamp",
                "e.observed_at < (p.mining_end + 1)::timestamp",
            ]
        )
    elif mode == "range":
        clauses.extend(
            [
                "e.observed_at >= %s::timestamp",
                "e.observed_at < (%s::date + 1)::timestamp",
            ]
        )
        params.extend([start.isoformat(), end.isoformat()])
    min_energy, min_magnitude = minimums
    if min_energy is not None:
        clauses.append("e.energy >= %s")
        params.append(min_energy)
    if min_magnitude is not None:
        clauses.append("e.magnitude >= %s")
        params.append(min_magnitude)
    return " AND ".join(clauses), params


def _validated_filters():
    values = _filters()
    if values[-1] is not None:
        return None, values[-1]
    return values[:-1], None


def _panel_filter_error(connection, panel_id, require_dates=False):
    row = connection.execute(
        "SELECT mining_start, mining_end FROM mining_panels WHERE id = %s",
        (panel_id,),
    ).fetchone()
    if not row:
        return jsonify({"error": "Panel not found."}), 404
    if require_dates and (row[0] is None or row[1] is None):
        return (
            jsonify(
                {
                    "error": "This panel has no complete mining period. "
                    "Edit the panel dates or choose another time filter."
                }
            ),
            400,
        )
    return None


@api.get("/api/events")
def list_events():
    filters, error = _validated_filters()
    if error:
        return error
    panel_id, mode, start, end, minimums = filters
    where, params = _where_filters(panel_id, mode, start, end, minimums)
    limit = min(max(request.args.get("limit", 6000, type=int), 1), 20000)
    with connect() as connection:
        panel_error = _panel_filter_error(connection, panel_id, mode == "mining")
        if panel_error:
            return panel_error
        rows = connection.execute(
            "SELECT e.id, e.observed_at, e.magnitude, e.energy, e.z_m, "
            "e.attributes, ST_X(ST_Transform(e.geom, 4326)), "
            "ST_Y(ST_Transform(e.geom, 4326)) "
            "FROM seismic_events e JOIN mining_panels p ON p.id = %s "
            f"WHERE {where} ORDER BY e.observed_at DESC, e.id DESC LIMIT %s",
            [panel_id, *params, limit],
        ).fetchall()
    return jsonify(
        {
            "events": [
                {
                    "id": row[0],
                    "datetime": row[1].isoformat(),
                    "magnitude": row[2],
                    "energy": row[3],
                    "z_m": row[4],
                    "attributes": row[5],
                    "longitude": row[6],
                    "latitude": row[7],
                }
                for row in rows
            ],
            "returned": len(rows),
            "limit": limit,
            "truncated": len(rows) == limit,
        }
    )


@api.get("/api/statistics")
def statistics():
    filters, error = _validated_filters()
    if error:
        return error
    panel_id, mode, start, end, minimums = filters
    where, params = _where_filters(panel_id, mode, start, end, minimums)
    with connect() as connection:
        panel_error = _panel_filter_error(connection, panel_id, mode == "mining")
        if panel_error:
            return panel_error
        summary = connection.execute(
            "SELECT count(*), coalesce(sum(e.energy), 0), avg(e.magnitude), "
            "max(e.magnitude), max(e.energy) "
            "FROM seismic_events e JOIN mining_panels p ON p.id = %s "
            f"WHERE {where}",
            [panel_id, *params],
        ).fetchone()
        energy_bins = connection.execute(
            "SELECT CASE WHEN e.energy < 10 THEN '<10' "
            "WHEN e.energy < 100 THEN '10-100' "
            "WHEN e.energy < 1000 THEN '100-1k' "
            "WHEN e.energy < 10000 THEN '1k-10k' "
            "WHEN e.energy < 100000 THEN '10k-100k' "
            "WHEN e.energy < 1000000 THEN '100k-1m' "
            "ELSE '>=1m' END AS bin, count(*) "
            "FROM seismic_events e JOIN mining_panels p ON p.id = %s "
            f"WHERE {where} AND e.energy IS NOT NULL GROUP BY bin "
            "ORDER BY min(e.energy)",
            [panel_id, *params],
        ).fetchall()
        timeline = connection.execute(
            "WITH monthly AS (SELECT date_trunc('month', e.observed_at)::date AS month, "
            "count(*) AS event_count, coalesce(sum(e.energy), 0) AS energy "
            "FROM seismic_events e JOIN mining_panels p ON p.id = %s "
            f"WHERE {where} GROUP BY 1) "
            "SELECT month, event_count, energy, sum(energy) OVER (ORDER BY month) "
            "FROM monthly ORDER BY month",
            [panel_id, *params],
        ).fetchall()
    return jsonify(
        {
            "count": summary[0],
            "total_energy": float(summary[1]),
            "mean_magnitude": float(summary[2]) if summary[2] is not None else None,
            "max_magnitude": summary[3],
            "max_energy": summary[4],
            "energy_distribution": [
                {"bin": row[0], "count": row[1]} for row in energy_bins
            ],
            "timeline": [
                {
                    "month": row[0].isoformat(),
                    "count": row[1],
                    "energy": float(row[2]),
                    "cumulative_energy": float(row[3]),
                }
                for row in timeline
            ],
        }
    )


@api.get("/api/depth-points")
def depth_points():
    panel_id = request.args.get("panel_id", type=int)
    if not panel_id:
        return jsonify({"error": "Select a mining panel first."}), 400
    point_type = request.args.get("kind", "all")
    if point_type not in {"all", "borehole", "grid"}:
        return jsonify({"error": "kind must be all, borehole, or grid."}), 400
    clauses = ["ST_Intersects(d.geom, p.monitoring_area)"]
    params: list[object] = []
    if point_type != "all":
        clauses.append("d.point_type = %s")
        params.append(point_type)
    limit = 5000
    with connect() as connection:
        panel_error = _panel_filter_error(connection, panel_id)
        if panel_error:
            return panel_error
        rows = connection.execute(
            "SELECT d.id, d.point_type, d.point_identifier, d.depth_m, d.attributes, "
            "ST_X(ST_Transform(d.geom, 4326)), ST_Y(ST_Transform(d.geom, 4326)) "
            "FROM depth_points d JOIN mining_panels p ON p.id = %s "
            f"WHERE {' AND '.join(clauses)} ORDER BY d.id LIMIT %s",
            [panel_id, *params, limit],
        ).fetchall()
    return jsonify(
        {
            "points": [
                {
                    "id": row[0],
                    "kind": row[1],
                    "identifier": row[2],
                    "depth_m": row[3],
                    "attributes": row[4],
                    "longitude": row[5],
                    "latitude": row[6],
                }
                for row in rows
            ],
            "truncated": len(rows) == limit,
        }
    )
