"""Doctor handlers for the Telegram bot."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date

from app.bot.keyboards.inline import (
    get_doctor_menu_keyboard,
    get_queue_management_keyboard,
    get_pending_registration_keyboard
)
from app.bot.keyboards.reply import get_phone_keyboard, remove_keyboard
from app.bot.states.registration import DoctorAddPatient
from app.database.connection import async_session_maker
from app.database.models import (
    Doctor, Patient, QueueEntry, QueueStatus, RegistrationType
)
from app.services.queue_service import (
    get_doctor_queue,
    update_queue_status,
    add_to_queue,
    get_or_create_patient,
    get_queue_statistics
)
from app.services.availability_service import format_estimated_time
from app.config import settings

router = Router()


async def is_doctor(telegram_id: int, session: AsyncSession) -> bool:
    """Check if user is a doctor."""
    result = await session.execute(
        select(Doctor).where(
            Doctor.telegram_id == telegram_id,
            Doctor.is_active == True
        )
    )
    doctor = result.scalar_one_or_none()
    return doctor is not None


async def get_doctor_by_telegram_id(telegram_id: int, session: AsyncSession) -> Doctor:
    """Get doctor by telegram ID."""
    result = await session.execute(
        select(Doctor).where(
            Doctor.telegram_id == telegram_id,
            Doctor.is_active == True
        )
    )
    return result.scalar_one_or_none()


@router.message(Command("doctor"))
async def doctor_panel(message: Message):
    """Show doctor panel."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(message.from_user.id, session)
        
        if not doctor:
            await message.answer(
                "❌ Sizda shifokor huquqlari yo'q.\n"
                "Iltimos, admin bilan bog'laning."
            )
            return
        
        # Get queue statistics
        stats = await get_queue_statistics(session, doctor.id)
        
        text = (
            f"👨‍⚕️ <b>Shifokor paneli - {doctor.name}</b>\n\n"
            f"📅 Bugun: {date.today().strftime('%d.%m.%Y')}\n\n"
            f"📊 <b>Statistika:</b>\n"
            f"• Navbatda: {stats['waiting']} kishi\n"
            f"• Qabulda: {stats['in_progress']} kishi\n"
            f"• Tugatilgan: {stats['completed']} kishi\n"
            f"• Jami: {stats['total']} kishi\n"
        )
        
        await message.answer(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )


@router.callback_query(F.data == "doctor_menu")
async def show_doctor_menu(callback: CallbackQuery):
    """Return to doctor menu."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.message.edit_text("❌ Sizda shifokor huquqlari yo'q.")
            await callback.answer()
            return
        
        # Get queue statistics
        stats = await get_queue_statistics(session, doctor.id)
        
        text = (
            f"👨‍⚕️ <b>Shifokor paneli - {doctor.name}</b>\n\n"
            f"📅 Bugun: {date.today().strftime('%d.%m.%Y')}\n\n"
            f"📊 <b>Statistika:</b>\n"
            f"• Navbatda: {stats['waiting']} kishi\n"
            f"• Qabulda: {stats['in_progress']} kishi\n"
            f"• Tugatilgan: {stats['completed']} kishi\n"
            f"• Jami: {stats['total']} kishi\n"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "doctor_queue")
async def show_doctor_queue(callback: CallbackQuery):
    """Show doctor's current queue."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.message.edit_text("❌ Sizda shifokor huquqlari yo'q.")
            await callback.answer()
            return
        
        # Get queue
        queue = await get_doctor_queue(session, doctor.id)
        
        if not queue:
            text = (
                f"📋 <b>Navbat bo'sh</b>\n\n"
                f"Hozirda navbatda bemorlar yo'q."
            )
        else:
            text = f"📋 <b>Sizning navbatingiz ({len(queue)} kishi)</b>\n\n"
            
            for entry in queue:
                # Get patient info
                patient = await session.get(Patient, entry.patient_id)
                
                status_emoji = {
                    QueueStatus.PENDING: "⏳",
                    QueueStatus.CONFIRMED: "✅",
                    QueueStatus.IN_PROGRESS: "🔄"
                }
                
                status_text = {
                    QueueStatus.PENDING: "Tasdiqlanmagan",
                    QueueStatus.CONFIRMED: "Tasdiqlangan",
                    QueueStatus.IN_PROGRESS: "Qabulda"
                }
                
                estimated = ""
                if entry.estimated_time:
                    estimated = f"\n   ⏰ {format_estimated_time(entry.estimated_time)}"
                
                text += (
                    f"{status_emoji.get(entry.status, 'ℹ️')} <b>#{entry.position}</b> - {patient.name}\n"
                    f"   📱 {patient.phone_number}\n"
                    f"   📊 {status_text.get(entry.status, 'Noma\'lum')}"
                    f"{estimated}\n\n"
                )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "doctor_complete")
async def complete_current_patient(callback: CallbackQuery):
    """Mark current patient as completed."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        # Get current patient (IN_PROGRESS status)
        queue = await get_doctor_queue(session, doctor.id)
        current_patient = None
        
        for entry in queue:
            if entry.status == QueueStatus.IN_PROGRESS:
                current_patient = entry
                break
        
        if not current_patient:
            await callback.answer(
                "❌ Hozirda qabulda bemor yo'q.",
                show_alert=True
            )
            return
        
        # Mark as completed
        await update_queue_status(session, current_patient.id, QueueStatus.COMPLETED)
        
        # Get patient info
        patient = await session.get(Patient, current_patient.patient_id)
        
        await callback.answer(
            f"✅ Bemor {patient.name} tugatildi.",
            show_alert=True
        )
        
        # Show updated queue
        await show_doctor_queue(callback)


@router.callback_query(F.data.startswith("start_patient_"))
async def start_patient(callback: CallbackQuery):
    """Mark patient as started (IN_PROGRESS)."""
    
    entry_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        # Update status
        entry = await update_queue_status(session, entry_id, QueueStatus.IN_PROGRESS)
        
        if entry:
            patient = await session.get(Patient, entry.patient_id)
            await callback.answer(
                f"✅ Bemor {patient.name} qabulni boshladi.",
                show_alert=True
            )
            
            # TODO: Notify patient
        else:
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
        
        await show_doctor_queue(callback)


@router.callback_query(F.data.startswith("complete_patient_"))
async def complete_patient(callback: CallbackQuery):
    """Mark patient as completed."""
    
    entry_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        # Update status
        entry = await update_queue_status(session, entry_id, QueueStatus.COMPLETED)
        
        if entry:
            patient = await session.get(Patient, entry.patient_id)
            await callback.answer(
                f"✅ Bemor {patient.name} tugatildi.",
                show_alert=True
            )
            
            # TODO: Notify patient and next in queue
        else:
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
        
        await show_doctor_queue(callback)


@router.callback_query(F.data.startswith("confirm_registration_"))
async def confirm_registration(callback: CallbackQuery):
    """Confirm pending registration."""
    
    entry_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        # Update status to CONFIRMED
        entry = await update_queue_status(session, entry_id, QueueStatus.CONFIRMED)
        
        if entry:
            patient = await session.get(Patient, entry.patient_id)
            await callback.answer(
                f"✅ {patient.name} tasdiqlandi!",
                show_alert=True
            )
            
            # TODO: Notify patient about confirmation
        else:
            await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)


@router.callback_query(F.data == "doctor_add_patient")
async def start_add_patient(callback: CallbackQuery, state: FSMContext):
    """Start adding walk-in patient."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        await state.update_data(doctor_id=doctor.id)
        
        await callback.message.edit_text(
            "➕ <b>Bemor qo'shish</b>\n\n"
            "Bemor ismini kiriting:"
        )
        
        await state.set_state(DoctorAddPatient.entering_name)
        await callback.answer()


@router.message(DoctorAddPatient.entering_name, F.text)
async def patient_name_entered(message: Message, state: FSMContext):
    """Handle patient name."""
    
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Iltimos, to'liq ismni kiriting.")
        return
    
    await state.update_data(patient_name=name)
    
    await message.answer(
        "Bemor telefon raqamini kiriting:\n"
        "(Masalan: +998901234567)"
    )
    
    await state.set_state(DoctorAddPatient.entering_phone)


@router.message(DoctorAddPatient.entering_phone, F.text)
async def patient_phone_entered(message: Message, state: FSMContext):
    """Handle patient phone and add to queue."""
    
    phone = message.text.strip()
    
    # Basic validation
    if len(phone) < 9:
        await message.answer("❌ Iltimos, to'g'ri telefon raqam kiriting.")
        return
    
    # Normalize phone
    if not phone.startswith("+"):
        if phone.startswith("998"):
            phone = f"+{phone}"
        else:
            phone = f"+998{phone}"
    
    data = await state.get_data()
    doctor_id = data["doctor_id"]
    patient_name = data["patient_name"]
    
    async with async_session_maker() as session:
        # Get or create patient
        patient = await get_or_create_patient(session, phone, patient_name)
        
        # Add to queue with CONFIRMED status (walk-in)
        queue_entry = await add_to_queue(
            session,
            doctor_id,
            patient.id,
            RegistrationType.WALK_IN,
            QueueStatus.CONFIRMED
        )
        
        if not queue_entry:
            await message.answer("❌ Bu bemor allaqachon navbatda!")
            await state.clear()
            return
        
        # Success
        estimated_text = ""
        if queue_entry.estimated_time:
            estimated_text = f"\n⏰ Taxminiy vaqt: {format_estimated_time(queue_entry.estimated_time)}"
        
        text = (
            f"✅ <b>Bemor qo'shildi!</b>\n\n"
            f"👤 Ism: {patient_name}\n"
            f"📱 Telefon: {phone}\n"
            f"📍 Navbat: #{queue_entry.position}"
            f"{estimated_text}"
        )
        
        await message.answer(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )
        
        # TODO: Notify patient if they have Telegram
        
        await state.clear()


@router.callback_query(F.data == "doctor_stats")
async def show_doctor_stats(callback: CallbackQuery):
    """Show detailed statistics."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        stats = await get_queue_statistics(session, doctor.id)
        
        text = (
            f"📊 <b>Bugungi statistika</b>\n\n"
            f"👥 Jami bemorlar: {stats['total']}\n"
            f"⏳ Navbatda: {stats['waiting']}\n"
            f"🔄 Qabulda: {stats['in_progress']}\n"
            f"✅ Tugatilgan: {stats['completed']}\n"
            f"❌ Bekor qilingan: {stats['cancelled']}\n\n"
            f"⏱️ O'rtacha vaqt: {doctor.average_duration} daqiqa"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "doctor_get_link")
async def generate_registration_link(callback: CallbackQuery):
    """Generate direct registration link."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        # TODO: Implement link generation
        text = (
            "🔗 <b>Ro'yxat havolasi</b>\n\n"
            "Ushbu xususiyat hali ishlab chiqilmoqda.\n"
            "Tez orada mavjud bo'ladi!"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "doctor_settings")
async def show_doctor_settings(callback: CallbackQuery):
    """Show doctor settings."""
    
    async with async_session_maker() as session:
        doctor = await get_doctor_by_telegram_id(callback.from_user.id, session)
        
        if not doctor:
            await callback.answer("❌ Sizda shifokor huquqlari yo'q.", show_alert=True)
            return
        
        text = (
            f"⚙️ <b>Sozlamalar</b>\n\n"
            f"👨‍⚕️ Ism: {doctor.name}\n"
            f"🏥 Mutaxassislik: {doctor.specialty or 'Ko\'rsatilmagan'}\n"
            f"⏱️ O'rtacha qabul vaqti: {doctor.average_duration} daqiqa\n"
            f"📅 Maxsus jadval: {'Ha' if doctor.uses_custom_schedule else 'Yo\'q'}\n"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_doctor_menu_keyboard()
        )
        await callback.answer()
