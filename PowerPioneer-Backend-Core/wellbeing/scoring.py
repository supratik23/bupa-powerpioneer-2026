"""
Rule-based wellbeing score (0-100, higher = better).

    wellbeing = clamp(100 - sum(penalties) + survey_adjustment, 0, 100)

Each risk factor converts one snapshot column into penalty points with a threshold
and a cap, so no single factor can dominate. The survey adjustment ranges from
-10 (all worst answers) to +10 (all best answers) and is 0 without responses.

Because the score is additive, every factor's points are stored directly as the
explanation's contribution (``shap_value``): positive = increases risk.

Risk band from the wellbeing score:
    >= 75 LOW | >= 55 MODERATE | >= 35 HIGH | < 35 CRITICAL
"""
from dataclasses import dataclass

MODEL_NAME = "wellbeing-rules"
MODEL_VERSION = "1.0.0"
SURVEY_MAX_ADJUSTMENT = 10.0


@dataclass(frozen=True)
class Rule:
    feature: str
    threshold: float          # no penalty at or below (or above, for "below" rules) this value
    per_unit: float           # points per unit beyond the threshold
    cap: float                # maximum points
    below: bool = False       # True if lower values are worse (e.g. rest hours)
    description: str = ""

    def points(self, value) -> float:
        if value is None:
            return 0.0
        v = float(value)
        excess = (self.threshold - v) if self.below else (v - self.threshold)
        return round(min(self.cap, max(0.0, excess * self.per_unit)), 4)


RULES: list[Rule] = [
    Rule("overtime_ratio_30d", 0.05, 50, 15, description="overtime above 5% of contracted hours"),
    Rule("night_shifts_30d", 4, 1.5, 10, description="more than 4 night shifts in 30 days"),
    Rule("long_shifts_30d", 8, 1.0, 6, description="more than 8 shifts of 12h+ in 30 days"),
    Rule("max_consecutive_work_days", 5, 2.0, 10, description="more than 5 working days in a row"),
    Rule("max_consecutive_night_shifts", 3, 2.5, 8, description="more than 3 nights in a row"),
    Rule("minimum_rest_hours_between_shifts", 11, 1.0, 8, below=True, description="less than 11h rest"),
    Rule("short_notice_roster_changes_30d", 0, 1.5, 6, description="short-notice roster changes"),
    Rule("missed_breaks_30d", 1, 1.0, 8, description="missed breaks"),
    Rule("late_arrivals_30d", 2, 0.5, 4, description="late arrivals"),
    Rule("days_since_last_meaningful_leave", 90, 1 / 15, 8, description="no 5+ day break for over 90 days"),
    Rule("cancelled_or_rejected_leave_90d", 0, 2.0, 6, description="cancelled or rejected leave"),
    Rule("understaffed_shift_ratio_30d", 0.1, 12, 8, description="more than 10% of shifts understaffed"),
    Rule("average_patient_load_ratio_30d", 1.0, 20, 8, description="patient load above expected"),
    Rule("redeployments_90d", 1, 1.0, 5, description="redeployments to other areas"),
    # maternity return (only populated during the first year back)
    Rule("overtime_hours_since_maternity_return", 0, 0.5, 6, description="overtime since maternity return"),
    Rule("maternity_adjustments_fulfilment_ratio", 1.0, 8, 8, below=True,
         description="agreed return-to-work adjustments not honoured"),
    Rule("nursing_or_recovery_breaks_missed_30d", 0, 1.5, 6, description="missed nursing/recovery breaks"),
    Rule("return_schedule_variance_hours_30d", 4, 0.25, 4, description="actual vs planned hours variance"),
]


def bradford_factor(episodes: int, days: int) -> int:
    """S^2 x D: frequent short absences weigh more than one long absence."""
    return episodes * episodes * days


def absence_points(episodes: int, days: int) -> float:
    return round(min(10.0, bradford_factor(episodes, days) / 25), 4)


@dataclass
class Contribution:
    feature_name: str
    feature_value: float | None
    points: float             # >0 increases risk, <0 decreases risk


@dataclass
class ScoreResult:
    wellbeing_score: float
    risk_score: float
    risk_band: str
    contributions: list[Contribution]


def band_for(wellbeing_score: float) -> str:
    if wellbeing_score >= 75:
        return "LOW"
    if wellbeing_score >= 55:
        return "MODERATE"
    if wellbeing_score >= 35:
        return "HIGH"
    return "CRITICAL"


def calculate_score(columns: dict, survey_score: float | None = None) -> ScoreResult:
    contributions: list[Contribution] = []
    for rule in RULES:
        value = columns.get(rule.feature)
        pts = rule.points(value)
        if pts:
            contributions.append(Contribution(rule.feature, None if value is None else float(value), pts))

    episodes = int(columns.get("unplanned_absence_episodes_90d") or 0)
    days = int(columns.get("unplanned_absence_days_90d") or 0)
    pts = absence_points(episodes, days)
    if pts:
        contributions.append(Contribution("bradford_factor_90d", float(bradford_factor(episodes, days)), pts))

    if survey_score is not None:
        adjustment = round((survey_score - 0.5) * 2 * SURVEY_MAX_ADJUSTMENT, 4)
        if adjustment:
            # negative points = protective factor
            contributions.append(Contribution("survey_sentiment_30d", round(survey_score, 4), -adjustment))

    raw = 100.0 - sum(c.points for c in contributions)
    wellbeing = round(max(0.0, min(100.0, raw)), 2)
    contributions.sort(key=lambda c: abs(c.points), reverse=True)
    return ScoreResult(
        wellbeing_score=wellbeing,
        risk_score=round(100.0 - wellbeing, 2),
        risk_band=band_for(wellbeing),
        contributions=contributions,
    )
