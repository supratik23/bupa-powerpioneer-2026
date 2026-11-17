"""
Recalculate wellbeing scores (e.g. from a nightly scheduler).

    python manage.py calculate_wellbeing
    python manage.py calculate_wellbeing --date 2026-11-01 --employee <uuid> --no-interventions
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from employees.models import Employee
from wellbeing.services import calculate_for_all, calculate_wellbeing


class Command(BaseCommand):
    help = "Calculate wellbeing snapshots, predictions and interventions."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Snapshot date YYYY-MM-DD (default today).")
        parser.add_argument("--employee", help="Only this employee_id.")
        parser.add_argument("--no-interventions", action="store_true")

    def handle(self, *args, **opts):
        snapshot_date = date.fromisoformat(opts["date"]) if opts["date"] else None
        create = not opts["no_interventions"]
        if opts["employee"]:
            try:
                emp = Employee.objects.get(pk=opts["employee"])
            except (Employee.DoesNotExist, ValueError) as exc:
                raise CommandError(f"Employee not found: {opts['employee']}") from exc
            predictions = [calculate_wellbeing(emp, snapshot_date, create_interventions=create)]
        else:
            predictions = calculate_for_all(snapshot_date, create_interventions=create)
        for p in predictions:
            self.stdout.write(f"{p.employee.full_name:<24} {p.risk_snapshot.wellbeing_score:>7}  {p.risk_band}")
        self.stdout.write(self.style.SUCCESS(f"Scored {len(predictions)} employee(s)."))
