from __future__ import annotations
from datetime import date, datetime, time

from app import create_app
from db import get_session
from models import Appointment


def seed_appointments() -> None:
    app = create_app({"TESTING": False})
    with app.app_context():
        session = get_session()
        today = date.today()
        session.query(Appointment).filter(Appointment.date == today).delete()
        session.commit()

        samples = [
            ("Harper Lee", time(9, 0), "Dr. Nguyen", "Scheduled"),
            ("Amelia Earhart", time(10, 30), "Dr. Patel", "Completed"),
            ("Isaac Newton", time(12, 15), "Dr. Wu", "Scheduled"),
            ("Emilia Clarke", time(14, 0), "Dr. Morris", "Cancelled"),
            ("Katherine Johnson", time(15, 45), "Dr. Singh", "Scheduled"),
        ]

        appointments = [
            Appointment(
                patient_name=name,
                appointment_time=datetime.combine(today, when),
                doctor_name=doctor,
                status=status,
                date=today,
            )
            for name, when, doctor, status in samples
        ]

        session.add_all(appointments)
        session.commit()


if __name__ == "__main__":
    seed_appointments()
