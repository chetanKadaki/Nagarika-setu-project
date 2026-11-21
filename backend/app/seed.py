from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Complaint, ComplaintAssignment, EngineerProfile, User
from app.security import hash_password

DEMO_PASSWORD = "civic-demo-password"


def seed_demo_data(db: Session) -> None:
    if not db.scalar(select(User.id).limit(1)):
        users = [
            User(
                id="citizen-01",
                name="Ananya Rao",
                email="citizen@civic.local",
                role="citizen",
                password_hash=hash_password(DEMO_PASSWORD),
            ),
            User(
                id="engineer-01",
                name="Ravi Kumar",
                email="engineer@civic.local",
                role="engineer",
                password_hash=hash_password(DEMO_PASSWORD),
            ),
            User(
                id="verifier-01",
                name="Meera Nair",
                email="verifier@civic.local",
                role="verifier",
                password_hash=hash_password(DEMO_PASSWORD),
            ),
            User(
                id="officer-01",
                name="Kavya Menon",
                email="officer@civic.local",
                role="officer",
                password_hash=hash_password(DEMO_PASSWORD),
            ),
        ]
        db.add_all(users)
        db.flush()

    engineer = db.get(User, "engineer-01")
    if engineer is not None:
        profile = db.get(EngineerProfile, engineer.id)
        if profile is None:
            db.add(
                EngineerProfile(
                    user_id=engineer.id,
                    department="Public Works",
                    registration_number="ENG-DEMO-001",
                    skills=["Road maintenance", "Public infrastructure"],
                    application_note="Development demo engineer with approved credentials.",
                    registration_status="APPROVED",
                )
            )
        else:
            profile.registration_status = "APPROVED"
        engineer.role = "engineer"

    if not db.scalar(select(Complaint.id).limit(1)):
        rows = [
            ("CP-2048", "Pothole on 12th Main Road", "Deep pothole causing congestion near the bus stop.", "Roads & pavements", "High", "IN_PROGRESS", "Ward 18 · Indiranagar", "12th Main Road, Indiranagar", 12.9717, 77.6406, "Public Works", "IN_PROGRESS", "NOT_SUBMITTED"),
            ("CP-2047", "Water leaking at street junction", "Water is flowing onto the road near the corner shop.", "Water & drainage", "Critical", "AWAITING_VERIFICATION", "Ward 12 · Malleshwaram", "Sampige Road, Malleshwaram", 13.0068, 77.5694, "Water Supply", "SUBMITTED_FOR_VERIFICATION", "PENDING_REVIEW"),
            ("CP-2046", "Street light out near park", "The light has not worked for several evenings.", "Street lighting", "Medium", "ASSIGNED", "Ward 18 · Indiranagar", "CMH Park entrance, Indiranagar", 12.9782, 77.6401, "Electrical", "NOT_STARTED", "NOT_SUBMITTED"),
            ("CP-2045", "Blocked storm water drain", "Water collects by the crossing during heavy rain.", "Water & drainage", "High", "UNDER_REVIEW", "Ward 14 · Jayanagar", "4th Block, Jayanagar", 12.9253, 77.5838, "Water Supply", "NOT_STARTED", "NOT_SUBMITTED"),
            ("CP-2044", "Uncollected waste near market", "Waste has been left outside the collection point.", "Waste management", "Medium", "OFFICIALLY_COMPLETED", "Ward 18 · Indiranagar", "100 Feet Road, Indiranagar", 12.9705, 77.6459, "Solid Waste", "WORK_DONE", "APPROVED"),
            ("CP-2043", "Uneven pavement by school", "Several pavement blocks have lifted by the school gate.", "Roads & pavements", "Low", "ASSIGNED", "Ward 10 · Basavanagudi", "Bull Temple Road, Basavanagudi", 12.9436, 77.5681, "Public Works", "NOT_STARTED", "NOT_SUBMITTED"),
            ("CP-2042", "Low water pressure on street", "Multiple homes have reduced water pressure this week.", "Water & drainage", "High", "IN_PROGRESS", "Ward 12 · Malleshwaram", "8th Cross, Malleshwaram", 13.0014, 77.5712, "Water Supply", "IN_PROGRESS", "NOT_SUBMITTED"),
        ]
        created_at = datetime.now(timezone.utc)
        db.add_all(
            [
                Complaint(
                    id=reference.lower(),
                    reference=reference,
                    title=title,
                    description=description,
                    category=category,
                    severity=severity,
                    official_status=status,
                    engineer_work_status=work_status,
                    verification_status=verification_status,
                    ward=ward,
                    address=address,
                    latitude=latitude,
                    longitude=longitude,
                    department=department,
                    citizen_id="citizen-01",
                    engineer_id="engineer-01" if work_status in {"IN_PROGRESS", "SUBMITTED_FOR_VERIFICATION", "WORK_DONE"} else None,
                    verifier_id=(
                        "verifier-01"
                        if work_status in {"IN_PROGRESS", "SUBMITTED_FOR_VERIFICATION", "WORK_DONE"}
                        else None
                    ),
                    is_demo=True,
                    created_at=created_at,
                )
                for (
                    reference,
                    title,
                    description,
                    category,
                    severity,
                    status,
                    ward,
                    address,
                    latitude,
                    longitude,
                    department,
                    work_status,
                    verification_status,
                ) in rows
            ]
        )
    db.flush()
    demo_verifier = db.get(User, "verifier-01")
    demo_complaints = list(
        db.scalars(
            select(Complaint).where(
                Complaint.is_demo.is_(True),
                Complaint.engineer_id.is_not(None),
            )
        )
    )
    if demo_verifier is not None:
        for complaint in demo_complaints:
            if complaint.verifier_id is None:
                complaint.verifier_id = demo_verifier.id
    db.flush()
    existing_assignments = set(db.scalars(select(ComplaintAssignment.complaint_id)))
    db.add_all(
        [
            ComplaintAssignment(
                id=f"seed-assignment-{complaint.id}",
                complaint_id=complaint.id,
                engineer_id=complaint.engineer_id,
                verifier_id=complaint.verifier_id,
                assigned_by="officer-01",
            )
            for complaint in demo_complaints
            if complaint.verifier_id is not None and complaint.id not in existing_assignments
        ]
    )
    db.commit()
