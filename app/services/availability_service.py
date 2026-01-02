"""Doctor availability service."""
from datetime import date, time, datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import (
    Doctor, DoctorWeeklySchedule, 
    DoctorScheduleOverride, DefaultClinicSchedule
)


class AvailabilitySchedule:
    """Represents doctor's availability for a specific date."""
    
    def __init__(
        self,
        is_working: bool,
        start_time: Optional[time] = None,
        end_time: Optional[time] = None,
        break_start: Optional[time] = None,
        break_end: Optional[time] = None,
        reason: Optional[str] = None
    ):
        self.is_working = is_working
        self.start_time = start_time
        self.end_time = end_time
        self.break_start = break_start
        self.break_end = break_end
        self.reason = reason


async def get_doctor_availability(
    session: AsyncSession, 
    doctor_id: int, 
    target_date: date
) -> AvailabilitySchedule:
    """
    Get doctor's availability for a specific date.
    Priority: Date Override > Weekly Schedule > Default Clinic Hours
    """
    
    # 1. Check for date-specific override
    result = await session.execute(
        select(DoctorScheduleOverride)
        .where(DoctorScheduleOverride.doctor_id == doctor_id)
        .where(DoctorScheduleOverride.date == target_date)
    )
    override = result.scalar_one_or_none()
    
    if override:
        return AvailabilitySchedule(
            is_working=override.is_working,
            start_time=override.start_time,
            end_time=override.end_time,
            break_start=override.break_start,
            break_end=override.break_end,
            reason=override.reason
        )
    
    # 2. Check doctor's custom weekly schedule
    doctor = await session.get(Doctor, doctor_id)
    if doctor and doctor.uses_custom_schedule:
        weekday = target_date.weekday()
        result = await session.execute(
            select(DoctorWeeklySchedule)
            .where(DoctorWeeklySchedule.doctor_id == doctor_id)
            .where(DoctorWeeklySchedule.weekday == weekday)
        )
        schedule = result.scalar_one_or_none()
        
        if schedule:
            return AvailabilitySchedule(
                is_working=schedule.is_working_day,
                start_time=schedule.start_time,
                end_time=schedule.end_time,
                break_start=schedule.break_start,
                break_end=schedule.break_end
            )
    
    # 3. Fall back to default clinic hours
    weekday = target_date.weekday()
    result = await session.execute(
        select(DefaultClinicSchedule)
        .where(DefaultClinicSchedule.weekday == weekday)
    )
    default = result.scalar_one_or_none()
    
    if default:
        return AvailabilitySchedule(
            is_working=default.is_working_day,
            start_time=default.start_time,
            end_time=default.end_time,
            break_start=default.break_start,
            break_end=default.break_end
        )
    
    # Ultimate fallback - not working
    return AvailabilitySchedule(is_working=False)


async def is_doctor_available_now(
    session: AsyncSession,
    doctor_id: int
) -> tuple[bool, str]:
    """
    Check if doctor is currently available.
    Returns (is_available, message in Uzbek).
    """
    
    now = datetime.now()
    availability = await get_doctor_availability(session, doctor_id, now.date())
    
    if not availability.is_working:
        if availability.reason:
            return False, f"Shifokor bugun qabul qilmaydi ({availability.reason})"
        return False, "Shifokor bugun qabul qilmaydi"
    
    current_time = now.time()
    
    if current_time < availability.start_time:
        return False, f"Shifokor soat {availability.start_time.strftime('%H:%M')} da ishni boshlaydi"
    
    if current_time > availability.end_time:
        return False, "Shifokor ish vaqti tugagan"
    
    if availability.break_start and availability.break_end:
        if availability.break_start <= current_time <= availability.break_end:
            return False, f"Shifokor tushlik tanaffusida. Soat {availability.break_end.strftime('%H:%M')} dan keyin urinib ko'ring"
    
    return True, "Mavjud"


async def calculate_estimated_time(
    session: AsyncSession,
    doctor_id: int,
    queue_position: int,
    queue_date: date
) -> Optional[datetime]:
    """
    Calculate estimated time for a patient based on their queue position.
    Returns None if estimated time is outside working hours.
    """
    
    # Get doctor's average duration
    doctor = await session.get(Doctor, doctor_id)
    if not doctor:
        return None
    
    # Get availability for the queue date
    availability = await get_doctor_availability(session, doctor_id, queue_date)
    if not availability.is_working:
        return None
    
    # Calculate estimated minutes
    estimated_minutes = queue_position * doctor.average_duration
    
    # Start from clinic open time
    start_datetime = datetime.combine(queue_date, availability.start_time)
    estimated_datetime = start_datetime + timedelta(minutes=estimated_minutes)
    
    # Check if estimated time is during break
    if availability.break_start and availability.break_end:
        break_start_dt = datetime.combine(queue_date, availability.break_start)
        break_end_dt = datetime.combine(queue_date, availability.break_end)
        
        if break_start_dt <= estimated_datetime <= break_end_dt:
            # Move estimated time after break
            break_duration = (break_end_dt - break_start_dt).total_seconds() / 60
            estimated_datetime += timedelta(minutes=break_duration)
    
    # Check if estimated time is beyond closing time
    end_datetime = datetime.combine(queue_date, availability.end_time)
    if estimated_datetime > end_datetime:
        return None  # Queue extends beyond working hours
    
    return estimated_datetime


def format_estimated_time(estimated_time: datetime) -> str:
    """Format estimated time in Uzbek."""
    now = datetime.now()
    
    if estimated_time.date() == now.date():
        # Same day
        time_str = estimated_time.strftime('%H:%M')
        
        # Calculate minutes until appointment
        delta = estimated_time - now
        minutes = int(delta.total_seconds() / 60)
        
        if minutes <= 0:
            return f"Hozir (soat {time_str})"
        elif minutes < 60:
            return f"Taxminan {minutes} daqiqadan keyin (soat {time_str})"
        else:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            if remaining_minutes == 0:
                return f"Taxminan {hours} soatdan keyin (soat {time_str})"
            else:
                return f"Taxminan {hours} soat {remaining_minutes} daqiqadan keyin (soat {time_str})"
    else:
        # Different day
        date_str = estimated_time.strftime('%d.%m.%Y')
        time_str = estimated_time.strftime('%H:%M')
        return f"{date_str}, soat {time_str}"
