"""Pytest configuration and fixtures."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.database.models import Base, Doctor, Patient
from app.config import settings


# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    """Create async engine for tests."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Create async session for tests."""
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def sample_doctor(session: AsyncSession):
    """Create a sample doctor for testing."""
    doctor = Doctor(
        name="Dr. Test Doctor",
        specialty="Test Specialty",
        is_active=True,
        average_duration=20,
        uses_custom_schedule=False
    )
    session.add(doctor)
    await session.commit()
    await session.refresh(doctor)
    return doctor


@pytest_asyncio.fixture
async def sample_patient(session: AsyncSession):
    """Create a sample patient for testing."""
    patient = Patient(
        name="Test Patient",
        phone_number="+998901234567",
        telegram_id=123456789
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient
