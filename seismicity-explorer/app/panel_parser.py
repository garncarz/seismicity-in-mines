import re
import unicodedata
from datetime import date

from pyproj import Transformer
from shapely import transform as transform_geometry
from shapely.geometry import Polygon, mapping


_TO_WGS84 = Transformer.from_crs("EPSG:5514", "EPSG:4326", always_xy=True)
_NUMBER = r"(-?\d+(?:[.,]\d+)?)"
_DATE = r"(\d{1,4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,4})"


class PanelInputError(ValueError):
    pass


def _date(value: str) -> date:
    match = re.fullmatch(_DATE, value.strip())
    if not match:
        raise PanelInputError(f"Unrecognized Czech/ISO date: {value.strip()!r}.")
    first, second, third = (int(part) for part in match.groups())
    if first > 31:
        year, month, day = first, second, third
    else:
        day, month, year = first, second, third
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise PanelInputError(f"Invalid date {value.strip()!r}: {exc}.") from exc


def _coordinate(value: str) -> float:
    return float(value.replace(",", "."))


def parse_panel(description: str) -> dict:
    if not description.strip():
        raise PanelInputError("Provide the panel details and boundary coordinates.")

    identifier_match = re.search(
        r"\bporub(?:u|y)?\s*(?:(?:č(?:\s*íslo)?\.?|cislo)\s*)?[:#-]?\s*"
        r"([^\r\n(]+)",
        description,
        re.IGNORECASE,
    )
    if not identifier_match:
        raise PanelInputError("Could not find a panel identifier after 'porub'.")
    raw_identifier = identifier_match.group(1).strip().rstrip(" ,;:")
    if re.fullmatch(r"\d+(?:[\s/,-]+\d+)?", raw_identifier):
        identifier = re.sub(r"[\s/,-]+", " ", raw_identifier).strip()
    else:
        identifier = re.sub(r"\s+", " ", raw_identifier)
    if not identifier or not re.fullmatch(r"[\w./ -]+", identifier):
        raise PanelInputError("Panel name may contain letters, numbers, spaces, dots, slashes, or hyphens.")
    if len(identifier) > 100:
        raise PanelInputError("Panel name must be 100 characters or fewer.")

    points: list[tuple[int, float, float]] = []
    for line in description.splitlines():
        match = re.match(
            rf"^\s*(\d+)\s*[,;\t ]+\s*{_NUMBER}\s*[,;\t ]+\s*{_NUMBER}\s*$",
            line,
        )
        if match:
            index, x, y = match.groups()
            points.append((int(index), _coordinate(x), _coordinate(y)))
    if len(points) < 3:
        raise PanelInputError(
            f"Found only {len(points)} vertices; at least three coordinate rows are required."
        )
    indices = [point[0] for point in points]
    if len(indices) != len(set(indices)):
        raise PanelInputError("Vertex numbers must be unique.")
    points.sort(key=lambda point: point[0])
    vertices = [[x, y] for _, x, y in points]
    if any(abs(value) > 10_000_000 for vertex in vertices for value in vertex):
        raise PanelInputError("Coordinates are outside a plausible EPSG:5514 range.")

    polygon = Polygon(vertices)
    if not polygon.is_valid:
        raise PanelInputError("The panel boundary is self-intersecting or otherwise invalid.")
    if polygon.is_empty or polygon.area <= 0:
        raise PanelInputError("The panel boundary must enclose a non-zero area.")

    start_match = re.search(rf"\bod\s+{_DATE}", description, re.IGNORECASE)
    end_match = re.search(rf"\bdo\s+{_DATE}", description, re.IGNORECASE)
    start = _date(start_match.group(0).split(maxsplit=1)[1]) if start_match else None
    end = _date(end_match.group(0).split(maxsplit=1)[1]) if end_match else None
    if start and end and start > end:
        raise PanelInputError("Mining start date must not be after the end date.")

    normalized = unicodedata.normalize("NFKD", description).encode("ascii", "ignore").decode()
    buffer_match = re.search(
        r"(?:buffer|vne\s+obrysu|plocha|oblast)\D{0,80}(\d+(?:[.,]\d+)?)\s*"
        r"(?:m\b|metr(?:u|y)?\b|meters?\b|metres?\b)",
        normalized,
        re.IGNORECASE,
    )
    buffer_m = _coordinate(buffer_match.group(1)) if buffer_match else 100.0
    if buffer_m < 0 or buffer_m > 100_000:
        raise PanelInputError("Buffer distance must be between 0 and 100,000 metres.")

    monitoring = polygon.buffer(buffer_m)
    def to_wgs84(coordinates):
        longitudes, latitudes = _TO_WGS84.transform(
            coordinates[:, 0], coordinates[:, 1]
        )
        return [[longitude, latitude] for longitude, latitude in zip(longitudes, latitudes)]

    original_wgs84 = transform_geometry(polygon, to_wgs84)
    monitoring_wgs84 = transform_geometry(monitoring, to_wgs84)
    return {
        "identifier": identifier,
        "vertices": vertices,
        "mining_start": start.isoformat() if start else None,
        "mining_end": end.isoformat() if end else None,
        "buffer_m": buffer_m,
        "boundary_geojson": mapping(original_wgs84),
        "monitoring_geojson": mapping(monitoring_wgs84),
    }
