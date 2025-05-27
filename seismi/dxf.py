"""
Functions for processing DXF files and converting DXF entities to GeoDataFrames.
"""
import math

import ezdxf
import geopandas as gpd
from shapely.affinity import translate, scale, rotate
from shapely.geometry import LineString, Point, Polygon

def arc_to_linestring(e, resolution=30):
    """
    Convert a DXF arc entity to a shapely LineString.

    Parameters:
    -----------
    e : ezdxf.entities.Arc
        The DXF arc entity to convert
    resolution : int, default 30
        Number of points to use for the arc approximation

    Returns:
    --------
    shapely.geometry.LineString
        LineString representation of the arc
    """
    center = e.dxf.center
    radius = e.dxf.radius
    start_angle = math.radians(e.dxf.start_angle)
    end_angle = math.radians(e.dxf.end_angle)
    if end_angle < start_angle:
        end_angle += 2 * math.pi
    angles = [start_angle + i * (end_angle - start_angle) / resolution for i in range(resolution + 1)]
    points = [(center.x + radius * math.cos(a), center.y + radius * math.sin(a)) for a in angles]
    return LineString(points)


def safe_polyline_to_geom(points, is_closed):
    """
    Safely convert a polyline to either a LineString or Polygon based on whether it's closed.

    Parameters:
    -----------
    points : list of tuples
        List of (x, y) coordinate tuples
    is_closed : bool
        Whether the polyline is closed

    Returns:
    --------
    shapely.geometry.LineString or shapely.geometry.Polygon
        The appropriate geometry type or None if not enough points
    """
    # Need at least 2 points for LineString, 4 for Polygon (with closing point)
    if len(points) < 2:
        return None
    elif is_closed and len(points) >= 3:
        # Ensure it loops by repeating the first point
        if points[0] != points[-1]:
            points.append(points[0])
        return Polygon(points)
    else:
        return LineString(points)


def explode_insert(insert_entity, doc):
    """
    Explode a DXF INSERT entity into its component geometries.

    Parameters:
    -----------
    insert_entity : ezdxf.entities.Insert
        The DXF INSERT entity to explode
    doc : ezdxf.document.Drawing
        The DXF document containing the block definitions

    Returns:
    --------
    list
        List of shapely geometries
    """
    block_name = insert_entity.dxf.name
    block = doc.blocks.get(block_name)
    insert_point = insert_entity.dxf.insert
    rotation = insert_entity.dxf.rotation
    xscale = insert_entity.dxf.xscale
    yscale = insert_entity.dxf.yscale

    exploded_geoms = []

    for entity in block:
        if entity.dxftype() == 'LINE':
            start = (entity.dxf.start.x, entity.dxf.start.y)
            end = (entity.dxf.end.x, entity.dxf.end.y)
            line = LineString([start, end])
            line = scale(line, xfact=xscale, yfact=yscale, origin=(0, 0))
            line = rotate(line, rotation, origin=(0, 0))
            line = translate(line, xoff=insert_point.x, yoff=insert_point.y)
            exploded_geoms.append(line)

        elif entity.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
            points = [(p[0], p[1]) for p in entity.get_points()]
            geom = safe_polyline_to_geom(points, entity.closed)
            if geom:
                geom = scale(geom, xfact=xscale, yfact=yscale, origin=(0, 0))
                geom = rotate(geom, rotation, origin=(0, 0))
                geom = translate(geom, xoff=insert_point.x, yoff=insert_point.y)
                exploded_geoms.append(geom)

        # You can add more types here: ARC, CIRCLE, etc.

    return exploded_geoms


def load_dxf(filename, source_crs='EPSG:5514', target_crs='EPSG:4326'):
    """
    Load a DXF file and convert it to a GeoDataFrame.

    Parameters:
    -----------
    filename : str
        Path to the DXF file
    source_crs : str, default 'EPSG:5514'
        Source coordinate reference system
    target_crs : str, default 'EPSG:4326'
        Target coordinate reference system

    Returns:
    --------
    geopandas.GeoDataFrame
        GeoDataFrame containing the geometries from the DXF file
    """
    doc = ezdxf.readfile(filename)
    msp = doc.modelspace()

    geoms = []

    for e in msp.query('LINE'):
        start = (e.dxf.start.x, e.dxf.start.y)
        end = (e.dxf.end.x, e.dxf.end.y)
        geoms.append(LineString([start, end]))

    for e in msp.query('LWPOLYLINE POLYLINE'):
        points = [(p[0], p[1]) for p in e.get_points()]
        if e.closed:
            if geom := safe_polyline_to_geom(points, e.closed):
                geoms.append(geom)
        else:
            geoms.append(LineString(points))

    for e in msp.query('CIRCLE'):
        center = (e.dxf.center.x, e.dxf.center.y)
        radius = e.dxf.radius
        geoms.append(Point(center).buffer(radius, resolution=64))  # approximate circle

    for e in msp.query('ARC'):
        geoms.append(arc_to_linestring(e))

    insert_geoms = []
    for insert in msp.query('INSERT'):
        insert_geoms.extend(explode_insert(insert, doc))

    all_geoms = geoms + insert_geoms

    dxf_gdf = gpd.GeoDataFrame(geometry=all_geoms, crs=source_crs)
    if target_crs and target_crs != source_crs:
        dxf_gdf = dxf_gdf.to_crs(target_crs)

    return dxf_gdf
