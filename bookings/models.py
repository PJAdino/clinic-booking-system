from django.db import models


class Doctor(models.Model):
    """
    A doctor at the clinic. Working hours are treated as clinic-local
    time (EAT / Africa/Nairobi) — see services.py for how these are
    used to validate bookings, which are stored in UTC.
    """

    full_name = models.CharField(max_length=100)
    working_start = models.TimeField(
        help_text="Clinic-local (EAT) start of working hours, e.g. 09:00"
    )
    working_end = models.TimeField(
        help_text="Clinic-local (EAT) end of working hours, e.g. 17:00"
    )

    def __str__(self):
        return self.full_name


class Appointment(models.Model):
    """
    Represents a single 30-minute slot for a doctor, whether free,
    booked, or cancelled.

    Concurrency safety: the unique constraint on (doctor, slot_time)
    (scoped to booked rows) is enforced at the database level, so two
    concurrent requests can never both successfully create a booked
    row for the same doctor at the same time — even if both passed an
    application-level availability check moments earlier. See Phase 1
    design notes in README.
    """

    class Status(models.TextChoices):
        FREE = "free", "Free"
        BOOKED = "booked", "Booked"
        CANCELLED = "cancelled", "Cancelled"

    doctor = models.ForeignKey(
        Doctor, on_delete=models.CASCADE, related_name="appointments"
    )
    patient_id = models.IntegerField(null=True, blank=True)
    slot_time = models.DateTimeField(help_text="Stored in UTC")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.FREE
    )
    cancellation_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "slot_time"],
                condition=models.Q(status="booked"),
                name="unique_doctor_slot_when_booked",
            )
        ]

    def __str__(self):
        return f"{self.doctor} @ {self.slot_time} ({self.status})"
