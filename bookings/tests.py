from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.test import TestCase
from django.utils import timezone as django_timezone

from bookings.models import Appointment, Doctor
from bookings.services import (
    BookingError,
    book_appointment,
    cancel_appointment,
    get_availability,
    reschedule_appointment,
)

CLINIC_TZ = ZoneInfo("Africa/Nairobi")


class AppointmentTests(TestCase):

    def setUp(self):
        # Anchor all tests to a future date dynamically
        self.tomorrow = (django_timezone.now().astimezone(CLINIC_TZ) + timedelta(days=1)).date()

    def test_book_appointment(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )

        patient_id = 601
        slot_time = datetime.combine(self.tomorrow, time(10, 0), tzinfo=CLINIC_TZ)

        appointment = book_appointment(doctor.id, patient_id, slot_time)

        self.assertEqual(appointment.doctor, doctor)
        self.assertEqual(appointment.patient_id, patient_id)
        self.assertEqual(appointment.status, "booked")

    def test_cannot_book_same_slot_twice(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )

        slot_time = datetime.combine(self.tomorrow, time(10, 0), tzinfo=CLINIC_TZ)
        patient_id = 1

        book_appointment(doctor.id, patient_id, slot_time)

        with self.assertRaises(BookingError) as context:
            book_appointment(
                doctor.id,
                2,
                slot_time,
            )

        self.assertEqual(context.exception.code, "slot_taken")

    def test_cannot_book_outside_working_hours(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )

        # 7:00 AM on tomorrow's date — in the future, but outside working hours (9:00 - 17:00)
        slot_time = datetime.combine(self.tomorrow, time(7, 0), tzinfo=CLINIC_TZ)

        with self.assertRaises(BookingError) as context:
            book_appointment(doctor.id, 1, slot_time)

        self.assertEqual(context.exception.code, "outside_working_hours")

    def test_cannot_book_in_the_past(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )

        slot_time = django_timezone.now() - timedelta(minutes=30)

        with self.assertRaises(BookingError) as context:
            book_appointment(doctor.id, 1, slot_time)

        self.assertEqual(context.exception.code, "past_slot")

    def test_cancel_appointment(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )
        slot_time = datetime.combine(self.tomorrow, time(10, 0), tzinfo=CLINIC_TZ)
        appointment = book_appointment(doctor.id, 1, slot_time)

        cancelled = cancel_appointment(appointment.id, "Patient requested cancellation")

        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(
            cancelled.cancellation_reason, "Patient requested cancellation"
        )

    def test_cannot_cancel_already_cancelled_appointment(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )
        slot_time = datetime.combine(self.tomorrow, time(10, 0), tzinfo=CLINIC_TZ)
        appointment = book_appointment(doctor.id, 1, slot_time)
        cancel_appointment(appointment.id, "First cancellation")

        with self.assertRaises(BookingError) as context:
            cancel_appointment(appointment.id, "Second attempt")

        self.assertEqual(context.exception.code, "already_cancelled")

    def test_reschedule_appointment(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )
        original_slot = datetime.combine(self.tomorrow, time(10, 0), tzinfo=CLINIC_TZ)
        new_slot = datetime.combine(self.tomorrow, time(11, 0), tzinfo=CLINIC_TZ)

        appointment = book_appointment(doctor.id, 1, original_slot)

        rescheduled = reschedule_appointment(appointment.id, new_slot)

        self.assertEqual(rescheduled.status, "booked")
        self.assertEqual(rescheduled.slot_time, new_slot)
        self.assertEqual(rescheduled.doctor, doctor)
        self.assertEqual(rescheduled.patient_id, 1)

        original = Appointment.objects.get(id=appointment.id)
        self.assertEqual(original.status, "cancelled")

    def test_reschedule_fails_if_new_slot_taken(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )
        original_slot = datetime.combine(self.tomorrow, time(10, 0), tzinfo=CLINIC_TZ)
        taken_slot = datetime.combine(self.tomorrow, time(11, 0), tzinfo=CLINIC_TZ)

        appointment = book_appointment(doctor.id, 1, original_slot)
        book_appointment(doctor.id, 2, taken_slot)

        with self.assertRaises(BookingError) as context:
            reschedule_appointment(appointment.id, taken_slot)

        self.assertEqual(context.exception.code, "slot_taken")

        original = Appointment.objects.get(id=appointment.id)
        self.assertEqual(original.status, "booked")
        self.assertEqual(original.slot_time, original_slot)

    def test_get_availability_excludes_booked_slots(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(11, 0),
        )
        booked_slot = datetime.combine(self.tomorrow, time(9, 30), tzinfo=CLINIC_TZ)
        book_appointment(doctor.id, 1, booked_slot)

        free_slots = get_availability(doctor.id, self.tomorrow)

        self.assertEqual(len(free_slots), 3)
        self.assertNotIn(booked_slot, free_slots)