from django.urls import path

from bookings.views import (
    AppointmentCancelView,
    AppointmentRescheduleView,
    AppointmentsView,
    DoctorAvailabilityView,
)


urlpatterns = [
    path("appointments/", AppointmentsView.as_view()),
    path("doctors/<int:doctor_id>/availability", DoctorAvailabilityView.as_view()),
    path("appointments/<int:appointment_id>/cancel", AppointmentCancelView.as_view()),
    path(
        "appointments/<int:appointment_id>/reschedule",
        AppointmentRescheduleView.as_view(),
    ),
]
