"""
Functions for loading and processing Excel (XLS/XLSX) files containing spatial data.
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

def df_to_gdf(df, x_col='X', y_col='Y', source_crs='EPSG:5514', target_crs='EPSG:4326'):
    """
    Convert a pandas DataFrame with coordinate columns to a GeoDataFrame.

    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame containing coordinate columns
    x_col : str, default 'X'
        Column name for X coordinates
    y_col : str, default 'Y'
        Column name for Y coordinates
    source_crs : str, default 'EPSG:5514'
        Source coordinate reference system
    target_crs : str, default 'EPSG:4326'
        Target coordinate reference system

    Returns:
    --------
    geopandas.GeoDataFrame
        GeoDataFrame with Point geometries
    """
    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df[x_col], df[y_col])],
        crs=source_crs,
    )
    if target_crs and target_crs != source_crs:
        gdf = gdf.to_crs(target_crs)

    # Overwrite X and Y with longitude and latitude in degrees
    gdf[x_col] = gdf.geometry.x
    gdf[y_col] = gdf.geometry.y

    return gdf


def read_seismic_events(filename='seismic_events.xlsx'):
    """
    Read seismic event data from an Excel file and convert to GeoDataFrame.

    Parameters:
    -----------
    filename : str, default 'seismic_events.xlsx'
        Path to the Excel file containing seismic event data

    Returns:
    --------
    geopandas.GeoDataFrame
        GeoDataFrame containing seismic event data with geometries
    """
    df = pd.read_excel(filename)
    df.rename(columns={'!-X': 'Y', '!-Y': 'X'}, inplace=True)

    # Standardize column names
    df.rename(columns={'Energie': 'energy', 'Datetime': 'datetime'}, inplace=True)

    numeric_cols = ['Magn', 'energy']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['datetime'] = pd.to_datetime(
        df['Datum'].astype(str) + ' ' + df['hh:mm:ss.sss'],
        format='mixed',
        dayfirst=True,
    )

    # Clean column names
    df.columns = df.columns.str.strip()

    return df_to_gdf(df)


def read_measured_points(filename):
    """
    Read measured depth points from an Excel file and convert to GeoDataFrame.

    Parameters:
    -----------
    filename : str
        Path to the Excel file containing measured depth points

    Returns:
    --------
    geopandas.GeoDataFrame
        GeoDataFrame containing measured depth points with geometries
    """
    df = pd.read_excel(filename)
    df.rename(columns={'x-coord': 'X', 'y-coord': 'Y', df.columns[3]: 'depth'}, inplace=True)
    return df_to_gdf(df)


def read_interpolated(filename):
    """
    Read interpolated depth grid from an Excel file and convert to GeoDataFrame.

    Parameters:
    -----------
    filename : str
        Path to the Excel file containing interpolated depth grid

    Returns:
    --------
    geopandas.GeoDataFrame
        GeoDataFrame containing interpolated depth grid with geometries
    """
    df = pd.read_excel(filename)
    df.rename(columns={df.columns[2]: 'depth'}, inplace=True)
    return df_to_gdf(df)
