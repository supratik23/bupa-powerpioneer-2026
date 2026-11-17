## Table `employee`
## Description - Main table for users of the application. It contains managers/employees/buddies
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `employee_id` | `uuid` | Primary |
| `employee_number` | `varchar` |  Unique |
| `first_name` | `varchar` |  |
| `last_name` | `varchar` |  |
| `email` | `varchar` |  Unique |
| `job_role` | `varchar` |  |
| `department` | `varchar` |  Nullable |
| `location` | `varchar` |  Nullable |
| `manager_employee_id` | `uuid` |  Nullable |
| `buddy_employee_id` | `uuid` |  Nullable |
| `employment_type` | `varchar` |  |
| `contracted_weekly_hours` | `numeric` |  Nullable |
| `hire_date` | `date` |  Nullable |
| `maternity_return_date` | `date` |  Nullable |
| `is_active` | `bool` |  |
| `created_at` | `timestamptz` |  |
| `updated_at` | `timestamptz` |  |

## Table `shift_roster`
## Description - Table for storing the calendar data of users.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `shift_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `shift_start` | `timestamptz` |  |
| `shift_end` | `timestamptz` |  |
| `planned_hours` | `numeric` |  |
| `actual_hours` | `numeric` |  Nullable |
| `shift_type` | `varchar` |  |
| `location` | `varchar` |  Nullable |
| `expected_patient_load` | `numeric` |  Nullable |
| `actual_patient_load` | `numeric` |  Nullable |
| `planned_staff_count` | `int4` |  Nullable |
| `actual_staff_count` | `int4` |  Nullable |
| `understaffed_flag` | `bool` |  |
| `missed_break_flag` | `bool` |  |
| `short_notice_change_flag` | `bool` |  |
| `redeployment_flag` | `bool` |  |
| `created_at` | `timestamptz` |  |
| `updated_at` | `timestamptz` |  |

## Table `leave_request`
## Description - Table for storing leave request of users.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `leave_request_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `leave_type` | `varchar` |  |
| `start_date` | `date` |  |
| `end_date` | `date` |  |
| `status` | `varchar` |  |
| `requested_at` | `timestamptz` |  |
| `decision_at` | `timestamptz` |  Nullable |
| `created_at` | `timestamptz` |  |
| `updated_at` | `timestamptz` |  |

## Table `attendance`
## Description - Table for storing attendance of users.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `attendance_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `attendance_date` | `date` |  |
| `attendance_status` | `varchar` |  |
| `late_minutes` | `int4` |  |
| `absence_type` | `varchar` |  Nullable |
| `absence_episode_id` | `uuid` |  Nullable |
| `notes` | `text` |  Nullable |
| `created_at` | `timestamptz` |  |
| `updated_at` | `timestamptz` |  |

## Table `question`
## Description - Table for storing questions generated. It will act as master table for questions.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `question_id` | `uuid` | Primary |
| `question_text` | `text` |  |
| `source` | `varchar` |  |
| `trigger_type` | `varchar` |  |
| `generated_for_employee_id` | `uuid` |  Nullable |
| `context_data` | `jsonb` |  Nullable |
| `model_name` | `varchar` |  Nullable |
| `prompt_version` | `varchar` |  Nullable |
| `is_active` | `bool` |  |
| `expires_at` | `timestamptz` |  Nullable |
| `created_at` | `timestamptz` |  |

## Table `question_option`
## Description - Option to choose from for each questions.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `option_id` | `uuid` | Primary |
| `question_id` | `uuid` |  |
| `option_text` | `text` |  |
| `normalized_score` | `int2` |  |
| `display_order` | `int2` |  |
| `created_at` | `timestamptz` |  |

## Table `employee_response`
## Description - Table to store the employee responses for each questions/options chosen.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `response_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `question_id` | `uuid` |  |
| `option_id` | `uuid` |  |
| `responded_at` | `timestamptz` |  |

## Table `employee_risk_snapshot`
## Description - This table stores the users roster data upto a specific time period and stores the well being score after calculating.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `risk_snapshot_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `snapshot_date` | `date` |  |
| `contracted_hours_30d` | `numeric` |  |
| `actual_hours_worked_30d` | `numeric` |  |
| `overtime_hours_30d` | `numeric` |  |
| `overtime_ratio_30d` | `numeric` |  |
| `night_shifts_30d` | `int4` |  |
| `long_shifts_30d` | `int4` |  |
| `max_consecutive_work_days` | `int4` |  |
| `max_consecutive_night_shifts` | `int4` |  |
| `minimum_rest_hours_between_shifts` | `numeric` |  Nullable |
| `short_notice_roster_changes_30d` | `int4` |  |
| `missed_breaks_30d` | `int4` |  |
| `unplanned_absence_days_90d` | `int4` |  |
| `unplanned_absence_episodes_90d` | `int4` |  |
| `late_arrivals_30d` | `int4` |  |
| `days_since_last_meaningful_leave` | `int4` |  Nullable |
| `cancelled_or_rejected_leave_90d` | `int4` |  |
| `understaffed_shift_ratio_30d` | `numeric` |  |
| `average_patient_load_ratio_30d` | `numeric` |  Nullable |
| `redeployments_90d` | `int4` |  |
| `wellbeing_score` | `numeric` |  Nullable |
| `days_since_maternity_return` | `int4` |  Nullable |
| `return_schedule_variance_hours_30d` | `numeric` |  Nullable |
| `overtime_hours_since_maternity_return` | `numeric` |  Nullable |
| `maternity_adjustments_fulfilment_ratio` | `numeric` |  Nullable |
| `nursing_or_recovery_breaks_missed_30d` | `int4` |  Nullable |
| `risk_label` | `varchar` |  Nullable |
| `risk_outcome_within_30d` | `bool` |  Nullable |
| `is_training_record` | `bool` |  |
| `created_at` | `timestamptz` |  |
| `updated_at` | `timestamptz` |  |

## Table `risk_prediction`
## Description - This table stores the risk predicted for the user
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `prediction_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `risk_snapshot_id` | `uuid` |  |
| `risk_score` | `numeric` |  |
| `risk_band` | `varchar` |  |
| `model_name` | `varchar` |  |
| `model_version` | `varchar` |  |
| `predicted_at` | `timestamptz` |  |

## Table `risk_explanation`
## Description - Explanation of risks
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `explanation_id` | `uuid` | Primary |
| `prediction_id` | `uuid` |  |
| `feature_name` | `varchar` |  |
| `feature_value` | `numeric` |  Nullable |
| `shap_value` | `numeric` |  |
| `contribution_direction` | `varchar` |  |
| `display_order` | `int2` |  |
| `created_at` | `timestamptz` |  |

## Table `intervention`
## Description - This table stores the communication triggered from a user.
### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `intervention_id` | `uuid` | Primary |
| `employee_id` | `uuid` |  |
| `prediction_id` | `uuid` |  Nullable |
| `target_employee_id` | `uuid` |  Nullable |
| `action_type` | `varchar` |  |
| `action_status` | `varchar` |  |
| `action_payload` | `jsonb` |  Nullable |
| `failure_reason` | `text` |  Nullable |
| `triggered_at` | `timestamptz` |  |
| `completed_at` | `timestamptz` |  Nullable |
| `created_at` | `timestamptz` |  |
| `updated_at` | `timestamptz` |  |

