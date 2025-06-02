# Seismicity in Mines

Goal: predict (next) seismicity events using AI methods.

Using Copilot/ChatGPT a lot to speed up development.

Copilot's description follows:

## Project Overview

This project aims to analyze and predict seismic events in mining environments using modern machine learning and deep learning techniques. The workflow includes data preprocessing, feature engineering, model training, evaluation, and visualization.

## Features

- **Data Loading & Preprocessing:**
  Utilities for reading seismic event data and geospatial information from Excel and shapefiles, converting them to GeoDataFrames, and interpolating missing values.

- **Neural Network Models:**
  - Simple and deep feedforward neural networks for regression.
  - Transformer-based models for sequence prediction of seismic events.
  - Custom spatial loss functions to account for spatial dependencies.

- **Visualization:**
  - Static and interactive maps of seismic events overlaid on mine maps.
  - Interactive residual and prediction maps using ipyleaflet.
  - Training and evaluation plots.

- **Notebooks:**
  - `maps.ipynb`: End-to-end workflow for data loading, model training, evaluation, and visualization.
  - `transformers.ipynb`: Experiments with transformer models for sequential seismic event prediction.

## Current State

- Data pipelines and preprocessing scripts are functional and robust to various input formats.
- Both classic neural networks and transformer models are implemented and tested.
- Interactive and static visualizations are available for both data exploration and model results.
- The codebase is being actively refactored for consistency (e.g., standardizing column names like `energy` and `datetime`).
- Most experiments and workflows are run and documented in Jupyter notebooks.
- The project is under active development, with frequent use of AI coding assistants for rapid prototyping and refactoring.

## Requirements

- Python 3.10+
- See `requirements.txt` for dependencies (PyTorch, scikit-learn, geopandas, ipyleaflet, etc.)

## Usage

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the notebooks (`maps.ipynb`, `transformers.ipynb`) for end-to-end examples.

## Directory Structure

- `seismi/`: Core Python modules for data loading, modeling, and plotting.
- `maps.ipynb`, `transformers.ipynb`: Main Jupyter notebooks for experiments.
- Data files: Excel and shapefiles for seismic events and mine maps.

## TODO / Roadmap

- Further improve model performance and generalization.
- Add more advanced spatial/temporal models.
- Clean up and document all modules.
- Add more tests and validation.
- Prepare for publication or deployment.
