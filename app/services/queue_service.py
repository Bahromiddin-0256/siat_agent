"""Queue management service."""
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, update

from app.database.models import (
    QueueEntry, Patient, Doctor, QueueStatus, RegistrationType
)
from app.services.availability_service import calculate_estimated_time


async def get_or_create_patient(
    session: AsyncSession,
    phone_number: str,
    name: str,
    telegram_id: Optional[int] = None
) -> Patient:
    """Get existing patient or create new one."""
    
    # Try to find existing patient by phone
    result = await session.execute(
        select(Patient).where(Patient.phone_number == phone_number)
    )
    patient = result.scalar_one_or_none()
    
    if patient:
        # Update telegram_id if provided and not set
        if telegram_id and not patient.telegram_id:
            patient.telegram_id = telegram_id
            await session.commit()
        return patient
    
    # Create new patient
    patient = Patient(
        phone_number=phone_number,
        name=name,
        telegram_id=telegram_id
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


async def add_to_queue(
    session: AsyncSession,
    doctor_id: int,
    patient_id: int,
    registration_type: RegistrationType,
    status: QueueStatus = QueueStatus.PENDING
) -> Optional[QueueEntry]:
    """Add patient to doctor's queue."""
    
    queue_date = date.today()
    
    # Check if patient already in queue for this doctor today
    result = await session.execute(
        select(QueueEntry).where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.patient_id == patient_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status.in_([QueueStatus.PENDING, QueueStatus.CONFIRMED, QueueStatus.IN_PROGRESS])
            )
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        return None  # Already in queue
    
    # Get next position
    result = await session.execute(
        select(func.max(QueueEntry.position)).where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date
            )
        )
    )
    max_position = result.scalar_one_or_none()
    next_position = (max_position or 0) + 1
    
    # Calculate estimated time
    estimated_time = await calculate_estimated_time(
        session, doctor_id, next_position, queue_date
    )
    
    # Create queue entry
    queue_entry = QueueEntry(
        doctor_id=doctor_id,
        patient_id=patient_id,
        position=next_position,
        status=status,
        registration_type=registration_type,
        estimated_time=estimated_time,
        queue_date=queue_date
    )
    
    session.add(queue_entry)
    await session.commit()
    await session.refresh(queue_entry)
    return queue_entry


async def get_doctor_queue(
    session: AsyncSession,
    doctor_id: int,
    queue_date: Optional[date] = None
) -> List[QueueEntry]:
    """Get doctor's queue for a specific date."""
    
    if queue_date is None:
        queue_date = date.today()
    
    result = await session.execute(
        select(QueueEntry)
        .where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status.in_([
                    QueueStatus.PENDING,
                    QueueStatus.CONFIRMED,
                    QueueStatus.IN_PROGRESS
                ])
            )
        )
        .order_by(QueueEntry.position)
    )
    
    return list(result.scalars().all())


async def get_patient_queue_entry(
    session: AsyncSession,
    patient_id: int,
    doctor_id: Optional[int] = None
) -> Optional[QueueEntry]:
    """Get patient's current queue entry."""
    
    query = select(QueueEntry).where(
        and_(
            QueueEntry.patient_id == patient_id,
            QueueEntry.queue_date == date.today(),
            QueueEntry.status.in_([
                QueueStatus.PENDING,
                QueueStatus.CONFIRMED,
                QueueStatus.IN_PROGRESS
            ])
        )
    )
    
    if doctor_id:
        query = query.where(QueueEntry.doctor_id == doctor_id)
    
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def update_queue_status(
    session: AsyncSession,
    queue_entry_id: int,
    new_status: QueueStatus
) -> Optional[QueueEntry]:
    """Update queue entry status."""
    
    queue_entry = await session.get(QueueEntry, queue_entry_id)
    if not queue_entry:
        return None
    
    queue_entry.status = new_status
    
    if new_status == QueueStatus.IN_PROGRESS:
        queue_entry.actual_start_time = datetime.now()
    elif new_status in [QueueStatus.COMPLETED, QueueStatus.CANCELLED, QueueStatus.NO_SHOW]:
        queue_entry.actual_end_time = datetime.now()
    
    await session.commit()
    await session.refresh(queue_entry)
    
    # If completed, update positions for remaining patients
    if new_status == QueueStatus.COMPLETED:
        await recalculate_queue_positions(session, queue_entry.doctor_id)
    
    return queue_entry


async def recalculate_queue_positions(
    session: AsyncSession,
    doctor_id: int
) -> None:
    """Recalculate queue positions and estimated times after a patient completes."""
    
    queue_date = date.today()
    
    # Get active queue entries
    queue = await get_doctor_queue(session, doctor_id, queue_date)
    
    # Recalculate positions and estimated times
    for i, entry in enumerate(queue, start=1):
        entry.position = i
        entry.estimated_time = await calculate_estimated_time(
            session, doctor_id, i, queue_date
        )
    
    await session.commit()


async def cancel_queue_entry(
    session: AsyncSession,
    queue_entry_id: int
) -> bool:
    """Cancel a queue entry."""
    
    queue_entry = await session.get(QueueEntry, queue_entry_id)
    if not queue_entry:
        return False
    
    queue_entry.status = QueueStatus.CANCELLED
    queue_entry.actual_end_time = datetime.now()
    await session.commit()
    
    # Recalculate positions
    await recalculate_queue_positions(session, queue_entry.doctor_id)
    
    return True


async def get_queue_statistics(
    session: AsyncSession,
    doctor_id: int,
    queue_date: Optional[date] = None
) -> dict:
    """Get queue statistics for a doctor."""
    
    if queue_date is None:
        queue_date = date.today()
    
    # Total patients today
    result = await session.execute(
        select(func.count(QueueEntry.id)).where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date
            )
        )
    )
    total = result.scalar_one()
    
    # Active patients (waiting)
    result = await session.execute(
        select(func.count(QueueEntry.id)).where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status.in_([QueueStatus.CONFIRMED, QueueStatus.PENDING])
            )
        )
    )
    waiting = result.scalar_one()
    
    # Completed patients
    result = await session.execute(
        select(func.count(QueueEntry.id)).where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status == QueueStatus.COMPLETED
            )
        )
    )
    completed = result.scalar_one()
    
    # In progress
    result = await session.execute(
        select(func.count(QueueEntry.id)).where(
            and_(
                QueueEntry.doctor_id == doctor_id,
                QueueEntry.queue_date == queue_date,
                QueueEntry.status == QueueStatus.IN_PROGRESS
            )
        )
    )
    in_progress = result.scalar_one()
    
    return {
        "total": total,
        "waiting": waiting,
        "completed": completed,
        "in_progress": in_progress,
        "cancelled": total - waiting - completed - in_progress
    }
