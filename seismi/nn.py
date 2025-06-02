"""
Neural network models and utilities for seismic energy prediction.
"""
import numpy as np
import torch
import torch.nn as nn
from scipy.interpolate import griddata
from scipy.spatial import KDTree
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


class SpatialMSELoss(nn.Module):
    def __init__(self, coords, targets, n_neighbors=5, alpha=2):
        super().__init__()
        self.coords = coords[:, :2]
        self.targets = targets
        self.kdtree = KDTree(self.coords)
        self.n_neighbors = n_neighbors
        self.alpha = alpha

    def forward(self, pred, targets, batch_indices):
        pred_np = pred.view(-1)
        batch_indices = torch.as_tensor(batch_indices, device=pred.device)
        batch_coords = torch.tensor(self.coords[batch_indices], device=pred.device, dtype=pred.dtype)
        loss = 0.0
        for i, point in enumerate(batch_coords):
            dists, idxs = self.kdtree.query(point.cpu().numpy().reshape(1, -1), k=self.n_neighbors + 1)
            dists, idxs = dists[0, 1:], idxs[0, 1:]
            if len(idxs) == 0:
                loss += 1e6
                continue
            weights = 1.0 / (dists ** self.alpha + 1e-6)
            weights /= weights.sum()
            neighbor_avg = torch.tensor(np.sum(weights * self.targets[idxs]), device=pred.device, dtype=pred.dtype)
            loss += (pred_np[i] - neighbor_avg) ** 2
        return loss / len(batch_indices)


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
        y = np.log1p(seismic_events['energy'].values)
    else:
        y = seismic_events['energy'].values

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


def train_model(
    model,
    data_loader,
    criterion,
    epochs=400,
    lr=0.01,
    print_every=100,
):
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    losses = []
    for epoch in range(epochs):
        model.train()
        epoch_loss = 0
        batch_count = 0
        for batch in data_loader:
            optimizer.zero_grad()
            if len(batch) == 3:
                features, targets, batch_indices = batch
                loss = criterion(model(features), targets, batch_indices)
            else:
                features, targets = batch
                loss = criterion(model(features), targets)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            batch_count += 1
        avg_loss = epoch_loss / batch_count
        losses.append(avg_loss)
        if epoch % print_every == 0:
            print(f'Epoch {epoch}, Loss: {avg_loss:.4f}')
    return losses


def compute_spatial_metrics(preds, y_true, coords, n_neighbors=5, max_distance=None, alpha=2):
    kdtree = KDTree(coords[:, :2])
    dists, idxs = kdtree.query(coords[:, :2], k=n_neighbors+1)
    dists, idxs = dists[:, 1:], idxs[:, 1:]
    spatial_mse = 0.0
    local_error_pattern = np.zeros(len(preds))
    for i in range(len(preds)):
        ni, nd = idxs[i], dists[i]
        if max_distance is not None:
            mask = nd <= max_distance
            ni, nd = ni[mask], nd[mask]
        if len(ni) == 0:
            continue
        w = 1.0 / (nd ** alpha + 1e-6)
        w /= w.sum()
        neighbor_avg = np.sum(w * y_true[ni])
        spatial_mse += (preds[i] - neighbor_avg) ** 2
        local_error_pattern[i] = np.abs(preds[i] - y_true[i]) - np.mean(np.abs(preds[ni] - y_true[ni]))
    spatial_mse /= np.count_nonzero([len(idxs[i]) > 0 for i in range(len(preds))])
    return dict(
        spatial_mse=spatial_mse,
        local_error_pattern=local_error_pattern,
        neighbor_indices=idxs,
        neighbor_distances=dists
    )


def evaluate_model(
    model,
    X_tensor,
    y_true,
    coords=None,
    log_transform=True,
    spatial_metrics=False,
    n_neighbors=5,
    max_distance=None,
    alpha=2,
):
    model.eval()
    with torch.no_grad():
        preds_log = model(X_tensor).cpu().numpy().flatten()
        preds = np.expm1(preds_log) if log_transform else preds_log
        mse = ((preds - y_true) ** 2).mean()
        mae = np.abs(preds - y_true).mean()
        results = dict(predictions=preds, true_values=y_true, standard_mse=mse, standard_mae=mae)
        if spatial_metrics and coords is not None:
            spatial = compute_spatial_metrics(
                preds, y_true, coords, n_neighbors, max_distance, alpha
            )
            results.update(spatial)
        return results


class IndexedDataset(torch.utils.data.Dataset):
    def __init__(self, features, targets):
        self.features = features
        self.targets = targets
    def __len__(self):
        return len(self.features)
    def __getitem__(self, idx):
        return self.features[idx], self.targets[idx], idx
