import hashlib
import json
import math
import re
import unicodedata
from datetime import date, datetime, time
from io import BytesIO

from openpyxl import load_workbook
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError


SOURCE_TYPES = {
    "seismic_events": "Seismic events",
    "borehole_depths": "Measured borehole depths",
    "interpolated_depth_grid": "Interpolated depth grid",
}


class ImportInputError(ValueError):
    pass


def _token(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _headers(values: tuple) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        name = str(value).strip() if value is not None else ""
        name = name or f"column_{index}"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        result.append(name)
    return result


def _column(headers: list[str], *aliases: str) -> int | None:
    tokens = {_token(alias) for alias in aliases}
    for index, header in enumerate(headers):
        if _token(header) in tokens:
            return index
    return None


def _depth_column(headers: list[str]) -> int | None:
    for index, header in enumerate(headers):
        token = _token(header)
        if token.startswith("hloubka") or token in {"depth", "depthm"}:
            return index
    return None


def _coordinate_columns(headers: list[str]) -> tuple[int | None, int | None]:
    special_x = next(
        (i for i, header in enumerate(headers) if header.strip().casefold() == "!-y"),
        None,
    )
    special_y = next(
        (i for i, header in enumerate(headers) if header.strip().casefold() == "!-x"),
        None,
    )
    if special_x is not None and special_y is not None:
        return special_x, special_y
    x = _column(headers, "x", "x-coord", "x coord", "easting")
    y = _column(headers, "y", "y-coord", "y coord", "northing")
    return x, y


def infer_source_type(headers: list[str]) -> str:
    x, y = _coordinate_columns(headers)
    depth = _depth_column(headers)
    date_column = _column(headers, "datetime", "date", "datum", "date time")
    energy = _column(headers, "energy", "energie")
    if date_column is not None and energy is not None and x is not None and y is not None:
        return "seismic_events"
    if x is not None and y is not None and depth is not None:
        if _column(headers, "id", "borehole", "vrt") is not None or any(
            _token(header) in {"xcoord", "ycoord"} for header in headers
        ):
            return "borehole_depths"
        return "interpolated_depth_grid"
    raise ImportInputError(
        "Could not identify this workbook. Choose its type and check that it has "
        "date/time, X/Y and energy columns (events), or X/Y and a depth column."
    )


def _json_value(value: object) -> object:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace("\u00a0", "").replace(" ", "")
        if not text:
            return None
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _parse_date_text(value: str) -> datetime | None:
    text = value.strip()
    for pattern in (
        "%d. %m. %Y",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d. %m. %Y %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_time(value: object) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for pattern in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    return None


def _event_datetime(
    row: tuple, headers: list[str], values: dict[str, object]
) -> datetime | None:
    date_index = _column(headers, "datetime", "date", "datum", "date time")
    time_index = _column(headers, "hh:mm:ss.sss", "time", "cas", "time of event")
    date_value = row[date_index] if date_index is not None and date_index < len(row) else None
    time_value = row[time_index] if time_index is not None and time_index < len(row) else None
    if isinstance(date_value, datetime):
        date_part = date_value.date()
        parsed = datetime.combine(date_part, time.min)
    elif isinstance(date_value, date):
        parsed = datetime.combine(date_value, time.min)
    elif date_value is not None:
        parsed = _parse_date_text(str(date_value))
    else:
        parsed = None
    if parsed is None:
        combined = values.get("datetime")
        if isinstance(combined, datetime):
            parsed = combined
        elif isinstance(combined, str):
            parsed = _parse_date_text(combined)
    if parsed is None:
        return None
    if time_index is not None and time_value not in (None, ""):
        parsed_time = _parse_time(time_value)
        if parsed_time is None:
            return None
        parsed = datetime.combine(parsed.date(), parsed_time)
    return parsed


def _load_sheet(
    data: bytes, requested_type: str
) -> tuple[str, list[str], object, str]:
    if requested_type not in (*SOURCE_TYPES, "auto"):
        raise ImportInputError("Unsupported import type.")
    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ImportInputError(f"Unable to read the Excel workbook: {exc}") from exc
    selected = None
    selected_headers: list[str] = []
    selected_type = requested_type
    for worksheet in workbook.worksheets:
        first_row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        if not first_row:
            continue
        headers = _headers(first_row)
        try:
            detected = infer_source_type(headers)
        except ImportInputError:
            continue
        if requested_type == "auto" or requested_type == detected:
            selected = worksheet
            selected_headers = headers
            selected_type = detected if requested_type == "auto" else requested_type
            break
    if selected is None:
        if requested_type == "auto":
            raise ImportInputError("No sheet with recognizable event or depth columns was found.")
        raise ImportInputError(
            f"No sheet in this workbook matches the selected type "
            f"'{SOURCE_TYPES[requested_type]}'."
        )
    return selected.title, selected_headers, selected, selected_type


def _source_transformer(source_crs: str) -> tuple[str, Transformer | None]:
    try:
        source = CRS.from_user_input(source_crs)
    except CRSError as exc:
        raise ImportInputError(f"Invalid source CRS {source_crs!r}: {exc}") from exc
    if not (source.is_projected or source.is_geographic):
        raise ImportInputError("Source CRS must be projected or geographic.")
    normalized = source.to_string()
    if source.equals(CRS.from_epsg(5514)):
        return normalized, None
    return normalized, Transformer.from_crs(source, "EPSG:5514", always_xy=True)


def _project_coordinates(
    x: float, y: float, transformer: Transformer | None
) -> tuple[float, float] | None:
    if transformer is None:
        return x, y
    try:
        projected = transformer.transform(x, y, errcheck=True)
    except (ProjError, ValueError):
        return None
    if not all(math.isfinite(value) for value in projected):
        return None
    return projected


def import_workbook(
    data: bytes, filename: str, requested_type: str, connection,
    source_crs: str = "EPSG:5514",
) -> dict:
    sheet_name, headers, worksheet, source_type = _load_sheet(data, requested_type)
    source_crs, transformer = _source_transformer(source_crs)
    sha256 = hashlib.sha256(data).hexdigest()

    existing = connection.execute(
        "SELECT id, filename, rows_seen, accepted_rows, skipped_rows, "
        "duplicate_events, warnings, report FROM source_files "
        "WHERE sha256 = %s AND source_type = %s AND source_crs = %s",
        (sha256, source_type, source_crs),
    ).fetchone()
    if existing:
        return {
            "already_imported": True,
            "source_id": existing[0],
            "filename": existing[1],
            "source_crs": source_crs,
            "rows_seen": existing[2],
            "accepted_rows": existing[3],
            "skipped_rows": existing[4],
            "duplicate_events": existing[5],
            "warnings": existing[6],
            "issues": existing[7].get("issues", []),
        }

    source_id = connection.execute(
        "INSERT INTO source_files (filename, sha256, source_type, source_crs, sheet_name) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (filename, sha256, source_type, source_crs, sheet_name),
    ).fetchone()[0]
    stats = {
        "source_id": source_id,
        "filename": filename,
        "source_type": source_type,
        "source_crs": source_crs,
        "sheet_name": sheet_name,
        "rows_seen": 0,
        "accepted_rows": 0,
        "skipped_rows": 0,
        "duplicate_events": 0,
        "warnings": 0,
        "issues": [],
    }

    if source_type == "seismic_events":
        _import_events(connection, source_id, worksheet, headers, stats, transformer)
    else:
        _import_depths(
            connection, source_id, source_type, worksheet, headers, stats, transformer
        )

    from psycopg.types.json import Jsonb

    connection.execute(
        "UPDATE source_files SET rows_seen = %s, accepted_rows = %s, skipped_rows = %s, "
        "duplicate_events = %s, warnings = %s, report = %s "
        "WHERE id = %s",
        (
            stats["rows_seen"],
            stats["accepted_rows"],
            stats["skipped_rows"],
            stats["duplicate_events"],
            stats["warnings"],
            Jsonb({"issues": stats["issues"]}),
            source_id,
        ),
    )
    return stats


def _row_attributes(row: tuple, headers: list[str]) -> dict[str, object]:
    return {
        header: _json_value(row[index] if index < len(row) else None)
        for index, header in enumerate(headers)
    }


def _row_value(row: tuple, index: int | None) -> object:
    return row[index] if index is not None and index < len(row) else None


def _issue(stats: dict, row_number: int, message: str, warning: bool = False) -> None:
    if warning:
        stats["warnings"] += 1
    else:
        stats["skipped_rows"] += 1
    if len(stats["issues"]) < 50:
        stats["issues"].append({"row": row_number, "message": message})


def _fingerprint(
    observed_at: datetime, x: float, y: float, z: float | None,
    magnitude: float | None, energy: float | None,
) -> str:
    values = [
        observed_at.isoformat(timespec="microseconds"),
        format(x, ".12g"),
        format(y, ".12g"),
        "" if z is None else format(z, ".12g"),
        "" if magnitude is None else format(magnitude, ".12g"),
        "" if energy is None else format(energy, ".12g"),
    ]
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def _import_events(connection, source_id, worksheet, headers, stats, transformer) -> None:
    x_index, y_index = _coordinate_columns(headers)
    date_index = _column(headers, "datetime", "date", "datum", "date time")
    magnitude_index = _column(headers, "magn", "magnitude")
    energy_index = _column(headers, "energy", "energie")
    depth_index = _column(headers, "z", "depth", "depthm")
    if x_index is None or y_index is None or date_index is None or energy_index is None:
        raise ImportInputError("The selected sheet is missing required event columns.")
    connection.execute(
        "CREATE TEMP TABLE import_events (source_row integer, observed_at timestamp, "
        "x_m double precision, y_m double precision, z_m double precision, "
        "magnitude double precision, energy double precision, fingerprint char(64), "
        "attributes text) ON COMMIT DROP"
    )
    with connection.cursor().copy(
        "COPY import_events (source_row, observed_at, x_m, y_m, z_m, magnitude, "
        "energy, fingerprint, attributes) FROM STDIN"
    ) as copy:
        for source_row, row in enumerate(
            worksheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            if not any(value is not None for value in row):
                continue
            stats["rows_seen"] += 1
            attributes = _row_attributes(row, headers)
            x, y = _numeric(_row_value(row, x_index)), _numeric(_row_value(row, y_index))
            observed_at = _event_datetime(row, headers, attributes)
            if x is None or y is None:
                _issue(stats, source_row, "Missing or invalid event coordinates.")
                continue
            projected = _project_coordinates(x, y, transformer)
            if projected is None:
                _issue(stats, source_row, "Coordinates cannot be transformed to EPSG:5514.")
                continue
            x, y = projected
            if observed_at is None:
                _issue(stats, source_row, "Missing or invalid event date/time.")
                continue
            z = _numeric(_row_value(row, depth_index))
            magnitude = _numeric(_row_value(row, magnitude_index))
            energy = _numeric(_row_value(row, energy_index))
            if depth_index is not None and _row_value(row, depth_index) not in (None, "") and z is None:
                _issue(stats, source_row, "Invalid depth preserved in raw attributes; stored as null.", True)
            if magnitude_index is not None and _row_value(row, magnitude_index) not in (None, "") and magnitude is None:
                _issue(stats, source_row, "Invalid magnitude preserved in raw attributes; stored as null.", True)
            if _row_value(row, energy_index) not in (None, "") and energy is None:
                _issue(stats, source_row, "Invalid energy preserved in raw attributes; stored as null.", True)
            fingerprint = _fingerprint(observed_at, x, y, z, magnitude, energy)
            copy.write_row(
                (
                    source_row,
                    observed_at,
                    x,
                    y,
                    z,
                    magnitude,
                    energy,
                    fingerprint,
                    json.dumps(attributes, ensure_ascii=False),
                )
            )
            stats["accepted_rows"] += 1

    new_unique_events = connection.execute(
        "SELECT count(DISTINCT i.fingerprint) "
        "FROM import_events i LEFT JOIN seismic_events e USING (fingerprint) "
        "WHERE e.id IS NULL"
    ).fetchone()[0]
    stats["duplicate_events"] = stats["accepted_rows"] - new_unique_events

    connection.execute(
        "INSERT INTO seismic_events (observed_at, x_m, y_m, z_m, magnitude, energy, "
        "fingerprint, attributes, geom) "
        "SELECT DISTINCT ON (fingerprint) observed_at, x_m, y_m, z_m, magnitude, energy, "
        "fingerprint, attributes::jsonb, ST_SetSRID(ST_MakePoint(x_m, y_m), 5514) "
        "FROM import_events ORDER BY fingerprint, source_row "
        "ON CONFLICT (fingerprint) DO NOTHING"
    )
    connection.execute(
        "INSERT INTO event_sources (event_id, source_file_id, source_row, attributes) "
        "SELECT e.id, %s, i.source_row, i.attributes::jsonb "
        "FROM import_events i JOIN seismic_events e USING (fingerprint) "
        "ON CONFLICT (source_file_id, source_row) DO NOTHING RETURNING event_id",
        (source_id,),
    )


def _import_depths(
    connection, source_id, source_type, worksheet, headers, stats, transformer
) -> None:
    x_index, y_index = _coordinate_columns(headers)
    depth_index = _depth_column(headers)
    id_index = _column(headers, "id", "borehole", "vrt")
    if x_index is None or y_index is None or depth_index is None:
        raise ImportInputError("The selected sheet is missing X, Y, or depth columns.")
    point_type = "borehole" if source_type == "borehole_depths" else "grid"
    connection.execute(
        "CREATE TEMP TABLE import_depths (source_row integer, x_m double precision, "
        "y_m double precision, depth_m double precision, point_identifier text, "
        "attributes text) ON COMMIT DROP"
    )
    with connection.cursor().copy(
        "COPY import_depths (source_row, x_m, y_m, depth_m, point_identifier, attributes) "
        "FROM STDIN"
    ) as copy:
        for source_row, row in enumerate(
            worksheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            if not any(value is not None for value in row):
                continue
            stats["rows_seen"] += 1
            attributes = _row_attributes(row, headers)
            x, y = _numeric(_row_value(row, x_index)), _numeric(_row_value(row, y_index))
            if x is None or y is None:
                _issue(stats, source_row, "Missing or invalid point coordinates.")
                continue
            projected = _project_coordinates(x, y, transformer)
            if projected is None:
                _issue(stats, source_row, "Coordinates cannot be transformed to EPSG:5514.")
                continue
            x, y = projected
            depth = _numeric(_row_value(row, depth_index))
            if depth is None:
                _issue(stats, source_row, "Missing or invalid depth value.")
                continue
            identifier = _row_value(row, id_index)
            copy.write_row(
                (
                    source_row,
                    x,
                    y,
                    depth,
                    str(identifier) if identifier not in (None, "") else None,
                    json.dumps(attributes, ensure_ascii=False),
                )
            )
            stats["accepted_rows"] += 1
    connection.execute(
        "INSERT INTO depth_points (source_file_id, source_row, point_type, point_identifier, "
        "depth_m, attributes, geom) "
        "SELECT %s, source_row, %s, point_identifier, depth_m, attributes::jsonb, "
        "ST_SetSRID(ST_MakePoint(x_m, y_m), 5514) FROM import_depths "
        "ON CONFLICT (source_file_id, source_row) DO NOTHING",
        (source_id, point_type),
    )
