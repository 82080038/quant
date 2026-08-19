"""XGBoost + LightGBM ensemble with SHAP feature selection.

Dual gradient boosting ensemble for tabular feature prediction.
SHAP-based top-60 feature selection for dimensionality reduction.

Architecture:
  1. Train XGBoost and LightGBM independently on feature matrix
  2. Compute SHAP values from XGBoost for feature importance
  3. Select top-60 features by mean |SHAP|
  4. Retrain both models on selected features
  5. Ensemble prediction = weighted average of both models

Output: signal [-1, +1] or probability [0, 1]
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class XGBLGBMConfig:
    """XGBoost + LightGBM ensemble configuration."""
    # XGBoost params
    xgb_n_estimators: int = 200
    xgb_max_depth: int = 5
    xgb_learning_rate: float = 0.05
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8

    # LightGBM params
    lgbm_n_estimators: int = 200
    lgbm_max_depth: int = 5
    lgbm_learning_rate: float = 0.05
    lgbm_subsample: float = 0.8
    lgbm_colsample_bytree: float = 0.8
    lgbm_num_leaves: int = 31

    # Ensemble
    xgb_weight: float = 0.5
    lgbm_weight: float = 0.5

    # SHAP feature selection
    shap_top_k: int = 60
    use_shap_selection: bool = True

    # Regularization
    early_stopping_rounds: int = 20
    random_state: int = 42


class XGBLGBMEnsemble:
    """Dual gradient boosting ensemble with SHAP feature selection.

    Usage:
        ensemble = XGBLGBMEnsemble()
        ensemble.fit(X_train, y_train)
        signal = ensemble.predict_signal(X_test[-1:])
    """

    def __init__(self, config: XGBLGBMConfig = None):
        self.config = config or XGBLGBMConfig()
        self.xgb_model = None
        self.lgbm_model = None
        self.selected_features: list[str] | None = None
        self.is_fitted = False
        self._feature_names: list[str] | None = None

    def fit(
        self,
        features: np.ndarray | pd.DataFrame,
        labels: np.ndarray,
        val_features: np.ndarray | pd.DataFrame | None = None,
        val_labels: np.ndarray | None = None,
        verbose: bool = False,
    ) -> "XGBLGBMEnsemble":
        """Train XGBoost and LightGBM ensemble.

        Args:
            features: Training features (n_samples, n_features)
            labels: Training labels [-1, 1] or [0, 1]
            val_features: Optional validation set for early stopping
            val_labels: Optional validation labels
            verbose: Print training progress

        Returns:
            self
        """
        if isinstance(features, pd.DataFrame):
            self._feature_names = list(features.columns)
            features = features.values
        if isinstance(val_features, pd.DataFrame):
            val_features = val_features.values

        # ── Phase 1: Train XGBoost on all features for SHAP ───────
        self._fit_xgb(features, labels, val_features, val_labels, verbose)

        # ── SHAP feature selection ─────────────────────────────────
        if self.config.use_shap_selection and features.shape[1] > self.config.shap_top_k:
            self._select_features_shap(features, labels, verbose)
            features = features[:, self._selected_indices]
            if val_features is not None:
                val_features = val_features[:, self._selected_indices]
        else:
            self._selected_indices = slice(None)

        # ── Phase 2: Retrain both models on selected features ──────
        self._fit_xgb(features, labels, val_features, val_labels, verbose)
        self._fit_lgbm(features, labels, val_features, val_labels, verbose)

        self.is_fitted = True
        return self

    def _fit_xgb(self, features, labels, val_features, val_labels, verbose):
        """Train XGBoost model."""
        try:
            import xgboost as xgb
        except ImportError:
            if verbose:
                print("  XGBoost not available, skipping")
            return

        self.xgb_model = xgb.XGBRegressor(
            n_estimators=self.config.xgb_n_estimators,
            max_depth=self.config.xgb_max_depth,
            learning_rate=self.config.xgb_learning_rate,
            subsample=self.config.xgb_subsample,
            colsample_bytree=self.config.xgb_colsample_bytree,
            random_state=self.config.random_state,
            n_jobs=-1,
        )

        fit_kwargs = {}
        if val_features is not None and val_labels is not None:
            fit_kwargs["eval_set"] = [(val_features, val_labels)]
            fit_kwargs["verbose"] = False

        self.xgb_model.fit(features, labels, **fit_kwargs)

        if verbose:
            print(f"  XGBoost trained: {self.xgb_model.n_estimators} trees")

    def _fit_lgbm(self, features, labels, val_features, val_labels, verbose):
        """Train LightGBM model."""
        try:
            import lightgbm as lgb
        except ImportError:
            if verbose:
                print("  LightGBM not available, skipping")
            return

        self.lgbm_model = lgb.LGBMRegressor(
            n_estimators=self.config.lgbm_n_estimators,
            max_depth=self.config.lgbm_max_depth,
            learning_rate=self.config.lgbm_learning_rate,
            subsample=self.config.lgbm_subsample,
            colsample_bytree=self.config.lgbm_colsample_bytree,
            num_leaves=self.config.lgbm_num_leaves,
            random_state=self.config.random_state,
            n_jobs=-1,
            verbose=-1,
        )

        fit_kwargs = {}
        if val_features is not None and val_labels is not None:
            fit_kwargs["eval_set"] = [(val_features, val_labels)]
            fit_kwargs["callbacks"] = [
                lgb.early_stopping(self.config.early_stopping_rounds, verbose=False),
            ]

        self.lgbm_model.fit(features, labels, **fit_kwargs)

        if verbose:
            print(f"  LightGBM trained: {self.lgbm_model.n_estimators} trees")

    def _select_features_shap(self, features, labels, verbose):
        """Select top-k features by SHAP importance."""
        if self.xgb_model is None:
            self._selected_indices = np.arange(min(self.config.shap_top_k, features.shape[1]))
            return

        try:
            import shap
            explainer = shap.TreeExplainer(self.xgb_model)
            shap_values = explainer.shap_values(features)
            mean_abs_shap = np.abs(shap_values).mean(axis=0)

            top_k = min(self.config.shap_top_k, features.shape[1])
            self._selected_indices = np.argsort(mean_abs_shap)[::-1][:top_k]

            if self._feature_names:
                self.selected_features = [self._feature_names[i] for i in self._selected_indices]

            if verbose:
                print(f"  SHAP selected top-{top_k} features")
        except ImportError:
            if verbose:
                print("  SHAP not available, using all features")
            self._selected_indices = np.arange(min(self.config.shap_top_k, features.shape[1]))

    def predict(self, features: np.ndarray | pd.DataFrame) -> dict[str, float]:
        """Generate ensemble predictions.

        Args:
            features: Feature matrix (n_samples, n_features)

        Returns:
            Dict with xgboost, lightgbm, and ensemble predictions
        """
        if not self.is_fitted:
            raise RuntimeError("Ensemble not fitted. Call fit() first.")

        if isinstance(features, pd.DataFrame):
            features = features.values

        if self.config.use_shap_selection and hasattr(self, "_selected_indices"):
            features = features[:, self._selected_indices]

        predictions = {}

        if self.xgb_model is not None:
            try:
                predictions["xgboost"] = float(self.xgb_model.predict(features)[-1])
            except Exception:
                predictions["xgboost"] = 0.0
        else:
            predictions["xgboost"] = 0.0

        if self.lgbm_model is not None:
            try:
                predictions["lightgbm"] = float(self.lgbm_model.predict(features)[-1])
            except Exception:
                predictions["lightgbm"] = 0.0
        else:
            predictions["lightgbm"] = 0.0

        w_xgb = self.config.xgb_weight
        w_lgbm = self.config.lgbm_weight
        total_w = w_xgb + w_lgbm
        if total_w > 0:
            ensemble = (w_xgb * predictions["xgboost"] + w_lgbm * predictions["lightgbm"]) / total_w
        else:
            ensemble = 0.0

        predictions["ensemble"] = float(np.clip(ensemble, -1, 1))
        return predictions

    def predict_signal(self, features: np.ndarray | pd.DataFrame) -> float:
        """Get ensemble signal only.

        Returns:
            Signal value [-1, 1]
        """
        return self.predict(features)["ensemble"]

    def feature_importance(self) -> pd.DataFrame:
        """Get feature importance from both models.

        Returns:
            DataFrame with feature names and importance scores
        """
        if not self.is_fitted:
            return pd.DataFrame()

        rows = []
        names = self.selected_features or self._feature_names or []

        if self.xgb_model is not None and hasattr(self.xgb_model, "feature_importances_"):
            xgb_imp = self.xgb_model.feature_importances_
            for i, imp in enumerate(xgb_imp):
                name = names[i] if i < len(names) else f"feature_{i}"
                rows.append({"feature": name, "xgboost_importance": imp})

        if self.lgbm_model is not None and hasattr(self.lgbm_model, "feature_importances_"):
            lgbm_imp = self.lgbm_model.feature_importances_
            if rows:
                for i, imp in enumerate(lgbm_imp):
                    if i < len(rows):
                        rows[i]["lightgbm_importance"] = imp
            else:
                for i, imp in enumerate(lgbm_imp):
                    name = names[i] if i < len(names) else f"feature_{i}"
                    rows.append({"feature": name, "lightgbm_importance": imp})

        df = pd.DataFrame(rows)
        if not df.empty:
            for col in ["xgboost_importance", "lightgbm_importance"]:
                if col in df.columns:
                    df[col] = df[col].fillna(0)
            if "xgboost_importance" in df.columns and "lightgbm_importance" in df.columns:
                df["combined"] = (df["xgboost_importance"] + df["lightgbm_importance"]) / 2
                df = df.sort_values("combined", ascending=False)

        return df
