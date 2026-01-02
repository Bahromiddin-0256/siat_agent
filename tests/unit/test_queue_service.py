"""Test queue service functionality."""
import pytest
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Doctor, Patient, QueueEntry, QueueStatus, RegistrationType
)
from app.services.queue_service import (
    get_or_create_patient,
    add_to_queue,
    get_doctor_queue,
    update_queue_status,
    recalculate_queue_positions,
    cancel_queue_entry,
    get_queue_statistics
)


@pytest.mark.asyncio
async def test_get_or_create_patient_new(session: AsyncSession):
    """Test creating a new patient."""
    patient = await get_or_create_patient(
        session,
        phone_number="+998901234567",
        name="Test Patient",
        telegram_id=123456789
    )
    
    assert patient.id is not None
    assert patient.phone_number == "+998901234567"
    assert patient.name == "Test Patient"
    assert patient.telegram_id == 123456789


@pytest.mark.asyncio
async def test_get_or_create_patient_existing(session: AsyncSession):
    """Test getting an existing patient."""
    # Create first patient
    patient1 = await get_or_create_patient(
        session,
        phone_number="+998901234567",
        name="Test Patient",
    )
    
    # Get same patient
    patient2 = await get_or_create_patient(
        session,
        phone_number="+998901234567",
        name="Updated Name",
        telegram_id=987654321
    )
    
    assert patient1.id == patient2.id
    assert patient2.telegram_id == 987654321


@pytest.mark.asyncio
async def test_add_to_queue(session: AsyncSession, sample_doctor: Doctor, sample_patient: Patient):
    """Test adding patient to queue."""
    queue_entry = await add_to_queue(
        session,
        doctor_id=sample_doctor.id,
        patient_id=sample_patient.id,
        registration_type=RegistrationType.ONLINE,
        status=QueueStatus.PENDING
    )
    
    assert queue_entry is not None
    assert queue_entry.position == 1
    assert queue_entry.status == QueueStatus.PENDING
    assert queue_entry.queue_date == date.today()


@pytest.mark.asyncio
async def test_add_to_queue_duplicate(session: AsyncSession, sample_doctor: Doctor, sample_patient: Patient):
    """Test preventing duplicate queue entries."""
    # Add first time
    entry1 = await add_to_queue(
        session,
        doctor_id=sample_doctor.id,
        patient_id=sample_patient.id,
        registration_type=RegistrationType.ONLINE,
        status=QueueStatus.CONFIRMED
    )
    
    # Try to add again
    entry2 = await add_to_queue(
        session,
        doctor_id=sample_doctor.id,
        patient_id=sample_patient.id,
        registration_type=RegistrationType.ONLINE,
        status=QueueStatus.CONFIRMED
    )
    
    assert entry1 is not None
    assert entry2 is None


@pytest.mark.asyncio
async def test_get_doctor_queue(session: AsyncSession, sample_doctor: Doctor):
    """Test getting doctor's queue."""
    # Create patients and add to queue
    for i in range(3):
        patient = Patient(
            name=f"Patient {i}",
            phone_number=f"+99890123456{i}"
        )
        session.add(patient)
        await session.commit()
        
        await add_to_queue(
            session,
            doctor_id=sample_doctor.id,
            patient_id=patient.id,
            registration_type=RegistrationType.ONLINE,
            status=QueueStatus.CONFIRMED
        )
    
    # Get queue
    queue = await get_doctor_queue(session, sample_doctor.id)
    
    assert len(queue) == 3
    assert queue[0].position == 1
    assert queue[1].position == 2
    assert queue[2].position == 3


@pytest.mark.asyncio
async def test_update_queue_status(session: AsyncSession, sample_doctor: Doctor, sample_patient: Patient):
    """Test updating queue entry status."""
    # Add to queue
    entry = await add_to_queue(
        session,
        doctor_id=sample_doctor.id,
        patient_id=sample_patient.id,
        registration_type=RegistrationType.ONLINE,
        status=QueueStatus.PENDING
    )
    
    # Update to IN_PROGRESS
    updated = await update_queue_status(
        session,
        entry.id,
        QueueStatus.IN_PROGRESS
    )
    
    assert updated.status == QueueStatus.IN_PROGRESS
    assert updated.actual_start_time is not None
    
    # Update to COMPLETED
    completed = await update_queue_status(
        session,
        entry.id,
        QueueStatus.COMPLETED
    )
    
    assert completed.status == QueueStatus.COMPLETED
    assert completed.actual_end_time is not None


@pytest.mark.asyncio
async def test_cancel_queue_entry(session: AsyncSession, sample_doctor: Doctor, sample_patient: Patient):
    """Test canceling a queue entry."""
    # Add to queue
    entry = await add_to_queue(
        session,
        doctor_id=sample_doctor.id,
        patient_id=sample_patient.id,
        registration_type=RegistrationType.ONLINE,
        status=QueueStatus.CONFIRMED
    )
    
    # Cancel
    success = await cancel_queue_entry(session, entry.id)
    
    assert success is True
    
    # Refresh entry
    await session.refresh(entry)
    assert entry.status == QueueStatus.CANCELLED


@pytest.mark.asyncio
async def test_get_queue_statistics(session: AsyncSession, sample_doctor: Doctor):
    """Test getting queue statistics."""
    # Create various queue entries
    statuses = [
        QueueStatus.CONFIRMED,
        QueueStatus.CONFIRMED,
        QueueStatus.IN_PROGRESS,
        QueueStatus.COMPLETED,
        QueueStatus.CANCELLED
    ]
    
    for i, status in enumerate(statuses):
        patient = Patient(
            name=f"Patient {i}",
            phone_number=f"+99890123456{i}"
        )
        session.add(patient)
        await session.commit()
        
        await add_to_queue(
            session,
            doctor_id=sample_doctor.id,
            patient_id=patient.id,
            registration_type=RegistrationType.ONLINE,
            status=status
        )
    
    # Get statistics
    stats = await get_queue_statistics(session, sample_doctor.id)
    
    assert stats['total'] == 5
    assert stats['waiting'] == 2  # CONFIRMED
    assert stats['in_progress'] == 1
    assert stats['completed'] == 1
    assert stats['cancelled'] == 1
