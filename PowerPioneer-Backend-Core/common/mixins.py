from django.db.models import Q

from .permissions import can_manage, ensure, is_staff


class EmployeeScopedViewSetMixin:
    """
    Restricts querysets to data a user may see and checks write access.

    * ``employee_field``     - ORM path from the model to the owning employee.
    * ``allow_self_write``   - the owning employee may create/update their own rows.

    Staff see everything. Other users see rows owned by themselves or by
    their direct reports. Writes require staff or the owner's manager
    (plus the owner themself when ``allow_self_write`` is True).
    """

    employee_field = "employee"
    allow_self_write = False

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(self, "swagger_fake_view", False) or is_staff(user):
            return qs
        f = self.employee_field
        return qs.filter(Q(**{f: user}) | Q(**{f"{f}__manager_employee": user})).distinct()

    # -- write checks -----------------------------------------------------
    def _owner_from(self, obj_or_data):
        target = obj_or_data
        for part in self.employee_field.split("__"):
            target = target.get(part) if isinstance(target, dict) else getattr(target, part, None)
            if target is None:
                return None
        return target

    def check_write(self, employee):
        user = self.request.user
        allowed = can_manage(user, employee) or (
            self.allow_self_write and employee is not None and employee.pk == user.pk
        )
        ensure(allowed, "Only staff or the employee's manager can modify this record.")

    def perform_create(self, serializer):
        self.check_write(self._owner_from(serializer.validated_data))
        serializer.save()

    def perform_update(self, serializer):
        self.check_write(self._owner_from(serializer.instance))
        new_owner = self._owner_from(serializer.validated_data)
        if new_owner is not None:
            self.check_write(new_owner)
        serializer.save()

    def perform_destroy(self, instance):
        self.check_write(self._owner_from(instance))
        instance.delete()
