"""Patient handlers for the Telegram bot."""
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.bot.keyboards.inline import (
    get_main_menu_keyboard,
    get_doctor_selection_keyboard,
    get_back_keyboard
)
from app.bot.keyboards.reply import get_phone_keyboard, remove_keyboard
from app.bot.states.registration import PatientRegistration
from app.database.connection import async_session_maker
from app.database.models import Doctor, QueueStatus, RegistrationType
from app.services.queue_service import (
    get_or_create_patient,
    add_to_queue,
    get_patient_queue_entry,
    cancel_queue_entry,
    get_doctor_queue
)
from app.services.availability_service import (
    is_doctor_available_now,
    format_estimated_time
)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start command."""
    welcome_text = (
        "🦷 <b>Stomatologiya klinikasiga xush kelibsiz!</b>\n\n"
        "Quyidagilardan birini tanlang:"
    )
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Return to main menu."""
    await state.clear()
    
    welcome_text = (
        "🦷 <b>Stomatologiya klinikasiga xush kelibsiz!</b>\n\n"
        "Quyidagilardan birini tanlang:"
    )
    
    await callback.message.edit_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    """Show help information."""
    help_text = (
        "❓ <b>Yordam</b>\n\n"
        "Bu bot stomatologiya klinikasida navbatni boshqarish uchun mo'ljallangan.\n\n"
        "<b>Asosiy imkoniyatlar:</b>\n"
        "• Shifokorni tanlash va navbatga yozilish\n"
        "• Navbatingizni kuzatish\n"
        "• Taxminiy qabul vaqtini ko'rish\n"
        "• Navbatni bekor qilish\n\n"
        "<b>Qanday foydalanish:</b>\n"
        "1. \"Ro'yxatdan o'tish\" tugmasini bosing\n"
        "2. Shifokorni tanlang\n"
        "3. Telefon raqamingizni yuboring\n"
        "4. Ismingizni kiriting\n"
        "5. Shifokor tasdiqlashini kuting\n\n"
        "Savollar bo'lsa, klinika bilan bog'laning."
    )
    
    await callback.message.edit_text(
        help_text,
        reply_markup=get_back_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "register")
async def start_registration(callback: CallbackQuery, state: FSMContext):
    """Start patient registration."""
    
    async with async_session_maker() as session:
        # Get all active doctors
        result = await session.execute(
            select(Doctor).where(Doctor.is_active == True)
        )
        doctors = list(result.scalars().all())
        
        if not doctors:
            await callback.message.edit_text(
                "❌ Hozirda shifokorlar mavjud emas.",
                reply_markup=get_back_keyboard()
            )
            await callback.answer()
            return
        
        text = "👨‍⚕️ <b>Shifokorni tanlang:</b>\n\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=get_doctor_selection_keyboard(doctors)
        )
        
        await state.set_state(PatientRegistration.selecting_doctor)
        await callback.answer()


@router.callback_query(F.data.startswith("doctor_"), PatientRegistration.selecting_doctor)
async def doctor_selected(callback: CallbackQuery, state: FSMContext):
    """Handle doctor selection."""
    
    doctor_id = int(callback.data.split("_")[1])
    
    async with async_session_maker() as session:
        doctor = await session.get(Doctor, doctor_id)
        
        if not doctor:
            await callback.message.edit_text(
                "❌ Shifokor topilmadi.",
                reply_markup=get_back_keyboard()
            )
            await callback.answer()
            return
        
        # Check if doctor is available
        is_available, message_text = await is_doctor_available_now(session, doctor_id)
        
        if not is_available:
            await callback.message.edit_text(
                f"❌ {message_text}",
                reply_markup=get_back_keyboard()
            )
            await callback.answer()
            return
        
        # Get queue info
        queue = await get_doctor_queue(session, doctor_id)
        queue_length = len(queue)
        
        await state.update_data(doctor_id=doctor_id, doctor_name=doctor.name)
        
        text = (
            f"👨‍⚕️ <b>Tanlangan shifokor:</b> {doctor.name}\n"
            f"📊 <b>Navbatda:</b> {queue_length} kishi\n\n"
            "Iltimos, telefon raqamingizni yuboring:"
        )
        
        await callback.message.delete()
        await callback.message.answer(
            text,
            reply_markup=get_phone_keyboard()
        )
        
        await state.set_state(PatientRegistration.entering_phone)
        await callback.answer()


@router.message(PatientRegistration.entering_phone, F.contact)
async def phone_received(message: Message, state: FSMContext):
    """Handle phone number."""
    
    phone_number = message.contact.phone_number
    
    # Normalize phone number
    if not phone_number.startswith("+"):
        phone_number = f"+{phone_number}"
    
    await state.update_data(
        phone_number=phone_number,
        telegram_id=message.from_user.id
    )
    
    await message.answer(
        "✅ Telefon raqam qabul qilindi.\n\n"
        "Iltimos, to'liq ismingizni kiriting:\n"
        "(Masalan: Aziz Karimov)",
        reply_markup=remove_keyboard()
    )
    
    await state.set_state(PatientRegistration.entering_name)


@router.message(PatientRegistration.entering_name, F.text)
async def name_received(message: Message, state: FSMContext):
    """Handle patient name and complete registration."""
    
    name = message.text.strip()
    
    if len(name) < 3:
        await message.answer("❌ Iltimos, to'liq ismingizni kiriting.")
        return
    
    data = await state.get_data()
    doctor_id = data["doctor_id"]
    doctor_name = data["doctor_name"]
    phone_number = data["phone_number"]
    telegram_id = data["telegram_id"]
    
    async with async_session_maker() as session:
        # Get or create patient
        patient = await get_or_create_patient(
            session, phone_number, name, telegram_id
        )
        
        # Add to queue with PENDING status (requires doctor confirmation)
        queue_entry = await add_to_queue(
            session,
            doctor_id,
            patient.id,
            RegistrationType.ONLINE,
            QueueStatus.PENDING
        )
        
        if not queue_entry:
            await message.answer(
                f"❌ Siz allaqachon {doctor_name} navbatdasiz!",
                reply_markup=get_main_menu_keyboard()
            )
            await state.clear()
            return
        
        # Success message
        estimated_text = ""
        if queue_entry.estimated_time:
            estimated_text = f"⏰ Taxminiy vaqt: {format_estimated_time(queue_entry.estimated_time)}"
        
        success_text = (
            "✅ <b>Ro'yxatdan o'tdingiz!</b>\n\n"
            f"👨‍⚕️ Shifokor: {doctor_name}\n"
            f"📍 Navbatingiz: #{queue_entry.position}\n"
            f"{estimated_text}\n\n"
            "⏳ Shifokor tasdiqlashini kuting...\n"
            "Sizga xabar yuboriladi."
        )
        
        await message.answer(
            success_text,
            reply_markup=get_main_menu_keyboard()
        )
        
        # TODO: Notify doctor about new registration
        
        await state.clear()


@router.callback_query(F.data == "my_status")
async def show_my_status(callback: CallbackQuery):
    """Show patient's current queue status."""
    
    async with async_session_maker() as session:
        telegram_id = callback.from_user.id
        
        # Find patient
        result = await session.execute(
            select(Patient).where(Patient.telegram_id == telegram_id)
        )
        patient = result.scalar_one_or_none()
        
        if not patient:
            await callback.message.edit_text(
                "❌ Siz hali ro'yxatdan o'tmagansiz.",
                reply_markup=get_back_keyboard()
            )
            await callback.answer()
            return
        
        # Get queue entry
        queue_entry = await get_patient_queue_entry(session, patient.id)
        
        if not queue_entry:
            await callback.message.edit_text(
                "ℹ️ Siz hozirda navbatda emassiz.",
                reply_markup=get_main_menu_keyboard()
            )
            await callback.answer()
            return
        
        # Get doctor info
        doctor = await session.get(Doctor, queue_entry.doctor_id)
        
        # Format status message
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
        
        estimated_text = ""
        if queue_entry.estimated_time:
            estimated_text = f"🕐 Taxminiy vaqt: {format_estimated_time(queue_entry.estimated_time)}\n"
        
        text = (
            f"{status_emoji.get(queue_entry.status, 'ℹ️')} <b>Sizning navbatingiz</b>\n\n"
            f"👨‍⚕️ Shifokor: {doctor.name}\n"
            f"📍 O'rningiz: #{queue_entry.position}\n"
            f"📊 Holat: {status_text.get(queue_entry.status, 'Noma\'lum')}\n"
            f"{estimated_text}\n"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=get_main_menu_keyboard()
        )
        await callback.answer()


@router.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery):
    """Cancel patient's registration."""
    
    async with async_session_maker() as session:
        telegram_id = callback.from_user.id
        
        # Find patient
        result = await session.execute(
            select(Patient).where(Patient.telegram_id == telegram_id)
        )
        patient = result.scalar_one_or_none()
        
        if not patient:
            await callback.message.edit_text(
                "❌ Siz hali ro'yxatdan o'tmagansiz.",
                reply_markup=get_back_keyboard()
            )
            await callback.answer()
            return
        
        # Get queue entry
        queue_entry = await get_patient_queue_entry(session, patient.id)
        
        if not queue_entry:
            await callback.message.edit_text(
                "ℹ️ Siz hozirda navbatda emassiz.",
                reply_markup=get_main_menu_keyboard()
            )
            await callback.answer()
            return
        
        # Cancel queue entry
        success = await cancel_queue_entry(session, queue_entry.id)
        
        if success:
            await callback.message.edit_text(
                "✅ Navbatingiz bekor qilindi.",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await callback.message.edit_text(
                "❌ Navbatni bekor qilishda xatolik yuz berdi.",
                reply_markup=get_main_menu_keyboard()
            )
        
        await callback.answer()


@router.callback_query(F.data == "view_queue")
async def view_queue(callback: CallbackQuery):
    """View current queue for all doctors."""
    
    async with async_session_maker() as session:
        # Get all active doctors
        result = await session.execute(
            select(Doctor).where(Doctor.is_active == True)
        )
        doctors = list(result.scalars().all())
        
        if not doctors:
            await callback.message.edit_text(
                "❌ Hozirda shifokorlar mavjud emas.",
                reply_markup=get_back_keyboard()
            )
            await callback.answer()
            return
        
        text = "📋 <b>Bugungi navbatlar:</b>\n\n"
        
        for doctor in doctors:
            queue = await get_doctor_queue(session, doctor.id)
            queue_length = len(queue)
            
            specialty = f" - {doctor.specialty}" if doctor.specialty else ""
            text += f"👨‍⚕️ <b>{doctor.name}{specialty}</b>\n"
            text += f"   📊 Navbatda: {queue_length} kishi\n\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=get_main_menu_keyboard()
        )
        await callback.answer()
