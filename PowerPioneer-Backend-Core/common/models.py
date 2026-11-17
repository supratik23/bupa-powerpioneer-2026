from django.db import models


class TimeStampedModel(models.Model):
    """Adds the ``created_at`` / ``updated_at`` columns used across the schema."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
