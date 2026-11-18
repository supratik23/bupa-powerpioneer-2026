"""
ShiftGuard XGBoost risk model: load the artifacts, score an employee and persist the result.

Artifacts (PowerPioneer-AI/model_artifacts by default, or RISK_MODEL_ARTIFACT_DIR):
    model.json, feature_names.json, model_config.json, risk_inference.py

Persistence order (risk_prediction.risk_snapshot_id is required, so the snapshot goes first):
    1. employee_risk_snapshot  upsert on (employee_id, snapshot_date, is_training_record)
    2. risk_prediction         risk_score = round(probability * 100, 2), model_name = 'XGBOOST'
    3. risk_explanation        one row per top factor, display_order 1..5
"""
from __future__ import annotations

import logging
import threading
import types
from datetime import date
from pathlib import Path
from typing import Any

from config import settings
from services.risk_feature_service import FEATURE_NAMES, NoShiftsInWindow, compute_features
from services.shiftguard_repository import XGBOOST_MODEL_NAME

logger = logging.getLogger(__name__)

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[3] / "model_artifacts"   # PowerPioneer-AI/model_artifacts

# Snapshot columns stored as integer; the rest of the features are numeric (rounded to 4 places on storage).
INTEGER_FEATURES = {
    "night_shifts_30d", "long_shifts_30d", "max_consecutive_work_days", "max_consecutive_night_shifts",
    "short_notice_roster_changes_30d", "missed_breaks_30d", "unplanned_absence_days_90d",
    "unplanned_absence_episodes_90d", "late_arrivals_30d", "days_since_last_meaningful_leave",
    "cancelled_or_rejected_leave_90d", "redeployments_90d", "days_since_maternity_return",
    "nursing_or_recovery_breaks_missed_30d", "end_of_life_care_7d",
}

_model = None
_model_lock = threading.Lock()


def artifact_dir() -> Path:
    return Path(settings.RISK_MODEL_ARTIFACT_DIR) if settings.RISK_MODEL_ARTIFACT_DIR else DEFAULT_ARTIFACT_DIR


def get_risk_model():
    """Load risk_inference.RiskModel once per process."""
    global _model
    with _model_lock:
        if _model is None:
            directory = artifact_dir()
            module_path = directory / "risk_inference.py"
            if not module_path.exists():
                raise FileNotFoundError(f"risk_inference.py not found in {directory}. Set RISK_MODEL_ARTIFACT_DIR.")
            # Compile from source without writing a .pyc into the shared model_artifacts folder.
            module = types.ModuleType("shiftguard_risk_inference")
            module.__file__ = str(module_path)
            exec(compile(module_path.read_text(encoding="utf-8"), str(module_path), "exec"), module.__dict__)
            _model = module.RiskModel(directory)
            if list(_model.feature_names) != FEATURE_NAMES:
                raise RuntimeError("feature_names.json does not match the agent's feature list.")
            logger.info("Loaded risk model %s from %s", _model.config.get("model_version"), directory)
        return _model


def predict(features: dict[str, Any]) -> dict:
    return get_risk_model().predict(features)


def _store_value(name: str, value: Any):
    if value is None:
        return None
    return int(round(value)) if name in INTEGER_FEATURES else round(float(value), 4)


def save_prediction(db, employee_id, d: date, features: dict[str, Any], result: dict) -> dict:
    """Write snapshot, prediction and explanations in one transaction. Returns the new ids."""
    connection = db.db_connection()
    if connection is None:
        raise ConnectionError("Unable to connect to the Supabase database.")

    stored = {name: _store_value(name, features[name]) for name in FEATURE_NAMES}
    columns = ", ".join(FEATURE_NAMES)
    placeholders = ", ".join(["%s"] * len(FEATURE_NAMES))
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in FEATURE_NAMES)
    model_version = result.get("model_version") or get_risk_model().config.get("model_version")

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO employee_risk_snapshot
                    (employee_id, snapshot_date, {columns}, risk_label, risk_outcome_within_30d, is_training_record)
                VALUES (%s, %s, {placeholders}, %s, NULL, false)
                ON CONFLICT (employee_id, snapshot_date, is_training_record) DO UPDATE SET
                    {updates}, risk_label = EXCLUDED.risk_label, risk_outcome_within_30d = NULL, updated_at = now()
                RETURNING risk_snapshot_id
                """,
                (employee_id, d, *[stored[n] for n in FEATURE_NAMES], result["risk_band"]),
            )
            snapshot_id = cursor.fetchone()[0]

            cursor.execute(
                """
                INSERT INTO risk_prediction
                    (employee_id, risk_snapshot_id, risk_score, risk_band, model_name, model_version, predicted_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                RETURNING prediction_id
                """,
                (employee_id, snapshot_id, round(result["risk_probability"] * 100, 2), result["risk_band"],
                 XGBOOST_MODEL_NAME, model_version),
            )
            prediction_id = cursor.fetchone()[0]

            for order, factor in enumerate(result["top_factors"], start=1):
                cursor.execute(
                    """
                    INSERT INTO risk_explanation
                        (prediction_id, feature_name, feature_value, shap_value, contribution_direction, display_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (prediction_id, factor["feature"], factor["value"], factor["shap_value"],
                     factor["direction"], order),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"risk_snapshot_id": str(snapshot_id), "prediction_id": str(prediction_id)}


def score_employee(db, employee: dict, d: date, save: bool = True) -> dict:
    """
    Compute features -> predict -> (optionally) persist. Returns a summary dict.
    Raises NoShiftsInWindow for employees without shifts in the last 30 days.
    """
    features = compute_features(db, employee, d)
    result = predict(features)
    summary = {
        "employee_id": str(employee["employee_id"]),
        "name": f"{employee['first_name']} {employee['last_name']}".strip(),
        "snapshot_date": d.isoformat(),
        "risk_probability": result["risk_probability"],
        "risk_score": round(result["risk_probability"] * 100, 2),
        "risk_band": result["risk_band"],
        "top_factors": result["top_factors"],
        "model_version": result["model_version"],
        "saved": False,
    }
    if save:
        summary.update(save_prediction(db, employee["employee_id"], d, features, result))
        summary["saved"] = True
    summary["features"] = features
    return summary


__all__ = ["NoShiftsInWindow", "get_risk_model", "predict", "save_prediction", "score_employee", "artifact_dir"]
