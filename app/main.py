from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import NotificationJob, Registration, Workshop
from app.schemas import (
    NotificationJobRead,
    RegistrationCreate,
    RegistrationRead,
    WorkshopCreate,
    WorkshopRead,
)

app = FastAPI(title="Workshop Registration API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def database_health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/workshops", response_model=WorkshopRead, status_code=status.HTTP_201_CREATED)
def create_workshop(data: WorkshopCreate, session: Session = Depends(get_session)) -> Workshop:
    workshop = Workshop(**data.model_dump())
    session.add(workshop)
    session.commit()
    session.refresh(workshop)
    return workshop


@app.get("/workshops", response_model=list[WorkshopRead])
def list_workshops(session: Session = Depends(get_session)) -> list[Workshop]:
    return list(session.scalars(select(Workshop).order_by(Workshop.id)))


@app.get("/workshops/{workshop_id}", response_model=WorkshopRead)
def get_workshop(workshop_id: int, session: Session = Depends(get_session)) -> Workshop:
    workshop = session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    return workshop


@app.post(
    "/workshops/{workshop_id}/registrations", response_model=RegistrationRead, status_code=201
)
def register(
    workshop_id: int, data: RegistrationCreate, session: Session = Depends(get_session)
) -> Registration:
    workshop = session.scalar(select(Workshop).where(Workshop.id == workshop_id).with_for_update())
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    if workshop.status != "active":
        raise HTTPException(status_code=409, detail="Workshop is cancelled")

    registration = Registration(workshop_id=workshop_id, member_id=data.member_id)
    job = NotificationJob(
        event_type="registration_confirmation",
        recipient=data.member_id,
        payload={"workshop_id": workshop_id, "workshop_title": workshop.title},
    )
    session.add_all([registration, job])
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Member is already registered") from exc
    session.refresh(registration)
    return registration


@app.get("/registrations/{registration_id}", response_model=RegistrationRead)
def get_registration(registration_id: int, session: Session = Depends(get_session)) -> Registration:
    registration = session.get(Registration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="Registration not found")
    return registration


@app.post("/workshops/{workshop_id}/cancel", response_model=WorkshopRead)
def cancel_workshop(workshop_id: int, session: Session = Depends(get_session)) -> Workshop:
    workshop = session.scalar(select(Workshop).where(Workshop.id == workshop_id).with_for_update())
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    if workshop.status == "cancelled":
        return workshop

    workshop.status = "cancelled"
    registrations = session.scalars(
        select(Registration).where(
            Registration.workshop_id == workshop_id, Registration.status == "registered"
        )
    ).all()
    for registration in registrations:
        session.add(
            NotificationJob(
                event_type="workshop_cancelled",
                recipient=registration.member_id,
                payload={"workshop_id": workshop_id, "workshop_title": workshop.title},
            )
        )
    session.commit()
    session.refresh(workshop)
    return workshop


@app.get("/notification-jobs", response_model=list[NotificationJobRead])
def list_notification_jobs(session: Session = Depends(get_session)) -> list[NotificationJob]:
    return list(session.scalars(select(NotificationJob).order_by(NotificationJob.id)))
