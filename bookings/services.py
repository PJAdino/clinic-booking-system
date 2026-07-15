"""
Business logic for booking, cancelling, and rescheduling appointments.

Kept separate from views.py so that:
  - this logic is testable without simulating HTTP requests
  - it can be reused identically by both the booking and reschedule
    endpoints (reschedule validates the new slot exactly as a fresh
    booking would)

Concurrency note: validation (working hours, not-in-past) is checked
first and fails fast for requests that could never succeed. The actual
database write is then wrapped in a transaction and guarded by the
DB-level unique constraint on (doctor, slot_time) for booked rows —
this is what catches the case where two valid requests race for the
same slot at nearly the same instant. See README Phase 1 notes.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction, IntegrityError
from django.utils import timezone as django_timezone
import zoneinfo

from .models import Appointment, Doctor

CLINIC_TZ = zoneinfo.ZoneInfo("Africa/Nairobi")  # EAT, UTC+3


class BookingError(Exception):
    """Raised for any validation/business-rule failure. Views translate
    this into an appropriate HTTP status + message."""

    def __init__(self, message, code="invalid"):
        self.message = message
        self.code = code
        super().__init__(message)


def _validate_slot(doctor: Doctor, slot_time: datetime):
    """
    Shared validation used by both booking and rescheduling:
      - slot_time must not be in the past
      - slot_time must fall within the doctor's working hours (EAT)
    Raises BookingError if invalid.
    """
    now = django_timezone.now()
    if slot_time <= now:
        raise BookingError("Cannot book a slot in the past.", code="past_slot")

    local_time = slot_time.astimezone(CLINIC_TZ).time()
    if not (doctor.working_start <= local_time < doctor.working_end):
        raise BookingError(
            f"Slot falls outside {doctor.full_name}'s working hours "
            f"({doctor.working_start}–{doctor.working_end} EAT).",
            code="outside_working_hours",
        )


def book_appointment(
    doctor_id: int, patient_id: int, slot_time: datetime
) -> Appointment:
    """
    Books a slot for a patient. Raises BookingError on any failure,
    including the slot being taken concurrently by another request.
    """
    try:
        doctor = Doctor.objects.get(id=doctor_id)
    except Doctor.DoesNotExist:
        raise BookingError("Doctor not found.", code="not_found")

    _validate_slot(doctor, slot_time)

    try:
        with transaction.atomic():
            appointment = Appointment.objects.create(
                doctor=doctor,
                patient_id=patient_id,
                slot_time=slot_time,
                status=Appointment.Status.BOOKED,
            )
    except IntegrityError:
        # The DB-level unique constraint caught a concurrent booking
        # for this exact doctor+slot that validation couldn't see.
        raise BookingError(
            "This slot was just booked by someone else.", code="slot_taken"
        )

    return appointment


def cancel_appointment(appointment_id: int, reason: str) -> Appointment:
    try:
        appointment = Appointment.objects.get(id=appointment_id)
    except Appointment.DoesNotExist:
        raise BookingError("Appointment not found.", code="not_found")

    if appointment.status == Appointment.Status.CANCELLED:
        raise BookingError(
            "This appointment is already cancelled.", code="already_cancelled"
        )

    appointment.status = Appointment.Status.CANCELLED
    appointment.cancellation_reason = reason
    appointment.save()
    return appointment


def reschedule_appointment(appointment_id: int, new_slot_time: datetime) -> Appointment:
    """
    Moves an appointment to a new slot as a single atomic transaction.
    If the new slot can't be claimed (validation failure or a
    concurrent booking caught by the DB constraint), the whole
    operation rolls back and the original appointment is untouched.
    """
    try:
        original = Appointment.objects.select_for_update().get(id=appointment_id)
    except Appointment.DoesNotExist:
        raise BookingError("Appointment not found.", code="not_found")

    if original.status == Appointment.Status.CANCELLED:
        raise BookingError(
            "Cannot reschedule a cancelled appointment.", code="already_cancelled"
        )

    _validate_slot(original.doctor, new_slot_time)

    try:
        with transaction.atomic():
            original.status = Appointment.Status.CANCELLED
            original.cancellation_reason = "Rescheduled to a new slot."
            original.save()

            new_appointment = Appointment.objects.create(
                doctor=original.doctor,
                patient_id=original.patient_id,
                slot_time=new_slot_time,
                status=Appointment.Status.BOOKED,
            )
    except IntegrityError:
        raise BookingError(
            "The new slot was just booked by someone else.", code="slot_taken"
        )

    return new_appointment


def get_availability(doctor_id, date):
    possible_times = []
    doctor = Doctor.objects.get(id=doctor_id)
    current_time = datetime.combine(date, doctor.working_start, tzinfo=CLINIC_TZ)
    end_time = datetime.combine(date, doctor.working_end, tzinfo=CLINIC_TZ)

    while current_time < end_time:
        possible_times.append(current_time)
        current_time = current_time + timedelta(minutes=30)

    booked_times = doctor.appointments.filter(
        status=Appointment.Status.BOOKED,
        slot_time__date=date,
    ).values_list("slot_time", flat=True)

    free_slots = [t for t in possible_times if t not in booked_times]
    return free_slots
