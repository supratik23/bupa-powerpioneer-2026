from datetime import timedelta
from fastmcp import FastMCP
from services.db_service import SupabaseDBConnectionManager
from services.risk_feature_service import NoShiftsInWindow, _utc
from services.risk_model_service import get_risk_model, score_employee
from services.shiftguard_repository import (
    RISK_BAND_ORDER, XGBOOST_MODEL_NAME, EMPLOYEE_COLUMNS, EMPLOYEE_FROM, ToolInputError, dumps, parse_date,
    resolve_employee,
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("ShiftGuard Risk Tool")

# Load the model (numpy / pandas / xgboost) in the main thread at startup. FastMCP runs sync tools in a worker
# thread, and a first-time numpy import inside that worker thread deadlocks on Windows.
try:
    get_risk_model()
except Exception:
    logger.exception("Risk model could not be loaded at startup; the tools will report the error.")


def _public(summary: dict, include_features: bool) -> dict:
    out = {k: v for k, v in summary.items() if k != "features"}
    if include_features:
        out["features"] = summary["features"]
    return out


@mcp.tool()
def predict_employee_risk(employee: str, as_of_date: str = "", save: bool = True,
                          include_features: bool = False) -> str:
    """
    Run the ShiftGuard XGBoost burnout/wellbeing risk model for ONE employee and (by default) save the result.

    Computes the 26 model features from shift_roster, attendance, leave_request, employee and check-in responses,
    calls the model, then writes employee_risk_snapshot (upsert), risk_prediction (model_name 'XGBOOST') and
    risk_explanation (top 5 factors). The result appears in the ShiftGuard dashboard.

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        as_of_date: Prediction date D as YYYY-MM-DD. Defaults to today (UTC).
        save: False only previews the prediction without writing to the database.
        include_features: True also returns all 26 feature values.

    Returns risk_probability (0-1), risk_score (0-100), risk_band (LOW/MEDIUM/HIGH/CRITICAL), top_factors
    (feature, value, shap_value, direction) and the saved prediction_id.
    """
    try:
        d = parse_date(as_of_date)
        with SupabaseDBConnectionManager() as db:
            row = resolve_employee(db, employee)
            summary = score_employee(db, row, d, save=save)
        return dumps(_public(summary, include_features))
    except NoShiftsInWindow as e:
        return f"Skipped: {e} The model only scores employees with shifts in the last 30 days."
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("predict_employee_risk failed")
        return f"Error running the risk model: {e}"


@mcp.tool()
def predict_risk_for_all_employees(as_of_date: str = "", save: bool = True, department: str = "") -> str:
    """
    Run the ShiftGuard risk model for every active employee with shifts in the last 30 days (a daily batch run)
    and save each result. Employees with no recent shifts (e.g. managers) are skipped.

    Args:
        as_of_date: Prediction date D as YYYY-MM-DD. Defaults to today (UTC).
        save: False only previews without writing.
        department: Optional department filter.

    Returns counts per risk band and one line per employee, highest risk first.
    """
    try:
        d = parse_date(as_of_date)
        get_risk_model()  # fail fast if the artifacts are missing
        params = [_utc(d - timedelta(days=29)), _utc(d + timedelta(days=1))]
        dept_sql = ""
        if department.strip():
            dept_sql = "AND lower(e.department) = lower(%s)"
            params.append(department.strip())

        results, skipped, errors = [], [], []
        with SupabaseDBConnectionManager() as db:
            employees = db.fetch_all(
                f"""SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM}
                    WHERE e.is_active = true AND EXISTS (
                        SELECT 1 FROM shift_roster s WHERE s.employee_id = e.employee_id
                        AND s.shift_start >= %s AND s.shift_start < %s) {dept_sql}
                    ORDER BY e.last_name, e.first_name""",
                params,
            )
            for row in employees:
                name = f"{row['first_name']} {row['last_name']}"
                try:
                    results.append(score_employee(db, row, d, save=save))
                except NoShiftsInWindow:
                    skipped.append(name)
                except Exception as e:  # keep going for the other employees
                    logger.exception("Scoring failed for %s", row["employee_id"])
                    errors.append({"employee": name, "error": str(e)})

        results.sort(key=lambda r: r["risk_probability"], reverse=True)
        bands: dict[str, int] = {}
        for r in results:
            bands[r["risk_band"]] = bands.get(r["risk_band"], 0) + 1
        return dumps({
            "snapshot_date": d,
            "saved": save,
            "scored": len(results),
            "band_counts": bands,
            "employees": [
                {"employee_id": r["employee_id"], "name": r["name"], "risk_band": r["risk_band"],
                 "risk_score": r["risk_score"], "prediction_id": r.get("prediction_id"),
                 "top_factor": r["top_factors"][0]["feature"] if r["top_factors"] else None}
                for r in results
            ],
            "skipped_no_recent_shifts": skipped,
            "errors": errors,
        })
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("predict_risk_for_all_employees failed")
        return f"Error running the batch risk prediction: {e}"


@mcp.tool()
def list_at_risk_employees(min_band: str = "HIGH", snapshot_date: str = "") -> str:
    """
    List employees whose saved XGBoost risk prediction is at or above a band, using the latest prediction per
    employee. Reads only; run predict_risk_for_all_employees first if nothing has been scored for that date.

    Args:
        min_band: LOW, MEDIUM, HIGH or CRITICAL.
        snapshot_date: YYYY-MM-DD. Empty uses the most recent live (non-training) snapshot date.
    """
    try:
        min_band = (min_band or "HIGH").upper()
        if min_band not in RISK_BAND_ORDER:
            raise ToolInputError("min_band must be one of LOW, MEDIUM, HIGH, CRITICAL.")
        with SupabaseDBConnectionManager() as db:
            if snapshot_date:
                d = parse_date(snapshot_date)
            else:
                row = db.fetch_one(
                    "SELECT max(s.snapshot_date) AS d FROM employee_risk_snapshot s "
                    "JOIN risk_prediction p ON p.risk_snapshot_id = s.risk_snapshot_id "
                    "WHERE s.is_training_record = false AND p.model_name = %s",
                    (XGBOOST_MODEL_NAME,),
                )
                if not row or not row["d"]:
                    return "No live XGBoost predictions saved yet. Run predict_risk_for_all_employees first."
                d = row["d"]
            rows = db.fetch_all(
                """
                SELECT DISTINCT ON (p.employee_id)
                       p.employee_id, e.first_name || ' ' || e.last_name AS name, e.email, e.department,
                       m.email AS manager_email, p.prediction_id, p.risk_band, p.risk_score, p.predicted_at
                FROM risk_prediction p
                JOIN employee_risk_snapshot s ON s.risk_snapshot_id = p.risk_snapshot_id
                JOIN employee e ON e.employee_id = p.employee_id
                LEFT JOIN employee m ON m.employee_id = e.manager_employee_id
                WHERE p.model_name = %s AND s.is_training_record = false AND s.snapshot_date = %s
                ORDER BY p.employee_id, p.predicted_at DESC
                """,
                (XGBOOST_MODEL_NAME, d),
            )
            selected = [r for r in rows if RISK_BAND_ORDER.get(r["risk_band"], 0) >= RISK_BAND_ORDER[min_band]]
            selected.sort(key=lambda r: r["risk_score"], reverse=True)
            for r in selected:
                r["top_factors"] = db.fetch_all(
                    "SELECT feature_name, feature_value, shap_value, contribution_direction FROM risk_explanation "
                    "WHERE prediction_id = %s ORDER BY display_order LIMIT 3",
                    (r["prediction_id"],),
                )
        return dumps({"snapshot_date": d, "min_band": min_band, "count": len(selected), "employees": selected})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("list_at_risk_employees failed")
        return f"Error listing at-risk employees: {e}"


@mcp.tool()
def get_employee_risk_history(employee: str, limit: int = 10) -> str:
    """
    Saved XGBoost risk predictions for one employee (newest first) with the explanation factors of the latest one.
    Use it to answer "what is X's risk / why / how has it changed". Training records are excluded.

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        limit: Number of past predictions (1-60).
    """
    try:
        limit = max(1, min(int(limit), 60))
        with SupabaseDBConnectionManager() as db:
            row = resolve_employee(db, employee)
            history = db.fetch_all(
                """
                SELECT DISTINCT ON (s.snapshot_date) s.snapshot_date, p.prediction_id, p.risk_band, p.risk_score,
                       p.model_version, p.predicted_at, s.wellbeing_score
                FROM risk_prediction p
                JOIN employee_risk_snapshot s ON s.risk_snapshot_id = p.risk_snapshot_id
                WHERE p.employee_id = %s AND p.model_name = %s AND s.is_training_record = false
                ORDER BY s.snapshot_date DESC, p.predicted_at DESC
                LIMIT %s
                """,
                (row["employee_id"], XGBOOST_MODEL_NAME, limit),
            )
            factors = []
            if history:
                factors = db.fetch_all(
                    "SELECT feature_name, feature_value, shap_value, contribution_direction, display_order "
                    "FROM risk_explanation WHERE prediction_id = %s ORDER BY display_order",
                    (history[0]["prediction_id"],),
                )
        if not history:
            return (f"No saved live risk predictions for {row['first_name']} {row['last_name']}. "
                    "Use predict_employee_risk to score them.")
        return dumps({
            "employee_id": row["employee_id"],
            "name": f"{row['first_name']} {row['last_name']}",
            "latest": history[0],
            "latest_top_factors": factors,
            "history": history,
        })
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("get_employee_risk_history failed")
        return f"Error fetching risk history: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
