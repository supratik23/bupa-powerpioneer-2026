"""ShiftGuard risk-model inference (FastAPI-ready).

Loads the artifacts produced by the training notebook:
    model.json          XGBoost model (portable JSON)
    feature_names.json  exact training feature order
    model_config.json   calibration constant, risk bands, metadata

Usage (FastAPI):
    from risk_inference import predict_employee_risk
    result = predict_employee_risk(snapshot_feature_dict)

Prototype on synthetic data. Risk bands are NOT clinically validated.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd
import xgboost as xgb

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent


class RiskModel:
    def __init__(self, artifact_dir: Path | str = DEFAULT_ARTIFACT_DIR):
        artifact_dir = Path(artifact_dir)
        self.feature_names: list[str] = json.loads((artifact_dir / "feature_names.json").read_text())
        self.config: dict = json.loads((artifact_dir / "model_config.json").read_text())
        self.model = xgb.XGBClassifier()
        self.model.load_model(str(artifact_dir / "model.json"))

        booster_names = self.model.get_booster().feature_names
        if booster_names is not None and list(booster_names) != self.feature_names:
            raise ValueError("model.json feature names do not match feature_names.json order")

        self.scale_pos_weight = float(self.config["scale_pos_weight"])
        self.risk_bands = sorted(self.config["risk_bands"], key=lambda b: b["min_probability"])
        self.top_k = int(self.config.get("top_k_factors", 5))

    # -- 1-4: validate names, enforce training order, preserve NULLs, build a DataFrame
    def _to_frame(self, feature_dict: Mapping[str, Any]) -> pd.DataFrame:
        missing = [f for f in self.feature_names if f not in feature_dict]
        if missing:
            # A key must be present even when not applicable. Send None/null explicitly, so a
            # "forgot to send it" bug is never confused with "not applicable".
            raise ValueError(f"Missing required features (send null if not applicable): {missing}")
        row = {}
        for f in self.feature_names:                       # exact training order
            v = feature_dict[f]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                row[f] = np.nan                            # NULL stays missing; never coerced to 0
                continue
            if isinstance(v, bool):
                raise ValueError(f"Feature {f!r} must be numeric, got bool")
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"Feature {f!r} must be numeric or null, got {v!r}") from None
            if math.isinf(fv):
                raise ValueError(f"Feature {f!r} is infinite")
            row[f] = fv
        return pd.DataFrame([row], columns=self.feature_names, dtype=float)

    def calibrate(self, raw: float) -> float:
        """Map the raw class-weighted score to a calibrated probability (method from model_config.json)."""
        raw = min(max(raw, 1e-7), 1 - 1e-7)
        cal = self.config.get("calibration", {})
        if cal.get("method") == "platt":
            z = float(cal["a"]) * math.log(raw / (1 - raw)) + float(cal["b"])
            z = max(min(z, 700.0), -700.0)
            return 1.0 / (1.0 + math.exp(-z))
        return raw / (raw + (1 - raw) * self.scale_pos_weight)   # prior correction

    def band_for(self, probability: float) -> str:
        band = self.risk_bands[0]["band"]
        for b in self.risk_bands:
            if probability >= b["min_probability"]:
                band = b["band"]
        return band

    def predict(self, feature_dict: Mapping[str, Any], top_k: Optional[int] = None) -> dict:
        X = self._to_frame(feature_dict)
        # 5-7: probability (raw class-weighted score -> calibrated probability) and band
        raw = float(self.model.predict_proba(X)[:, 1][0])
        probability = self.calibrate(raw)
        # 8: TreeSHAP contributions natively from XGBoost (log-odds; last column = base value)
        contribs = self.model.get_booster().predict(xgb.DMatrix(X, missing=np.nan), pred_contribs=True)[0]
        shap_values, base_value = contribs[:-1], float(contribs[-1])
        # 9: top contributing features by |SHAP|
        k = self.top_k if top_k is None else top_k
        order = [i for i in np.argsort(-np.abs(shap_values)) if shap_values[i] != 0][:k]
        top_factors = []
        for i in order:
            value = X.iat[0, i]
            top_factors.append({
                "feature": self.feature_names[i],
                "value": None if np.isnan(value) else round(float(value), 4),
                "shap_value": round(float(shap_values[i]), 4),
                "direction": "INCREASES_RISK" if shap_values[i] > 0 else "DECREASES_RISK",
            })
        return {
            "risk_probability": round(probability, 4),
            "risk_band": self.band_for(probability),
            "raw_model_score": round(raw, 4),
            "top_factors": top_factors,
            "shap_base_value": round(base_value, 4),
            "shap_units": "log_odds",
            "model_version": self.config.get("model_version"),
        }


_default_model: Optional[RiskModel] = None


def get_model(artifact_dir: Path | str | None = None) -> RiskModel:
    """Load once and cache (call at FastAPI startup)."""
    global _default_model
    if artifact_dir is not None:
        return RiskModel(artifact_dir)
    if _default_model is None:
        _default_model = RiskModel()
    return _default_model


def predict_employee_risk(feature_dict: Mapping[str, Any], top_k: Optional[int] = None,
                          artifact_dir: Path | str | None = None) -> dict:
    """Predict risk for one employee snapshot. Keys must include every training feature."""
    return get_model(artifact_dir).predict(feature_dict, top_k=top_k)
