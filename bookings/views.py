from datetime import datetime
from django.utils.dateparse import parse_datetime
from bookings.services import (
    BookingError,
    book_appointment,
    cancel_appointment,
    get_availability,
    reschedule_appointment,
)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

ERROR_STATUS_MAP = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "slot_taken": status.HTTP_409_CONFLICT,
    "already_cancelled": status.HTTP_409_CONFLICT,
    "past_slot": status.HTTP_400_BAD_REQUEST,
    "outside_working_hours": status.HTTP_400_BAD_REQUEST,
}


class AppointmentsView(APIView):
    def post(self, request):
        doctor_id = request.data.get("doctor_id")
        patient_id = request.data.get("patient_id")
        slot_time = request.data.get("slot_time")

        try:
            appointment = book_appointment(doctor_id, patient_id, slot_time)
        except BookingError as e:
            return Response(
                {"error": e.message}, status=ERROR_STATUS_MAP.get(e.code, 400)
            )

        return Response(
            {
                "id": appointment.id,
                "doctor": appointment.doctor.full_name,
                "slot_time": appointment.slot_time,
                "patient_id": appointment.patient_id,
            },
            status=status.HTTP_201_CREATED,
        )


class DoctorAvailabilityView(APIView):
    def get(self, request, doctor_id):
        date_str = request.query_params.get("date")
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        free_slots = get_availability(doctor_id, date)

        return Response(
            {"Available Slots": [t.isoformat() for t in free_slots]},
            status=status.HTTP_200_OK,
        )


class AppointmentCancelView(APIView):
    def patch(self, request, appointment_id):
        reason = request.data.get("reason")

        try:
            appointment = cancel_appointment(appointment_id, reason)
        except BookingError as e:
            return Response(
                {"error": e.message}, status=ERROR_STATUS_MAP.get(e.code, 400)
            )

        return Response(
            {
                "id": appointment.id,
                "doctor": appointment.doctor.full_name,
                "slot_time": appointment.slot_time,
                "patient_id": appointment.patient_id,
                "reason": reason,
                "status": appointment.status,
            },
            status=status.HTTP_200_OK,
        )


class AppointmentRescheduleView(APIView):
    def patch(self, request, appointment_id):
        new_slot_time = parse_datetime(request.data.get("new_slot_time"))

        try:
            appointment = reschedule_appointment(appointment_id, new_slot_time)
        except BookingError as e:
            return Response(
                {"error": e.message}, status=ERROR_STATUS_MAP.get(e.code, 400)
            )

        return Response(
            {
                "id": appointment.id,
                "doctor": appointment.doctor.full_name,
                "slot_time": appointment.slot_time,
                "patient_id": appointment.patient_id,
                "status": appointment.status,
            },
            status=status.HTTP_200_OK,
        )
    
class HealthCheckView(APIView):
    def get(self, request):
        return Response(
            {"status": "ok", "service": "Clinic Booking API"},
            status=status.HTTP_200_OK,
        )    
