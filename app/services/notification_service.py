"""Notification service for sending Telegram messages."""
from typing import Optional
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Patient, QueueEntry, Doctor
from app.services.availability_service import format_estimated_time


async def notify_patient_confirmation(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify patient that their registration is confirmed."""
    
    patient = await session.get(Patient, queue_entry.patient_id)
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    
    if not patient.telegram_id:
        return False
    
    estimated_text = ""
    if queue_entry.estimated_time:
        estimated_text = f"\n⏰ Taxminiy vaqt: {format_estimated_time(queue_entry.estimated_time)}"
    
    text = (
        "✅ <b>Navbatingiz tasdiqlandi!</b>\n\n"
        f"👨‍⚕️ Shifokor: {doctor.name}\n"
        f"📍 Navbat: #{queue_entry.position}"
        f"{estimated_text}\n\n"
        "Vaqti kelganda sizga xabar beramiz."
    )
    
    try:
        await bot.send_message(patient.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to patient {patient.id}: {e}")
        return False


async def notify_patient_position_update(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify patient about queue position update."""
    
    patient = await session.get(Patient, queue_entry.patient_id)
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    
    if not patient.telegram_id:
        return False
    
    estimated_text = ""
    if queue_entry.estimated_time:
        estimated_text = f"\n⏰ Taxminiy vaqt: {format_estimated_time(queue_entry.estimated_time)}"
    
    text = (
        "🔄 <b>Navbat yangilandi</b>\n\n"
        f"👨‍⚕️ Shifokor: {doctor.name}\n"
        f"📍 Yangi o'rningiz: #{queue_entry.position}"
        f"{estimated_text}"
    )
    
    try:
        await bot.send_message(patient.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to patient {patient.id}: {e}")
        return False


async def notify_patient_turn_approaching(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify patient that their turn is approaching."""
    
    patient = await session.get(Patient, queue_entry.patient_id)
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    
    if not patient.telegram_id:
        return False
    
    text = (
        "⏰ <b>Navbatingiz yaqinlashmoqda!</b>\n\n"
        f"Sizdan oldin {queue_entry.position - 1} kishi qoldi.\n\n"
        "Iltimos, klinikaga yaqin bo'ling!"
    )
    
    try:
        await bot.send_message(patient.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to patient {patient.id}: {e}")
        return False


async def notify_patient_turn_arrived(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify patient that it's their turn."""
    
    patient = await session.get(Patient, queue_entry.patient_id)
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    
    if not patient.telegram_id:
        return False
    
    text = (
        "🔔 <b>Sizning navbatingiz!</b>\n\n"
        f"Iltimos, {doctor.name} kabinetiga kiring.\n\n"
        "📍 Kabinet: 3-xona"
    )
    
    try:
        await bot.send_message(patient.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to patient {patient.id}: {e}")
        return False


async def notify_patient_completed(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify patient that their appointment is completed."""
    
    patient = await session.get(Patient, queue_entry.patient_id)
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    
    if not patient.telegram_id:
        return False
    
    text = (
        "✅ <b>Qabul tugallandi</b>\n\n"
        f"👨‍⚕️ Shifokor: {doctor.name}\n\n"
        "Bizni tanlaganingiz uchun rahmat!\n"
        "Tez orada ko'rishguncha! 🦷"
    )
    
    try:
        await bot.send_message(patient.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to patient {patient.id}: {e}")
        return False


async def notify_doctor_new_registration(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify doctor about new pending registration."""
    
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    patient = await session.get(Patient, queue_entry.patient_id)
    
    if not doctor.telegram_id:
        return False
    
    estimated_text = ""
    if queue_entry.estimated_time:
        estimated_text = f"\n⏰ Taxminiy vaqt: {format_estimated_time(queue_entry.estimated_time)}"
    
    text = (
        "📝 <b>Yangi ro'yxat!</b>\n\n"
        f"👤 Bemor: {patient.name}\n"
        f"📱 Telefon: {patient.phone_number}\n"
        f"📍 Navbat: #{queue_entry.position}"
        f"{estimated_text}\n\n"
        "Iltimos, bemorga qo'ng'iroq qilib tasdiqlang."
    )
    
    try:
        # TODO: Add inline buttons for confirm/reject
        await bot.send_message(doctor.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to doctor {doctor.id}: {e}")
        return False


async def notify_doctor_walk_in_added(
    bot: Bot,
    session: AsyncSession,
    queue_entry: QueueEntry
) -> bool:
    """Notify doctor about walk-in patient added by another staff member."""
    
    doctor = await session.get(Doctor, queue_entry.doctor_id)
    patient = await session.get(Patient, queue_entry.patient_id)
    
    if not doctor.telegram_id:
        return False
    
    text = (
        "➕ <b>Yangi bemor qo'shildi</b>\n\n"
        f"👤 Bemor: {patient.name}\n"
        f"📱 Telefon: {patient.phone_number}\n"
        f"📍 Navbat: #{queue_entry.position}\n"
        f"📋 Turi: Walk-in"
    )
    
    try:
        await bot.send_message(doctor.telegram_id, text)
        return True
    except Exception as e:
        print(f"Failed to send notification to doctor {doctor.id}: {e}")
        return False


async def broadcast_message(
    bot: Bot,
    session: AsyncSession,
    message: str,
    patient_ids: Optional[list[int]] = None
) -> tuple[int, int]:
    """
    Broadcast message to patients.
    Returns (success_count, failed_count).
    """
    
    from sqlalchemy import select
    from app.database.models import Patient
    
    query = select(Patient).where(Patient.telegram_id.isnot(None))
    
    if patient_ids:
        query = query.where(Patient.id.in_(patient_ids))
    
    result = await session.execute(query)
    patients = list(result.scalars().all())
    
    success_count = 0
    failed_count = 0
    
    for patient in patients:
        try:
            await bot.send_message(patient.telegram_id, message)
            success_count += 1
        except Exception as e:
            print(f"Failed to send broadcast to patient {patient.id}: {e}")
            failed_count += 1
    
    return success_count, failed_count
