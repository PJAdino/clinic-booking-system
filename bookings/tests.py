from datetime import date, datetime, time, timedelta, timezone
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


class AppointmentTests(TestCase):

    def test_book_appointment(self):

        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),  # 9:00 AM
            working_end=time(17, 0),  # 5:00 PM
        )

        patient_id = 601
        slot_time = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Africa/Nairobi"))

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

        slot_time = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Africa/Nairobi"))
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

        slot_time = datetime(
            2026,
            7,
            20,
            7,
            0,  # 7:00 AM — before working_start of 9:00
            tzinfo=ZoneInfo("Africa/Nairobi"),
        )

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
        slot_time = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Africa/Nairobi"))
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
        slot_time = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Africa/Nairobi"))
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
        original_slot = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Africa/Nairobi"))
        new_slot = datetime(2026, 7, 20, 11, 0, tzinfo=ZoneInfo("Africa/Nairobi"))

        appointment = book_appointment(doctor.id, 1, original_slot)

        rescheduled = reschedule_appointment(appointment.id, new_slot)

        self.assertEqual(rescheduled.status, "booked")
        self.assertEqual(rescheduled.slot_time, new_slot)
        self.assertEqual(rescheduled.doctor, doctor)
        self.assertEqual(rescheduled.patient_id, 1)

        # confirm the original slot was actually freed (no longer a booked row blocking it)
        original = Appointment.objects.get(id=appointment.id)
        self.assertEqual(original.status, "cancelled")

    def test_reschedule_fails_if_new_slot_taken(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(17, 0),
        )
        original_slot = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Africa/Nairobi"))
        taken_slot = datetime(2026, 7, 20, 11, 0, tzinfo=ZoneInfo("Africa/Nairobi"))

        appointment = book_appointment(doctor.id, 1, original_slot)
        book_appointment(
            doctor.id, 2, taken_slot
        )  # another patient already holds 11:00

        with self.assertRaises(BookingError) as context:
            reschedule_appointment(appointment.id, taken_slot)

        self.assertEqual(context.exception.code, "slot_taken")

        # confirm the original appointment is untouched — atomicity/rollback worked
        original = Appointment.objects.get(id=appointment.id)
        self.assertEqual(original.status, "booked")
        self.assertEqual(original.slot_time, original_slot)

    def test_get_availability_excludes_booked_slots(self):
        doctor = Doctor.objects.create(
            full_name="Dr. Alice Mwangi",
            working_start=time(9, 0),
            working_end=time(
                11, 0
            ),  # small window: 9:00, 9:30, 10:00, 10:30 → 4 possible slots
        )
        booked_slot = datetime(2026, 7, 20, 9, 30, tzinfo=ZoneInfo("Africa/Nairobi"))
        book_appointment(doctor.id, 1, booked_slot)

        free_slots = get_availability(doctor.id, date(2026, 7, 20))

        self.assertEqual(len(free_slots), 3)  # 4 possible minus 1 booked
        self.assertNotIn(booked_slot, free_slots)
