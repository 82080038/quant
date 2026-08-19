"""Train DL models (VAE, LSTM, XGBoost+LightGBM) on IDX ticker data.

Prepares feature matrices from stock_prices, generates TBL labels,
trains all three models, and saves them to models/ directory.

Usage:
    python scripts/train_dl_models.py [--tickers BBCA.JK,BBRI.JK] [--limit 50]
"""

import argparse
import json
import logging
import os
import pickle
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db
from quant.signals.vae import VAEFeatureExtractor, VAEConfig
from quant.signals.lstm import LSTMSignalPredictor, LSTMConfig
from quant.signals.xgb_lgbm import XGBLGBMEnsemble, XGBLGBMConfig
from quant.signals.tbl import apply_triple_barrier, TBLConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical features from OHLCV data."""
    df = df.copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    # Returns
    df["ret_1d"] = close.pct_change(1)
    df["ret_3d"] = close.pct_change(3)
    df["ret_5d"] = close.pct_change(5)
    df["ret_10d"] = close.pct_change(10)

    # Moving averages
    df["sma_5"] = close.rolling(5).mean()
    df["sma_10"] = close.rolling(10).mean()
    df["sma_20"] = close.rolling(20).mean()
    df["sma_50"] = close.rolling(50).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-8)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # MACD
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # Bollinger Bands
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (bb_mid + 1e-8)

    # Volatility
    df["vol_5d"] = df["ret_1d"].rolling(5).std()
    df["vol_10d"] = df["ret_1d"].rolling(10).std()
    df["vol_20d"] = df["ret_1d"].rolling(20).std()

    # Volume features
    df["vol_sma_5"] = volume.rolling(5).mean()
    df["vol_ratio"] = volume / (df["vol_sma_5"] + 1e-8)

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / (close + 1e-8)

    # Momentum
    df["momentum_5"] = close / close.shift(5) - 1
    df["momentum_10"] = close / close.shift(10) - 1
    df["momentum_20"] = close / close.shift(20) - 1

    # Stochastic
    df["stoch_k"] = (close - low.rolling(14).min()) / (high.rolling(14).max() - low.rolling(14).min() + 1e-8) * 100
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    return df


def get_feature_columns() -> list[str]:
    """Return the list of feature column names."""
    return [
        "ret_1d", "ret_3d", "ret_5d", "ret_10d",
        "sma_5", "sma_10", "sma_20", "sma_50",
        "rsi_14", "macd", "macd_signal",
        "bb_upper", "bb_lower", "bb_width",
        "vol_5d", "vol_10d", "vol_20d",
        "vol_sma_5", "vol_ratio",
        "atr_14", "atr_pct",
        "momentum_5", "momentum_10", "momentum_20",
        "stoch_k", "stoch_d",
    ]


def load_ticker_data(session, ticker: str, end_date: date, lookback_days: int = 500) -> pd.DataFrame:
    """Load OHLCV data for a ticker."""
    start_date = end_date - timedelta(days=lookback_days)
    result = session.execute(text(
        "SELECT date, open, high, low, close, volume "
        "FROM stock_prices WHERE ticker = :ticker AND date BETWEEN :start AND :end "
        "ORDER BY date"
    ), {"ticker": ticker, "start": start_date, "end": end_date})
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    # Convert Decimal to float
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].apply(lambda x: float(x) if x is not None else 0.0)
    return df


def prepare_training_data(session, tickers: list[str], end_date: date) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Prepare feature matrix and TBL labels for all tickers."""
    all_features = []
    all_labels = []
    all_tickers = []
    feature_cols = get_feature_columns()

    for ticker in tickers:
        df = load_ticker_data(session, ticker, end_date)
        if len(df) < 60:
            continue

        df = compute_features(df)
        df = df.dropna()
        if len(df) < 30:
            continue

        # Generate TBL labels
        tbl_config = TBLConfig(use_atr=True)
        tbl_result = apply_triple_barrier(df.set_index("date")["close"], tbl_config)

        # Align features with labels
        feature_df = df[feature_cols].reset_index(drop=True)
        labels = tbl_result["label"].values if "label" in tbl_result.columns else tbl_result.iloc[:, 0].values

        # Trim to matching length
        min_len = min(len(feature_df), len(labels))
        feature_df = feature_df.iloc[:min_len]
        labels = labels[:min_len]

        # Replace inf/nan
        feature_df = feature_df.replace([np.inf, -np.inf], np.nan).fillna(0)

        all_features.append(feature_df.values)
        all_labels.extend(labels)
        all_tickers.extend([ticker] * min_len)

    if not all_features:
        return np.array([]), np.array([]), []

    X = np.vstack(all_features)
    y = np.array(all_labels)

    logger.info("Training data: X=%s, y=%s, tickers=%d", X.shape, y.shape, len(set(all_tickers)))
    return X, y, all_tickers


def train_vae(X: np.ndarray, device: str = "cuda:1") -> VAEFeatureExtractor:
    """Train VAE feature extractor."""
    logger.info("Training VAE on %s...", device)
    config = VAEConfig(
        input_dim=X.shape[1],
        hidden_dim=64,
        latent_dim=16,
        n_epochs=50,
        batch_size=64,
        learning_rate=1e-3,
    )
    extractor = VAEFeatureExtractor(config=config, device=device)
    extractor.fit(X, verbose=True)
    logger.info("VAE training complete. Latent dim: %d", config.latent_dim)
    return extractor


def train_lstm(X: np.ndarray, y: np.ndarray, device: str = "cuda:1") -> LSTMSignalPredictor:
    """Train LSTM predictor."""
    logger.info("Training LSTM on %s...", device)
    config = LSTMConfig(
        input_dim=X.shape[1],
        hidden_dim=64,
        n_layers=2,
        seq_len=20,
        n_epochs=50,
        batch_size=32,
        learning_rate=1e-3,
    )
    predictor = LSTMSignalPredictor(config=config, device=device)
    predictor.fit(X, y, verbose=True)
    logger.info("LSTM training complete")
    return predictor


def train_xgb_lgbm(X: np.ndarray, y: np.ndarray) -> XGBLGBMEnsemble:
    """Train XGBoost + LightGBM ensemble."""
    logger.info("Training XGBoost + LightGBM ensemble...")
    config = XGBLGBMConfig(
        xgb_n_estimators=200,
        lgbm_n_estimators=200,
        use_shap_selection=True,
        shap_top_k=min(20, X.shape[1]),
    )
    ensemble = XGBLGBMEnsemble(config=config)
    ensemble.fit(X, y, verbose=True)
    logger.info("XGBoost + LightGBM training complete")
    return ensemble


def main():
    parser = argparse.ArgumentParser(description="Train DL models on IDX data")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    parser.add_argument("--limit", type=int, default=50, help="Max tickers to use")
    parser.add_argument("--vae-device", type=str, default="cuda:1")
    parser.add_argument("--lstm-device", type=str, default="cuda:1")
    args = parser.parse_args()

    MODELS_DIR.mkdir(exist_ok=True)

    session = get_db()

    # Get tickers
    if args.tickers:
        tickers = args.tickers.split(",")
    else:
        # Get tickers from stock_prices that have sufficient data
        result = session.execute(text(
            "SELECT ticker, count(*) as cnt FROM stock_prices "
            "WHERE ticker LIKE '%%.JK' AND ticker NOT LIKE 'IDX%%' "
            "GROUP BY ticker HAVING count(*) >= 200 "
            "ORDER BY cnt DESC LIMIT :limit"
        ), {"limit": args.limit})
        tickers = [r[0] for r in result.fetchall()]

    logger.info("Using %d tickers: %s", len(tickers), tickers[:10])

    end_date = date(2026, 8, 18)
    X, y, ticker_list = prepare_training_data(session, tickers, end_date)

    if len(X) == 0:
        logger.error("No training data available")
        session.close()
        sys.exit(1)

    # Split: 80% train, 20% test
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    logger.info("Train: %d samples, Test: %d samples", len(X_train), len(X_test))

    # Train all models
    results = {}

    # VAE
    try:
        vae = train_vae(X_train, device=args.vae_device)
        vae_path = MODELS_DIR / "vae_extractor.pkl"
        with open(vae_path, "wb") as f:
            pickle.dump({"mean": vae.mean, "std": vae.std, "config": vae.config}, f)
        # Save model state dict
        torch_path = MODELS_DIR / "vae_model.pt"
        import torch
        torch.save(vae.model.state_dict(), torch_path)
        results["vae"] = {"status": "trained", "path": str(vae_path)}
        logger.info("VAE saved to %s", vae_path)
    except Exception as e:
        logger.error("VAE training failed: %s", e)
        results["vae"] = {"status": "failed", "error": str(e)}

    # LSTM
    try:
        lstm = train_lstm(X_train, y_train, device=args.lstm_device)
        lstm_path = MODELS_DIR / "lstm_predictor.pkl"
        with open(lstm_path, "wb") as f:
            pickle.dump({"mean": lstm.mean, "std": lstm.std, "config": lstm.config}, f)
        torch_path = MODELS_DIR / "lstm_model.pt"
        import torch
        torch.save(lstm.model.state_dict(), torch_path)
        # Evaluate
        test_pred = lstm.predict(X_test)
        # LSTM predict returns (n - seq_len) predictions due to sequence windowing
        n_pred = len(test_pred)
        test_mse = np.mean((test_pred - y_test[-n_pred:]) ** 2)
        results["lstm"] = {"status": "trained", "path": str(lstm_path), "test_mse": float(test_mse)}
        logger.info("LSTM saved to %s, test MSE: %.6f", lstm_path, test_mse)
    except Exception as e:
        logger.error("LSTM training failed: %s", e)
        results["lstm"] = {"status": "failed", "error": str(e)}

    # XGBoost + LightGBM
    try:
        ensemble = train_xgb_lgbm(X_train, y_train)
        ensemble_path = MODELS_DIR / "xgb_lgbm_ensemble.pkl"
        with open(ensemble_path, "wb") as f:
            pickle.dump(ensemble, f)
        # Evaluate
        test_pred = ensemble.predict_signal(X_test)
        test_mse = np.mean((test_pred - y_test) ** 2)
        results["xgb_lgbm"] = {"status": "trained", "path": str(ensemble_path), "test_mse": float(test_mse)}
        logger.info("XGBoost+LightGBM saved to %s, test MSE: %.6f", ensemble_path, test_mse)
    except Exception as e:
        logger.error("XGBoost+LightGBM training failed: %s", e)
        results["xgb_lgbm"] = {"status": "failed", "error": str(e)}

    # Save training report
    report_path = MODELS_DIR / "training_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "date": str(date.today()),
            "n_tickers": len(set(ticker_list)),
            "n_samples": len(X),
            "n_features": X.shape[1],
            "train_size": len(X_train),
            "test_size": len(X_test),
            "results": results,
        }, f, indent=2)

    print("\n" + "=" * 60)
    print("TRAINING SUMMARY")
    print("=" * 60)
    print(json.dumps(results, indent=2))
    print(f"\nModels saved to: {MODELS_DIR}")

    session.close()


if __name__ == "__main__":
    import torch  # noqa: E402
    main()
