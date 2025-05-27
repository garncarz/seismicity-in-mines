"""
Neural network models and utilities for seismic energy prediction.
"""
import numpy as np
import torch
import torch.nn as nn
from scipy.interpolate import griddata
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


class SimpleNN(nn.Module):
    """
    A simple neural network for seismic energy prediction.

    Architecture:
    - Input layer: 3 features (x, y, depth)
    - Hidden layer 1: 32 units with ReLU activation
    - Hidden layer 2: 16 units with ReLU activation
    - Output layer: 1 unit (energy prediction)
    """
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        """Forward pass through the network."""
        return self.net(x)


class BiggerNN(nn.Module):
    """
    A larger neural network for seismic energy prediction.

    Architecture:
    - Input layer: 3 features (x, y, depth)
    - Hidden layer 1: 64 units with ReLU activation
    - Hidden layer 2: 64 units with ReLU activation
    - Hidden layer 3: 32 units with ReLU activation
    - Output layer: 1 unit (energy prediction)
    """
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )
    def forward(self, x):
        """Forward pass through the network."""
        return self.net(x)


def prepare_data(seismic_events, depths_interpolated, log_transform=True, test_size=0.2, random_state=42):
    """
    Prepare data for neural network training by interpolating depths and creating features.

    Parameters:
    -----------
    seismic_events : geopandas.GeoDataFrame
        GeoDataFrame containing seismic events with geometries and 'Energie' column
    depths_interpolated : geopandas.GeoDataFrame
        GeoDataFrame containing interpolated depth grid with geometries and 'depth' column
    log_transform : bool, default True
        Whether to apply log transformation to the target energy values
    test_size : float, default 0.2
        Fraction of data to use for testing
    random_state : int, default 42
        Random seed for reproducibility

    Returns:
    --------
    tuple
        (X_train, X_test, y_train, y_test, X_train_tensor, y_train_tensor,
         X_test_tensor, y_test_tensor, scaler)
    """
    # Get coordinates and depth from depths_interpolated
    depth_points = np.array(list(zip(depths_interpolated.geometry.x, depths_interpolated.geometry.y)))
    depth_values = depths_interpolated['depth'].values

    # Get seismic event coordinates
    event_points = np.array(list(zip(seismic_events.geometry.x, seismic_events.geometry.y)))

    # Interpolate depth at each seismic event location
    event_depths = griddata(depth_points, depth_values, event_points, method='linear')

    # Prepare features and targets
    X = np.column_stack([event_points, event_depths])  # Features: x, y, depth

    # Apply log transform to energy values if requested
    if log_transform:
        y = np.log1p(seismic_events['Energie'].values)
    else:
        y = seismic_events['Energie'].values

    # Remove events where depth could not be interpolated
    mask = ~np.isnan(X[:, 2])
    X = X[mask]
    y = y[mask]

    # Normalize features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Split into train/test
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=test_size, random_state=random_state
    )

    # Convert to torch tensors
    X_train_tensor = torch.tensor(X_train, dtype=torch.float32)
    y_train_tensor = torch.tensor(y_train, dtype=torch.float32).view(-1, 1)
    X_test_tensor = torch.tensor(X_test, dtype=torch.float32)
    y_test_tensor = torch.tensor(y_test, dtype=torch.float32).view(-1, 1)

    return (
        X_train, X_test, y_train, y_test,
        X_train_tensor, y_train_tensor, X_test_tensor, y_test_tensor,
        scaler,
    )


def train_model(model, X_train_tensor, y_train_tensor, epochs=400, lr=0.01):
    """
    Train a neural network model.

    Parameters:
    -----------
    model : torch.nn.Module
        Neural network model to train
    X_train_tensor : torch.Tensor
        Training features as tensor
    y_train_tensor : torch.Tensor
        Training targets as tensor
    epochs : int, default 400
        Number of epochs to train for
    lr : float, default 0.01
        Learning rate for optimizer

    Returns:
    --------
    tuple
        (trained model, list of losses)
    """
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    losses = []
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        outputs = model(X_train_tensor)
        loss = criterion(outputs, y_train_tensor)
        loss.backward()
        optimizer.step()
        losses.append(loss.item())
        if epoch % 200 == 0:
            print(f"Epoch {epoch}, Loss: {loss.item():.4f}")

    return model, losses


def evaluate_model(model, X_test_tensor, y_test, log_transform=True):
    """
    Evaluate a trained model on test data.

    Parameters:
    -----------
    model : torch.nn.Module
        Trained neural network model
    X_test_tensor : torch.Tensor
        Test features as tensor
    y_test : numpy.ndarray
        True target values
    log_transform : bool, default True
        Whether the target was log-transformed during training

    Returns:
    --------
    tuple
        (predictions, MSE)
    """
    model.eval()
    with torch.no_grad():
        preds_log = model(X_test_tensor).numpy().flatten()

        if log_transform:
            # Transform back from log scale
            preds = np.expm1(preds_log)
        else:
            preds = preds_log

        mse = ((preds - y_test) ** 2).mean()
        print(f"Test MSE: {mse:.4f}")

    return preds, mse
