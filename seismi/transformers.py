"""
Transformer models for seismic event prediction.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from torch.utils.data import Dataset, DataLoader


class SeismicEventEncoder(nn.Module):
    """
    Encodes seismic event features (location, depth, time) into a fixed-size embedding.
    """
    def __init__(self, input_dim=5, embedding_dim=64):
        super().__init__()
        self.embedding = nn.Sequential(
            nn.Linear(input_dim, embedding_dim),
            nn.LayerNorm(embedding_dim),
            nn.ReLU(),
            nn.Linear(embedding_dim, embedding_dim),
            nn.LayerNorm(embedding_dim)
        )

    def forward(self, x):
        return self.embedding(x)


class SeismicTransformer(nn.Module):
    """
    Transformer model for predicting future seismic events.
    """
    def __init__(self, input_dim=5, embedding_dim=64, num_heads=4,
                 num_encoder_layers=2, output_dim=5):
        super().__init__()

        self.event_encoder = SeismicEventEncoder(input_dim, embedding_dim)

        # Position encoding
        self.register_buffer("position_ids", torch.arange(100).expand((1, -1)))
        self.position_embedding = nn.Embedding(100, embedding_dim)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embedding_dim,
            nhead=num_heads,
            dim_feedforward=embedding_dim*4,
            dropout=0.1,
            batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer=encoder_layer,
            num_layers=num_encoder_layers
        )

        # Output layers
        self.output_layer = nn.Sequential(
            nn.Linear(embedding_dim, embedding_dim),
            nn.ReLU(),
            nn.Linear(embedding_dim, output_dim)
        )

    def forward(self, x, mask=None):
        # x shape: [batch_size, seq_len, features]
        seq_len = x.size(1)

        # Encode events
        event_embeddings = self.event_encoder(x)

        # Add positional encoding
        positions = self.position_ids[:, :seq_len]
        pos_embeddings = self.position_embedding(positions)

        # Combine event embeddings with positional embeddings
        embeddings = event_embeddings + pos_embeddings

        # Apply transformer encoder
        if mask is not None:
            encoded = self.transformer_encoder(embeddings, src_key_padding_mask=mask)
        else:
            encoded = self.transformer_encoder(embeddings)

        # Generate output predictions (x, y, depth, energy, timestamp)
        output = self.output_layer(encoded)

        return output


class SeismicEventDataset(Dataset):
    """
    Dataset for sequence-to-sequence prediction of seismic events.
    """
    def __init__(self, events_df, seq_length=10, prediction_horizon=1, time_feature='days_elapsed'):
        """
        Initialize dataset.

        Parameters:
        -----------
        events_df : pandas.DataFrame
            DataFrame with seismic events, sorted by time
        seq_length : int
            Number of events to use as input sequence
        prediction_horizon : int
            Number of events to predict into the future
        time_feature : str
            Column name for the time feature (should be numeric)
        """
        self.events = events_df.copy()
        self.seq_length = seq_length
        self.prediction_horizon = prediction_horizon

        # Ensure events are sorted by time
        self.events.sort_values(by=time_feature, inplace=True)

        # Create feature and target arrays (now with days_elapsed as the time feature)
        features = ['X', 'Y', 'depth', time_feature, 'energy']
        self.data = self.events[features].values
        # Log-transform energy before scaling
        self.data[:, 4] = np.log1p(self.data[:, 4])
        self.scaler = StandardScaler()
        self.data_scaled = self.scaler.fit_transform(self.data)

        # Calculate number of valid sequences
        self.num_sequences = len(self.events) - seq_length - prediction_horizon + 1

    def __len__(self):
        return self.num_sequences

    def __getitem__(self, idx):
        """
        Get a sequence of events and the future event to predict.
        """
        # Input sequence
        X = self.data_scaled[idx:idx+self.seq_length]

        # Target: future event features
        y_idx = idx + self.seq_length + self.prediction_horizon - 1
        y = self.data_scaled[y_idx]

        # Extract x, y, depth, days_elapsed, energy for prediction
        y = y[[0, 1, 2, 3, 4]]  # X, Y, depth, days_elapsed, Energie

        return torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)


def prepare_time_features(events_df, reference_time=None):
    """
    Prepare time features for the seismic events.

    Parameters:
    -----------
    events_df : pandas.DataFrame
        DataFrame with seismic events including 'datetime' column
    reference_time : pandas.Timestamp, optional
        Reference time for calculating elapsed time (defaults to min datetime)

    Returns:
    --------
    pandas.DataFrame
        DataFrame with additional time features
    """
    df = events_df.copy()

    # Ensure datetime column exists
    if 'datetime' not in df.columns:
        raise ValueError("DataFrame must contain a 'datetime' column")

    # Sort by time
    df.sort_values('datetime', inplace=True)

    # Set reference time if not provided
    if reference_time is None:
        reference_time = df['datetime'].min()

    # Calculate elapsed time features
    df['seconds_elapsed'] = (df['datetime'] - reference_time).dt.total_seconds()
    df['minutes_elapsed'] = df['seconds_elapsed'] / 60
    df['hours_elapsed'] = df['minutes_elapsed'] / 60
    df['days_elapsed'] = df['hours_elapsed'] / 24

    return df


def train_transformer_model(model, train_loader, val_loader=None, epochs=100,
                           lr=0.001, device=None):
    """
    Train the transformer model.

    Parameters:
    -----------
    model : SeismicTransformer
        The transformer model to train
    train_loader : DataLoader
        DataLoader for the training data
    val_loader : DataLoader, optional
        DataLoader for the validation data
    epochs : int, default 100
        Number of training epochs
    lr : float, default 0.001
        Learning rate
    device : torch.device, optional
        Device to use for training

    Returns:
    --------
    dict
        Dictionary with training history
    """
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()

    history = {
        'train_loss': [],
        'val_loss': [],
    }

    for epoch in range(epochs):
        # Training
        model.train()
        train_loss = 0
        for batch_idx, (data, target) in enumerate(train_loader):
            data, target = data.to(device), target.to(device)

            optimizer.zero_grad()
            # Get predictions for the last element in each sequence
            output = model(data)[:, -1, :]
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()

            train_loss += loss.item()

        train_loss /= len(train_loader)
        history['train_loss'].append(train_loss)

        # Validation
        if val_loader:
            model.eval()
            val_loss = 0
            with torch.no_grad():
                for data, target in val_loader:
                    data, target = data.to(device), target.to(device)
                    output = model(data)[:, -1, :]
                    val_loss += criterion(output, target).item()

            val_loss /= len(val_loader)
            history['val_loss'].append(val_loss)

            print(f"Epoch {epoch+1}/{epochs} - Train Loss: {train_loss:.6f}, Val Loss: {val_loss:.6f}")
        else:
            print(f"Epoch {epoch+1}/{epochs} - Train Loss: {train_loss:.6f}")

    return history


def predict_future_events(model, initial_sequence, n_future=10, scaler=None, device=None):
    """
    Predict future seismic events based on an initial sequence.

    Parameters:
    -----------
    model : SeismicTransformer
        The trained transformer model
    initial_sequence : torch.Tensor
        Initial sequence of events [seq_len, features]
    n_future : int, default 10
        Number of future events to predict
    scaler : StandardScaler, optional
        Scaler used to normalize the data
    device : torch.device, optional
        Device to use for prediction

    Returns:
    --------
    numpy.ndarray
        Predicted future events [n_future, 4] (x, y, depth, energy)
    """
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    model = model.to(device)
    model.eval()

    # Convert to tensor if it's not already
    if not isinstance(initial_sequence, torch.Tensor):
        initial_sequence = torch.tensor(initial_sequence, dtype=torch.float32)

    # Add batch dimension if needed
    if initial_sequence.dim() == 2:
        initial_sequence = initial_sequence.unsqueeze(0)

    initial_sequence = initial_sequence.to(device)
    seq_len = initial_sequence.size(1)

    # Make a copy of the sequence that we'll update with predictions
    current_sequence = initial_sequence.clone()
    predictions = []

    with torch.no_grad():
        for _ in range(n_future):
            # Get prediction for next event
            output = model(current_sequence)[:, -1, :]  # [batch, features]

            # Save the prediction
            predictions.append(output.cpu().numpy()[0])

            # Update the last time value for the next prediction
            # Assuming time is at index 3 and we increment by a constant amount
            # This depends on how time is encoded in your data
            last_time = current_sequence[0, -1, 3]
            time_increment = current_sequence[0, -1, 3] - current_sequence[0, -2, 3]
            next_time = last_time + time_increment

            # Create the next event with predicted values
            next_event = torch.zeros_like(current_sequence[0, 0])
            next_event[0] = output[0, 0]  # X
            next_event[1] = output[0, 1]  # Y
            next_event[2] = output[0, 2]  # depth
            next_event[3] = next_time     # time
            next_event[4] = output[0, 3]  # energy

            # Remove first event and add new event at the end
            current_sequence = torch.cat([
                current_sequence[:, 1:, :],
                next_event.unsqueeze(0).unsqueeze(0)
            ], dim=1)

    # Convert predictions to numpy
    predictions = np.array(predictions)

    # Inverse transform if scaler is provided
    if scaler:
        dummy = np.zeros((len(predictions), scaler.n_features_in_))
        # X, Y, depth, days_elapsed, Energie
        dummy[:, [0, 1, 2, 3, 4]] = predictions  # X, Y, depth, days_elapsed, Energie
        dummy_inverse = scaler.inverse_transform(dummy)
        predictions = dummy_inverse[:, [0, 1, 2, 3, 4]]
        # Apply expm1 to energy (column 4)
        predictions[:, 4] = np.expm1(predictions[:, 4])

    return predictions


def evaluate_predictions(true_events, predicted_events, radius=100):
    """
    Evaluate the quality of seismic event predictions.

    Parameters:
    -----------
    true_events : numpy.ndarray
        True future events [n_events, 4] (x, y, depth, energy)
    predicted_events : numpy.ndarray
        Predicted future events [n_events, 4] (x, y, depth, energy)
    radius : float, default 100
        Spatial radius (meters) for considering a prediction "close"

    Returns:
    --------
    dict
        Dictionary with evaluation metrics
    """
    from scipy.spatial.distance import cdist

    # Calculate spatial distances between true and predicted events
    spatial_dists = cdist(
        true_events[:, :2],     # x, y coordinates of true events
        predicted_events[:, :2]  # x, y coordinates of predicted events
    )

    # Find minimum distance for each true event
    min_dists = np.min(spatial_dists, axis=1)

    # Calculate energy errors
    energy_errors = np.abs(true_events[:, 3] - predicted_events[:, 3])

    # Calculate metrics
    metrics = {
        'mean_spatial_error': np.mean(min_dists),
        'median_spatial_error': np.median(min_dists),
        'mean_energy_error': np.mean(energy_errors),
        'median_energy_error': np.median(energy_errors),
        'spatial_hit_rate': np.mean(min_dists < radius),
    }

    return metrics


def plot_predictions(true_events, predicted_events, base_map=None, figsize=(12, 10)):
    """
    Plot true vs predicted seismic events.

    Parameters:
    -----------
    true_events : numpy.ndarray
        True future events [n_events, 4] (x, y, depth, energy)
    predicted_events : numpy.ndarray
        Predicted future events [n_events, 4] (x, y, depth, energy)
    base_map : geopandas.GeoDataFrame, optional
        Base map to plot events on
    figsize : tuple, default (12, 10)
        Figure size as (width, height) in inches

    Returns:
    --------
    matplotlib.figure.Figure
        The figure object
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, ax = plt.subplots(figsize=figsize)

    # Plot base map if provided
    if base_map is not None:
        base_map.plot(ax=ax, color='lightgray')

    # Plot true events
    scatter1 = ax.scatter(
        true_events[:, 0], true_events[:, 1],
        c=true_events[:, 3], cmap='viridis',
        norm=LogNorm(vmin=max(1, true_events[:, 3].min())),
        s=100, alpha=0.7, edgecolor='black',
        label='True Events'
    )

    # Plot predicted events
    scatter2 = ax.scatter(
        predicted_events[:, 0], predicted_events[:, 1],
        c=predicted_events[:, 3], cmap='plasma',
        norm=LogNorm(vmin=max(1, predicted_events[:, 3].min())),
        s=80, alpha=0.7, marker='s', edgecolor='white',
        label='Predicted Events'
    )

    # Draw lines connecting true and predicted events
    for i in range(min(len(true_events), len(predicted_events))):
        ax.plot(
            [true_events[i, 0], predicted_events[i, 0]],
            [true_events[i, 1], predicted_events[i, 1]],
            'k--', alpha=0.3, linewidth=0.5
        )

    # Add colorbars
    cbar1 = fig.colorbar(scatter1, ax=ax, shrink=0.6, pad=0.01)
    cbar1.set_label('True Energy')

    cbar2 = fig.colorbar(scatter2, ax=ax, shrink=0.6, pad=0.05)
    cbar2.set_label('Predicted Energy')

    ax.set_xlabel('X Coordinate')
    ax.set_ylabel('Y Coordinate')
    ax.set_title('True vs Predicted Seismic Events')
    ax.legend()
    ax.grid(True)

    plt.tight_layout()
    return fig