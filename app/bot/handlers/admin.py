"""Admin handlers for the Telegram bot."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, time

from app.bot.keyboards.inline import get_admin_menu_keyboard, get_back_keyboard
from app.bot.states.registration import AdminAddDoctor
from app.database.connection import async_session_maker
from app.database.models import Doctor, QueueEntry, QueueStatus, DefaultClinicSchedule
from app.config import settings

router = Router()


def is_admin(telegram_id: int) -> bool:
    """Check if user is an admin."""
    return telegram_id in settings.admin_id_list


@router.message(Command("admin"))
async def admin_panel(message: Message):
    """Show admin panel."""
    
    if not is_admin(message.from_user.id):
        await message.answer(
            "❌ Sizda admin huquqlari yo'q."
        )
        return
    
    async with async_session_maker() as session:
        # Get statistics
        result = await session.execute(
            select(func.count(Doctor.id)).where(Doctor.is_active == True)
        )
        active_doctors = result.scalar_one()
        
        result = await session.execute(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.queue_date == date.today()
            )
        )
        total_patients_today = result.scalar_one()
        
        text = (
            "🔧 <b>Admin paneli</b>\n\n"
            f"👨‍⚕️ Faol shifokorlar: {active_doctors}\n"
            f"👥 Bugungi bemorlar: {total_patients_today}\n"
        )
        
        await message.answer(
            text,
            reply_markup=get_admin_menu_keyboard()
        )


@router.callback_query(F.data == "admin_doctors")
async def show_doctors(callback: CallbackQuery):
    """Show all doctors."""
    
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Sizda admin huquqlari yo'q.", show_alert=True)
        return
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(Doctor).order_by(Doctor.name)
        )
        doctors = list(result.scalars().all())
        
        if not doctors:
            text = "❌ Shifokorlar topilmadi."
        else:
            text = "👨‍⚕️ <b>Shifokorlar ro'yxati:</b>\n\n"
            
            for doctor in doctors:
                status = "✅" if doctor.is_active else "❌"
                specialty = f" - {doctor.specialty}" if doctor.specialty else ""
                telegram = f"@{doctor.telegram_id}" if doctor.telegram_id else "Telegram bog'lanmagan"
                
                text += (
                    f"{status} <b>{doctor.name}</b>{specialty}\n"
                    f"   📱 {telegram}\n"
                    f"   ⏱️ O'rtacha vaqt: {doctor.average_duration} daqiqa\n\n"
                )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_admin_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "admin_settings")
async def show_settings(callback: CallbackQuery):
    """Show system settings."""
    
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Sizda admin huquqlari yo'q.", show_alert=True)
        return
    
    text = (
        "⚙️ <b>Tizim sozlamalari</b>\n\n"
        f"⏱️ O'rtacha qabul vaqti: {settings.default_duration} daqiqa\n"
        f"🕐 Navbat yangilanish: {settings.daily_reset_time}\n"
        f"🏥 Klinika ish vaqti: {settings.clinic_open} - {settings.clinic_close}\n"
        f"🍽️ Tushlik: {settings.lunch_break_start} - {settings.lunch_break_end}\n"
        f"📊 Maksimal navbat: {settings.max_queue_size} kishi\n"
        f"🔔 Xabarnoma chegara: {settings.notification_threshold} kishi\n"
        f"🔗 Havola muddati: {settings.link_expiry_hours} soat\n"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def show_admin_stats(callback: CallbackQuery):
    """Show detailed system statistics."""
    
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Sizda admin huquqlari yo'q.", show_alert=True)
        return
    
    async with async_session_maker() as session:
        # Total doctors
        result = await session.execute(
            select(func.count(Doctor.id))
        )
        total_doctors = result.scalar_one()
        
        # Active doctors
        result = await session.execute(
            select(func.count(Doctor.id)).where(Doctor.is_active == True)
        )
        active_doctors = result.scalar_one()
        
        # Today's statistics
        result = await session.execute(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.queue_date == date.today()
            )
        )
        total_today = result.scalar_one()
        
        result = await session.execute(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.queue_date == date.today(),
                QueueEntry.status == QueueStatus.COMPLETED
            )
        )
        completed_today = result.scalar_one()
        
        result = await session.execute(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.queue_date == date.today(),
                QueueEntry.status.in_([QueueStatus.PENDING, QueueStatus.CONFIRMED])
            )
        )
        waiting_today = result.scalar_one()
        
        result = await session.execute(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.queue_date == date.today(),
                QueueEntry.status == QueueStatus.CANCELLED
            )
        )
        cancelled_today = result.scalar_one()
        
        text = (
            "📊 <b>Tizim statistikasi</b>\n\n"
            "👨‍⚕️ <b>Shifokorlar:</b>\n"
            f"• Jami: {total_doctors}\n"
            f"• Faol: {active_doctors}\n\n"
            "👥 <b>Bugungi navbat:</b>\n"
            f"• Jami: {total_today}\n"
            f"• Kutmoqda: {waiting_today}\n"
            f"• Tugatilgan: {completed_today}\n"
            f"• Bekor qilingan: {cancelled_today}\n"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_admin_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def show_broadcast_info(callback: CallbackQuery):
    """Show broadcast feature info."""
    
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Sizda admin huquqlari yo'q.", show_alert=True)
        return
    
    text = (
        "📢 <b>Xabar yuborish</b>\n\n"
        "Ushbu xususiyat barcha foydalanuvchilarga xabar yuborish imkonini beradi.\n\n"
        "Hozirda ishlab chiqilmoqda."
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_menu_keyboard()
    )
    await callback.answer()


@router.message(Command("adddoctor"))
async def add_doctor_command(message: Message, state: FSMContext):
    """Start adding a new doctor."""
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q.")
        return
    
    await message.answer(
        "➕ <b>Yangi shifokor qo'shish</b>\n\n"
        "Shifokor ismini kiriting:"
    )
    
    await state.set_state(AdminAddDoctor.entering_name)


@router.message(AdminAddDoctor.entering_name, F.text)
async def doctor_name_entered(message: Message, state: FSMContext):
    """Handle doctor name."""
    
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Iltimos, to'liq ismni kiriting.")
        return
    
    await state.update_data(doctor_name=name)
    
    await message.answer(
        "Mutaxassislikni kiriting:\n"
        "(Masalan: Umumiy stomatologiya, Ortodontiya, Jarrohlik)"
    )
    
    await state.set_state(AdminAddDoctor.entering_specialty)


@router.message(AdminAddDoctor.entering_specialty, F.text)
async def doctor_specialty_entered(message: Message, state: FSMContext):
    """Handle doctor specialty."""
    
    specialty = message.text.strip()
    
    await state.update_data(doctor_specialty=specialty)
    
    await message.answer(
        "Shifokor Telegram ID sini kiriting:\n"
        "(Shifokor @userinfobot ga /start yuborishi kerak)\n\n"
        "Yoki 0 ni kiriting (keyinroq qo'shish uchun):"
    )
    
    await state.set_state(AdminAddDoctor.entering_telegram_id)


@router.message(AdminAddDoctor.entering_telegram_id, F.text)
async def doctor_telegram_id_entered(message: Message, state: FSMContext):
    """Handle doctor telegram ID and create doctor."""
    
    telegram_id_str = message.text.strip()
    
    try:
        telegram_id = int(telegram_id_str)
    except ValueError:
        await message.answer("❌ Iltimos, to'g'ri raqam kiriting.")
        return
    
    data = await state.get_data()
    doctor_name = data["doctor_name"]
    doctor_specialty = data["doctor_specialty"]
    
    async with async_session_maker() as session:
        # Check if telegram_id already exists (if not 0)
        if telegram_id != 0:
            result = await session.execute(
                select(Doctor).where(Doctor.telegram_id == telegram_id)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                await message.answer(
                    f"❌ Bu Telegram ID allaqachon {existing.name} shifokoriga biriktirilgan."
                )
                await state.clear()
                return
        
        # Create new doctor
        doctor = Doctor(
            name=doctor_name,
            specialty=doctor_specialty,
            telegram_id=telegram_id if telegram_id != 0 else None,
            is_active=True,
            average_duration=settings.default_duration,
            uses_custom_schedule=False
        )
        
        session.add(doctor)
        await session.commit()
        await session.refresh(doctor)
        
        text = (
            "✅ <b>Shifokor muvaffaqiyatli qo'shildi!</b>\n\n"
            f"👨‍⚕️ Ism: {doctor.name}\n"
            f"🏥 Mutaxassislik: {doctor.specialty}\n"
            f"📱 Telegram ID: {doctor.telegram_id or 'Biriktirilmagan'}\n"
            f"⏱️ O'rtacha vaqt: {doctor.average_duration} daqiqa\n"
        )
        
        await message.answer(text)
        await state.clear()


@router.command(Command("init_schedule"))
async def initialize_default_schedule(message: Message):
    """Initialize default clinic schedule (admin only)."""
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q.")
        return
    
    async with async_session_maker() as session:
        # Check if already initialized
        result = await session.execute(
            select(func.count(DefaultClinicSchedule.id))
        )
        count = result.scalar_one()
        
        if count > 0:
            await message.answer("ℹ️ Default jadval allaqachon mavjud.")
            return
        
        # Create default schedule
        # Monday to Friday: 09:00 - 18:00 with lunch 13:00 - 14:00
        for weekday in range(5):  # 0-4 (Monday to Friday)
            schedule = DefaultClinicSchedule(
                weekday=weekday,
                start_time=settings.get_clinic_open_time(),
                end_time=settings.get_clinic_close_time(),
                break_start=settings.get_lunch_break_start(),
                break_end=settings.get_lunch_break_end(),
                is_working_day=True
            )
            session.add(schedule)
        
        # Saturday and Sunday: Not working
        for weekday in range(5, 7):  # 5-6 (Saturday, Sunday)
            schedule = DefaultClinicSchedule(
                weekday=weekday,
                start_time=time(9, 0),
                end_time=time(18, 0),
                break_start=None,
                break_end=None,
                is_working_day=False
            )
            session.add(schedule)
        
        await session.commit()
        
        await message.answer(
            "✅ Default klinika jadvali yaratildi!\n\n"
            "Dushanba - Juma: 09:00 - 18:00\n"
            "Tushlik: 13:00 - 14:00\n"
            "Shanba - Yakshanba: Dam olish"
        )
