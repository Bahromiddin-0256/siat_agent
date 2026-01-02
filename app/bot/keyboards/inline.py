"""Inline keyboards for the bot."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
from app.database.models import Doctor, QueueEntry


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard for patients."""
    keyboard = [
        [
            InlineKeyboardButton(text="📋 Navbatni ko'rish", callback_data="view_queue"),
            InlineKeyboardButton(text="📝 Ro'yxatdan o'tish", callback_data="register")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Mening holatim", callback_data="my_status"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_registration")
        ],
        [
            InlineKeyboardButton(text="❓ Yordam", callback_data="help")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_doctor_selection_keyboard(doctors: List[Doctor]) -> InlineKeyboardMarkup:
    """Get doctor selection keyboard."""
    keyboard = []
    
    for doctor in doctors:
        specialty = f" - {doctor.specialty}" if doctor.specialty else ""
        keyboard.append([
            InlineKeyboardButton(
                text=f"👨‍⚕️ {doctor.name}{specialty}",
                callback_data=f"doctor_{doctor.id}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Get confirmation keyboard."""
    keyboard = [
        [
            InlineKeyboardButton(text="✅ Ha", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data="confirm_no")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_doctor_menu_keyboard() -> InlineKeyboardMarkup:
    """Get doctor panel menu."""
    keyboard = [
        [
            InlineKeyboardButton(text="📋 Mening navbatim", callback_data="doctor_queue"),
            InlineKeyboardButton(text="✅ Bemor chiqdi", callback_data="doctor_complete")
        ],
        [
            InlineKeyboardButton(text="➕ Bemor qo'shish", callback_data="doctor_add_patient"),
            InlineKeyboardButton(text="🔗 Havola olish", callback_data="doctor_get_link")
        ],
        [
            InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="doctor_settings"),
            InlineKeyboardButton(text="📊 Statistika", callback_data="doctor_stats")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_queue_management_keyboard(queue_entry: QueueEntry) -> InlineKeyboardMarkup:
    """Get queue management keyboard for doctor."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Bemor kirdi",
                callback_data=f"start_patient_{queue_entry.id}"
            ),
            InlineKeyboardButton(
                text="✅ Bemor chiqdi",
                callback_data=f"complete_patient_{queue_entry.id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=f"cancel_patient_{queue_entry.id}"
            ),
            InlineKeyboardButton(
                text="📞 Qo'ng'iroq qilish",
                callback_data=f"call_patient_{queue_entry.id}"
            )
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="doctor_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_pending_registration_keyboard(queue_entry_id: int) -> InlineKeyboardMarkup:
    """Get keyboard for pending registration confirmation."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"confirm_registration_{queue_entry_id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"reject_registration_{queue_entry_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="📞 Qo'ng'iroq qilish",
                callback_data=f"call_patient_{queue_entry_id}"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Get admin panel menu."""
    keyboard = [
        [
            InlineKeyboardButton(text="👨‍⚕️ Shifokorlar", callback_data="admin_doctors"),
            InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="admin_settings")
        ],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"),
            InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Get simple back button."""
    keyboard = [
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
