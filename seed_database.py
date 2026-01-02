"""Database seeder for initial data and testing."""
import asyncio
from datetime import time, date, timedelta

from app.database.connection import init_db, async_session_maker
from app.database.models import (
    Doctor, Patient, DefaultClinicSchedule, DoctorWeeklySchedule,
    Setting
)
from app.config import settings


async def seed_default_schedule():
    """Seed default clinic schedule."""
    print("📅 Seeding default clinic schedule...")
    
    async with async_session_maker() as session:
        # Check if already exists
        from sqlalchemy import select, func
        result = await session.execute(
            select(func.count(DefaultClinicSchedule.id))
        )
        count = result.scalar_one()
        
        if count > 0:
            print("  ℹ️  Default schedule already exists, skipping...")
            return
        
        # Monday to Friday: 09:00 - 18:00 with lunch 13:00 - 14:00
        for weekday in range(5):
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
        for weekday in range(5, 7):
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
        print("  ✅ Default schedule created")


async def seed_sample_doctors():
    """Seed sample doctors for testing."""
    print("👨‍⚕️ Seeding sample doctors...")
    
    async with async_session_maker() as session:
        # Check if doctors already exist
        from sqlalchemy import select, func
        result = await session.execute(
            select(func.count(Doctor.id))
        )
        count = result.scalar_one()
        
        if count > 0:
            print(f"  ℹ️  {count} doctors already exist, skipping...")
            return
        
        # Create sample doctors
        doctors_data = [
            {
                "name": "Dr. Ahmad Karimov",
                "specialty": "Umumiy stomatologiya",
                "average_duration": 20
            },
            {
                "name": "Dr. Malika Azimova",
                "specialty": "Ortodontiya",
                "average_duration": 30
            },
            {
                "name": "Dr. Botir Rahimov",
                "specialty": "Jarrohlik",
                "average_duration": 45
            },
            {
                "name": "Dr. Dilnoza Yusupova",
                "specialty": "Bolalar stomatologiyasi",
                "average_duration": 25
            }
        ]
        
        for doctor_data in doctors_data:
            doctor = Doctor(
                name=doctor_data["name"],
                specialty=doctor_data["specialty"],
                average_duration=doctor_data["average_duration"],
                is_active=True,
                uses_custom_schedule=False
            )
            session.add(doctor)
        
        await session.commit()
        print(f"  ✅ Created {len(doctors_data)} sample doctors")


async def seed_sample_patients():
    """Seed sample patients for testing."""
    print("👥 Seeding sample patients...")
    
    async with async_session_maker() as session:
        # Check if patients already exist
        from sqlalchemy import select, func
        result = await session.execute(
            select(func.count(Patient.id))
        )
        count = result.scalar_one()
        
        if count > 0:
            print(f"  ℹ️  {count} patients already exist, skipping...")
            return
        
        # Create sample patients
        patients_data = [
            {"name": "Aziz Karimov", "phone": "+998901234567"},
            {"name": "Madina Saidova", "phone": "+998901234568"},
            {"name": "Sardor Toshmatov", "phone": "+998901234569"},
            {"name": "Nilufar Abdullayeva", "phone": "+998901234570"},
            {"name": "Javohir Alimov", "phone": "+998901234571"},
        ]
        
        for patient_data in patients_data:
            patient = Patient(
                name=patient_data["name"],
                phone_number=patient_data["phone"]
            )
            session.add(patient)
        
        await session.commit()
        print(f"  ✅ Created {len(patients_data)} sample patients")


async def seed_settings():
    """Seed system settings."""
    print("⚙️ Seeding system settings...")
    
    async with async_session_maker() as session:
        # Check if settings already exist
        from sqlalchemy import select, func
        result = await session.execute(
            select(func.count(Setting.key))
        )
        count = result.scalar_one()
        
        if count > 0:
            print(f"  ℹ️  {count} settings already exist, skipping...")
            return
        
        # Create default settings
        settings_data = [
            {
                "key": "default_duration",
                "value": str(settings.default_duration),
                "description": "O'rtacha qabul vaqti (daqiqada)"
            },
            {
                "key": "daily_reset_time",
                "value": settings.daily_reset_time,
                "description": "Navbat yangilanish vaqti"
            },
            {
                "key": "clinic_open",
                "value": settings.clinic_open,
                "description": "Klinika ochilish vaqti"
            },
            {
                "key": "clinic_close",
                "value": settings.clinic_close,
                "description": "Klinika yopilish vaqti"
            },
            {
                "key": "max_queue_size",
                "value": str(settings.max_queue_size),
                "description": "Kunlik maksimal navbat"
            },
            {
                "key": "notification_threshold",
                "value": str(settings.notification_threshold),
                "description": "Xabarnoma yuborish (X kishi qolganda)"
            }
        ]
        
        for setting_data in settings_data:
            setting = Setting(**setting_data)
            session.add(setting)
        
        await session.commit()
        print(f"  ✅ Created {len(settings_data)} settings")


async def main():
    """Main seeder function."""
    print("🌱 Starting database seeding...\n")
    
    # Initialize database
    await init_db()
    print("✅ Database initialized\n")
    
    # Seed data
    await seed_default_schedule()
    await seed_sample_doctors()
    await seed_sample_patients()
    await seed_settings()
    
    print("\n✅ Database seeding completed!")
    print("\nYou can now:")
    print("  1. Start the bot: python -m app.main")
    print("  2. Add admin by setting ADMIN_IDS in .env")
    print("  3. Link doctors to Telegram accounts using /adddoctor")


if __name__ == "__main__":
    asyncio.run(main())
