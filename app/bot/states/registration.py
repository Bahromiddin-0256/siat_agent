"""Registration states for FSM."""
from aiogram.fsm.state import State, StatesGroup


class PatientRegistration(StatesGroup):
    """Patient registration states."""
    selecting_doctor = State()
    entering_phone = State()
    entering_name = State()


class DoctorAddPatient(StatesGroup):
    """Doctor adding walk-in patient states."""
    entering_name = State()
    entering_phone = State()


class AdminAddDoctor(StatesGroup):
    """Admin adding doctor states."""
    entering_name = State()
    entering_specialty = State()
    entering_telegram_id = State()


class DoctorSchedule(StatesGroup):
    """Doctor schedule configuration states."""
    selecting_day = State()
    setting_start_time = State()
    setting_end_time = State()
    setting_break_start = State()
    setting_break_end = State()
