from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime
from db import Base


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    patient_name = Column(String, nullable=False)
    appointment_time = Column(DateTime, nullable=False)
    doctor_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    date = Column(Date, nullable=False)

    def to_dict(self) -> dict[str, str | int]:
        """Serialize the appointment for JSON responses."""
        return {
            "id": self.id,
            "patient_name": self.patient_name,
            "appointment_time": self.appointment_time.isoformat(),
            "doctor_name": self.doctor_name,
            "status": self.status,
        }
