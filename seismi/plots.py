"""
Visualization functions for seismic and geospatial data.
"""
import matplotlib.pyplot as plt

import numpy as np
from branca.colormap import linear
from ipyleaflet import Map, CircleMarker, Popup
from ipywidgets import HTML


def plot_basic_map(mines_map, seismic_events, thickness=None, figsize=(10, 10)):
    """
    Create a basic matplotlib plot with seismic events overlaid on a mine map.

    Parameters:
    -----------
    mines_map : geopandas.GeoDataFrame
        GeoDataFrame containing mine map geometries
    seismic_events : geopandas.GeoDataFrame
        GeoDataFrame containing seismic event points
    thickness : geopandas.GeoDataFrame, optional
        GeoDataFrame containing thickness lines/polygons
    figsize : tuple, default (10, 10)
        Figure size as (width, height) in inches

    Returns:
    --------
    tuple
        (fig, ax) tuple containing the figure and axes objects
    """
    fig, ax = plt.subplots(figsize=figsize)
    mines_map.plot(ax=ax, color='lightgray')
    seismic_events.plot(ax=ax, color='red', markersize=20)

    if thickness is not None:
        thickness.plot(ax=ax, color='blue', edgecolor='black', alpha=0.7,
                       label='Mocnost meziloží')

    plt.title('Seismic events overlaid on a mine map')
    plt.xlabel('Longitude / X')
    plt.ylabel('Latitude / Y')
    plt.grid(True)

    return fig, ax


def add_seismic_events(m, events, colormap=None, min_radius=4, max_radius=15):
    """
    Add seismic events to an interactive leaflet map with popups.

    Parameters:
    -----------
    m : ipyleaflet.Map
        Map object to add markers to
    events : geopandas.GeoDataFrame
        GeoDataFrame containing seismic events with an energy attribute
    colormap : branca.colormap.LinearColormap, optional
        Colormap to use for markers (will be created if None)
    min_radius : int, default 4
        Minimum radius for markers
    max_radius : int, default 15
        Maximum radius for markers

    Returns:
    --------
    list
        List of added markers
    """
    # Create log energy values for scaling
    log_energy = np.log10(events.energy.replace(0, np.nan)).dropna()
    min_log_e, max_log_e = log_energy.min(), log_energy.max()

    # Create colormap if not provided
    if colormap is None:
        colormap = linear.YlOrRd_09.scale(min_log_e, max_log_e)

    # Create scaling function for radius
    scaled_radius = lambda log_e: int(
        np.interp(log_e, [min_log_e, max_log_e], [min_radius, max_radius])
    )

    markers = []
    for _, row in events.iterrows():
        point = row.geometry
        log_e = np.log10(row.energy)

        popup = Popup(
            location=(point.y, point.x),
            child=HTML(f'{row.datetime} / E = {row.energy}'),
        )

        marker = CircleMarker(
            location=(point.y, point.x),  # Leaflet uses (lat, lon)
            radius=scaled_radius(log_e),
            color=colormap(log_e),
            fill_color=colormap(log_e),
            fill_opacity=0.7,
            stroke=False,
            popup=popup,
        )

        m.add_layer(marker)
        markers.append(marker)

    return markers


def add_gdf(m, gdf, basecolormap, val_attr, radius=4):
    """
    Add points from a GeoDataFrame to an interactive leaflet map.

    Parameters:
    -----------
    m : ipyleaflet.Map
        Map object to add markers to
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing point geometries
    basecolormap : branca.colormap
        Base colormap to use for markers
    val_attr : str
        Column name of the attribute to use for coloring
    radius : int, default 4
        Radius for markers

    Returns:
    --------
    list
        List of added markers
    """
    colormap = basecolormap.scale(gdf[val_attr].min(), gdf[val_attr].max())

    markers = []
    for _, row in gdf.iterrows():
        point = row.geometry
        val = row[val_attr]

        popup = Popup(
            location=(point.y, point.x),
            child=HTML(f'{val}'),
        )

        marker = CircleMarker(
            location=(point.y, point.x),
            radius=radius,
            color=colormap(val),
            fill_color=colormap(val),
            fill_opacity=0.7,
            stroke=False,
            popup=popup,
        )

        m.add_layer(marker)
        markers.append(marker)

    return markers


def create_interactive_map(seismic_events, depths=None, depths_interpolated=None,
                          sample_events=200, sample_interpolated=1000):
    """
    Create an interactive leaflet map with seismic events and optional depth data.

    Parameters:
    -----------
    seismic_events : geopandas.GeoDataFrame
        GeoDataFrame containing seismic events
    depths : geopandas.GeoDataFrame, optional
        GeoDataFrame containing measured depth points
    depths_interpolated : geopandas.GeoDataFrame, optional
        GeoDataFrame containing interpolated depth grid
    sample_events : int, default 200
        Number of events to sample (to avoid overcrowding)
    sample_interpolated : int, default 1000
        Number of interpolated points to sample

    Returns:
    --------
    ipyleaflet.Map
        Interactive map with added layers
    """
    center = [seismic_events.geometry.y.mean(), seismic_events.geometry.x.mean()]
    m = Map(center=center, zoom=14)

    if sample_events:
        seismic_events = seismic_events.sample(min(sample_events, len(seismic_events)))
    if depths_interpolated is not None and sample_interpolated:
        depths_interpolated = depths_interpolated.sample(
            min(sample_interpolated, len(depths_interpolated))
        )

    if depths_interpolated is not None:
        add_gdf(m, depths_interpolated, linear.Accent_07, 'depth')
    if depths is not None:
        add_gdf(m, depths, linear.Blues_04, 'depth')

    add_seismic_events(m, seismic_events)

    return m


def plot_model_results(y_test, preds, X_test=None, figsize=(12, 8)):
    """
    Create plots to visualize model prediction results.

    Parameters:
    -----------
    y_test : numpy.ndarray
        True target values
    preds : numpy.ndarray
        Predicted target values
    X_test : numpy.ndarray, optional
        Test features (for spatial residual plot)
    figsize : tuple, default (12, 8)
        Base figure size

    Returns:
    --------
    tuple
        Tuple of figure objects
    """
    figures = []

    # True vs Predicted plot
    fig1 = plt.figure(figsize=(figsize[0]//2, figsize[1]//2))
    plt.scatter(y_test, preds, alpha=0.5)
    plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 'r--')  # Ideal line
    plt.xlabel('True Energy')
    plt.ylabel('Predicted Energy')
    plt.title('True vs. Predicted Seismic Energy')
    plt.grid(True)
    figures.append(fig1)

    # Calculate residuals
    residuals = preds - y_test

    # Residual plot
    fig2 = plt.figure(figsize=(figsize[0]//2, figsize[1]//2))
    plt.scatter(y_test, residuals, alpha=0.5)
    plt.axhline(0, color='red', linestyle='--')
    plt.xlabel('True Energy')
    plt.ylabel('Residual (Predicted - True)')
    plt.title('Residuals')
    plt.grid(True)
    figures.append(fig2)

    # Spatial residual plot (only if X_test provided with coordinates)
    if X_test is not None and X_test.shape[1] >= 2:
        fig3 = plt.figure(figsize=(figsize[0]//2, figsize[1]//2))
        plt.scatter(X_test[:, 0], X_test[:, 1], c=residuals, cmap='coolwarm', s=40)
        plt.colorbar(label='Residual (Predicted - True)')
        plt.xlabel('X')
        plt.ylabel('Y')
        plt.title('Spatial Distribution of Prediction Residuals')
        figures.append(fig3)

    return tuple(figures)


def create_interactive_prediction_map(X_test, y_test, preds, scaler=None):
    """
    Create an interactive map visualizing model predictions and residuals.

    Parameters:
    -----------
    X_test : numpy.ndarray
        Test features (must include X, Y coordinates)
    y_test : numpy.ndarray
        True target values
    preds : numpy.ndarray
        Predicted target values
    scaler : sklearn.preprocessing.StandardScaler, optional
        Scaler used to normalize features

    Returns:
    --------
    ipyleaflet.Map
        Interactive map with prediction results
    """
    residuals = preds - y_test

    # Unscale coordinates if scaler is provided
    if scaler:
        X_unscaled = scaler.inverse_transform(X_test)
    else:
        X_unscaled = X_test

    center = [np.mean(X_unscaled[:, 1]), np.mean(X_unscaled[:, 0])]
    m = Map(center=center, zoom=13)

    # Add markers for each prediction
    for i in range(len(X_unscaled)):
        x, y, _depth = X_unscaled[i]
        true = y_test[i]
        pred = preds[i]
        residual = residuals[i]

        popup = Popup(
            location=(y, x),
            child=HTML(f"True: {true:.2f}<br>Pred: {pred:.2f}<br>Residual: {residual:.2f}"),
            close_button=False,
            auto_close=False,
            close_on_escape_key=False,
        )

        marker = CircleMarker(
            location=(y, x),
            radius=6,
            color='red' if residual > 0 else 'blue',
            fill_color='red' if residual > 0 else 'blue',
            fill_opacity=0.6,
            popup=popup,
        )
        m.add_layer(marker)

    return m
