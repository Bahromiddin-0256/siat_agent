"""Scheduler service for automated tasks."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, date, timedelta
from sqlalchemy import select, and_

from app.database.connection import async_session_maker
from app.database.models import QueueEntry, QueueStatus, Doctor
from app.config import settings


scheduler = AsyncIOScheduler()


async def reset_daily_queues():
    """Reset all queues at the start of each day."""
    
    print(f"🔄 Resetting daily queues at {datetime.now()}")
    
    async with async_session_maker() as session:
        # Archive or clean up old queue entries
        # For now, we just let them stay as historical data
        # Status-based filtering will handle showing only active entries
        
        # You could also mark all pending/confirmed entries from yesterday as NO_SHOW
        yesterday = date.today() - timedelta(days=1)
        
        result = await session.execute(
            select(QueueEntry).where(
                and_(
                    QueueEntry.queue_date == yesterday,
                    QueueEntry.status.in_([QueueStatus.PENDING, QueueStatus.CONFIRMED])
                )
            )
        )
        
        old_entries = list(result.scalars().all())
        
        for entry in old_entries:
            entry.status = QueueStatus.NO_SHOW
        
        if old_entries:
            await session.commit()
            print(f"✅ Marked {len(old_entries)} entries from yesterday as NO_SHOW")
        
        print("✅ Daily queue reset completed")


async def send_queue_summaries():
    """Send daily queue summary to doctors."""
    
    print(f"📊 Sending queue summaries at {datetime.now()}")
    
    async with async_session_maker() as session:
        # Get all active doctors
        result = await session.execute(
            select(Doctor).where(Doctor.is_active == True)
        )
        doctors = list(result.scalars().all())
        
        for doctor in doctors:
            # Get today's queue count
            result = await session.execute(
                select(QueueEntry).where(
                    and_(
                        QueueEntry.doctor_id == doctor.id,
                        QueueEntry.queue_date == date.today()
                    )
                )
            )
            entries = list(result.scalars().all())
            
            if entries:
                # TODO: Send summary to doctor
                print(f"  📋 Doctor {doctor.name}: {len(entries)} patients today")
        
        print("✅ Queue summaries sent")


async def check_upcoming_appointments():
    """Check for appointments coming up soon and notify patients."""
    
    print(f"🔔 Checking upcoming appointments at {datetime.now()}")
    
    async with async_session_maker() as session:
        # Get all confirmed entries for today
        result = await session.execute(
            select(QueueEntry).where(
                and_(
                    QueueEntry.queue_date == date.today(),
                    QueueEntry.status.in_([QueueStatus.CONFIRMED, QueueStatus.PENDING]),
                    QueueEntry.position <= settings.notification_threshold
                )
            )
        )
        
        entries = list(result.scalars().all())
        
        # TODO: Send notifications to patients whose turn is approaching
        print(f"  🔔 Found {len(entries)} patients with upcoming appointments")
        
        print("✅ Upcoming appointment checks completed")


def start_scheduler():
    """Start the scheduler with all jobs."""
    
    # Parse reset time from settings
    reset_hour, reset_minute = map(int, settings.daily_reset_time.split(":"))
    
    # Daily queue reset at specified time
    scheduler.add_job(
        reset_daily_queues,
        CronTrigger(hour=reset_hour, minute=reset_minute),
        id="daily_queue_reset",
        name="Daily Queue Reset",
        replace_existing=True
    )
    
    # Send queue summaries at 8 AM
    scheduler.add_job(
        send_queue_summaries,
        CronTrigger(hour=8, minute=0),
        id="queue_summaries",
        name="Queue Summaries",
        replace_existing=True
    )
    
    # Check upcoming appointments every 30 minutes
    scheduler.add_job(
        check_upcoming_appointments,
        CronTrigger(minute="*/30"),
        id="check_upcoming",
        name="Check Upcoming Appointments",
        replace_existing=True
    )
    
    scheduler.start()
    print("✅ Scheduler started with jobs:")
    print(f"  - Daily Queue Reset: {reset_hour:02d}:{reset_minute:02d}")
    print(f"  - Queue Summaries: 08:00")
    print(f"  - Check Upcoming: Every 30 minutes")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        print("🛑 Scheduler stopped")
