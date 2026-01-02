"""SQLAlchemy database models for dental clinic bot."""
from sqlalchemy import (
    Column, Integer, String, BigInteger, Boolean, DateTime, 
    Date, Time, ForeignKey, Enum as SQLEnum, Text
)
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
from datetime import datetime
import enum


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class QueueStatus(enum.Enum):
    """Queue entry status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class RegistrationType(enum.Enum):
    """Registration type."""
    ONLINE = "online"
    WALK_IN = "walk_in"
    DIRECT_LINK = "direct_link"


class Doctor(Base):
    """Doctor model."""
    __tablename__ = "doctors"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=True)
    name = Column(String(100), nullable=False)
    specialty = Column(String(100))
    is_active = Column(Boolean, default=True)
    average_duration = Column(Integer, default=20)
    uses_custom_schedule = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    weekly_schedule = relationship("DoctorWeeklySchedule", back_populates="doctor", cascade="all, delete-orphan")
    schedule_overrides = relationship("DoctorScheduleOverride", back_populates="doctor", cascade="all, delete-orphan")
    queue_entries = relationship("QueueEntry", back_populates="doctor")
    registration_links = relationship("RegistrationLink", back_populates="doctor", cascade="all, delete-orphan")


class DoctorWeeklySchedule(Base):
    """Doctor's weekly schedule."""
    __tablename__ = "doctor_weekly_schedule"
    
    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    weekday = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_start = Column(Time, nullable=True)
    break_end = Column(Time, nullable=True)
    is_working_day = Column(Boolean, default=True)
    
    # Relationships
    doctor = relationship("Doctor", back_populates="weekly_schedule")


class DoctorScheduleOverride(Base):
    """Doctor's schedule overrides for specific dates."""
    __tablename__ = "doctor_schedule_overrides"
    
    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    is_working = Column(Boolean, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    break_start = Column(Time, nullable=True)
    break_end = Column(Time, nullable=True)
    reason = Column(String(200), nullable=True)
    
    # Relationships
    doctor = relationship("Doctor", back_populates="schedule_overrides")


class Patient(Base):
    """Patient model."""
    __tablename__ = "patients"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=True)
    phone_number = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    queue_entries = relationship("QueueEntry", back_populates="patient")


class QueueEntry(Base):
    """Queue entry model."""
    __tablename__ = "queue_entries"
    
    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    status = Column(SQLEnum(QueueStatus), nullable=False, default=QueueStatus.PENDING)
    registration_type = Column(SQLEnum(RegistrationType), nullable=False, default=RegistrationType.ONLINE)
    estimated_time = Column(DateTime, nullable=True)
    actual_start_time = Column(DateTime, nullable=True)
    actual_end_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    queue_date = Column(Date, nullable=False)
    
    # Relationships
    doctor = relationship("Doctor", back_populates="queue_entries")
    patient = relationship("Patient", back_populates="queue_entries")


class RegistrationLink(Base):
    """Registration link model for direct patient registration."""
    __tablename__ = "registration_links"
    
    id = Column(Integer, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    usage_count = Column(Integer, default=0)
    max_usage = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    doctor = relationship("Doctor", back_populates="registration_links")


class Setting(Base):
    """System settings model."""
    __tablename__ = "settings"
    
    key = Column(String(50), primary_key=True)
    value = Column(String(500), nullable=False)
    description = Column(String(200), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DefaultClinicSchedule(Base):
    """Default clinic schedule (fallback when doctor has no custom schedule)."""
    __tablename__ = "default_clinic_schedule"
    
    id = Column(Integer, primary_key=True)
    weekday = Column(Integer, nullable=False, unique=True)  # 0=Monday, 6=Sunday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_start = Column(Time, nullable=True)
    break_end = Column(Time, nullable=True)
    is_working_day = Column(Boolean, default=True)
