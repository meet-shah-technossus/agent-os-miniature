from __future__ import annotations
from datetime import date as _date, datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from db import get_session
from models import Appointment

api_bp = Blueprint("api", __name__, url_prefix="/api")
ALLOWED_STATUSES = {"Scheduled", "Completed", "Cancelled"}


def _parse_date(date_str: str | None) -> _date:
    if not date_str:
        return _date.today()
    try:
        return _date.fromisoformat(date_str)
    except ValueError:
        raise ValueError("Invalid date format. Please use YYYY-MM-DD.")


@api_bp.route("/appointments", methods=["GET"])
def list_appointments() -> Any:
    target_date = _parse_date(request.args.get("date"))
    session = get_session()
    appointments = (
        session.query(Appointment)
        .filter(Appointment.date == target_date)
        .order_by(Appointment.appointment_time)
        .all()
    )
    return jsonify([appointment.to_dict() for appointment in appointments])


@api_bp.route("/appointments/<int:appointment_id>", methods=["PATCH"])
def update_appointment(appointment_id: int) -> Any:
    payload = request.get_json(force=True, silent=True)
    if not payload or "status" not in payload:
        return jsonify({"message": "Missing status"}), 400

    new_status = payload["status"]
    if new_status not in ALLOWED_STATUSES:
        return jsonify({"message": "Invalid status"}), 400

    session = get_session()
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return jsonify({"message": "Appointment not found"}), 404

    appointment.status = new_status
    session.commit()
    return jsonify(appointment.to_dict())


@api_bp.route("/summary", methods=["GET"])
def summary() -> Any:
    target_date = _parse_date(request.args.get("date"))
    session = get_session()
    total = (
        session.query(func.count(Appointment.id))
        .filter(Appointment.date == target_date)
        .scalar()
    )
    completed = (
        session.query(func.count(Appointment.id))
        .filter(Appointment.date == target_date, Appointment.status == "Completed")
        .scalar()
    )
    pending = (
        session.query(func.count(Appointment.id))
        .filter(Appointment.date == target_date, Appointment.status == "Scheduled")
        .scalar()
    )

    return jsonify({
        "total": int(total or 0),
        "completed": int(completed or 0),
        "pending": int(pending or 0),
    })
