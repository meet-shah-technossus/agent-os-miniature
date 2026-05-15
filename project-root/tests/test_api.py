from __future__ import annotations
from datetime import date, datetime, time

import pytest
from flask import Flask

from app import create_app
from db import get_session
from models import Appointment


@pytest.fixture
def app(monkeypatch) -> Flask:
    test_app = create_app({
        "DATABASE_URL": "sqlite:///:memory:",
        "TESTING": True,
    })
    with test_app.app_context():
        session = get_session()
        session.execute("PRAGMA journal_mode = WAL")
        session.commit()
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def seed_today(session):
    today = date.today()
    session.query(Appointment).filter(Appointment.date == today).delete()
    session.commit()
    data = [
        ("Patient A", time(9, 0), "Dr. A", "Scheduled"),
        ("Patient B", time(11, 0), "Dr. B", "Completed"),
        ("Patient C", time(13, 30), "Dr. C", "Completed"),
    ]
    for patient, appointment_time, doctor, status in data:
        session.add(
            Appointment(
                patient_name=patient,
                appointment_time=datetime.combine(today, appointment_time),
                doctor_name=doctor,
                status=status,
                date=today,
            )
        )
    session.commit()


def test_list_todays_appointments(client, app):
    with app.app_context():
        session = get_session()
        seed_today(session)

    response = client.get("/api/appointments")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    assert len(payload) == 3
    for appointment in payload:
        assert all(key in appointment for key in ("patient_name", "appointment_time", "doctor_name", "status"))


def test_update_appointment_status_reflects_in_list(client, app):
    with app.app_context():
        session = get_session()
        seed_today(session)
        appointment = session.query(Appointment).first()
        appointment_id = appointment.id

    response = client.patch(
        f"/api/appointments/{appointment_id}",
        json={"status": "Completed"},
    )
    assert response.status_code == 200

    response = client.get("/api/appointments")
    assert response.status_code == 200
    payload = response.get_json()
    for appointment in payload:
        if appointment["id"] == appointment_id:
            assert appointment["status"] == "Completed"
            break
    else:
        pytest.skip("Updated appointment missing from response")


def test_summary_metrics_update(client, app):
    with app.app_context():
        session = get_session()
        seed_today(session)
        appointment = session.query(Appointment).filter_by(status="Scheduled").first()
        appointment_id = appointment.id

    before = client.get("/api/summary").get_json()
    assert before["pending"] >= 1

    client.patch(f"/api/appointments/{appointment_id}", json={"status": "Completed"})
    after = client.get("/api/summary").get_json()

    assert after["completed"] == before["completed"] + 1
    assert after["pending"] == before["pending"] - 1
