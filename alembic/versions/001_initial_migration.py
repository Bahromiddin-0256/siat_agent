"""Initial migration - create all tables

Revision ID: 001
Revises: 
Create Date: 2024-01-02 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create doctors table
    op.create_table('doctors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('specialty', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('average_duration', sa.Integer(), nullable=True),
        sa.Column('uses_custom_schedule', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id')
    )
    
    # Create patients table
    op.create_table('patients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create default_clinic_schedule table
    op.create_table('default_clinic_schedule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('break_start', sa.Time(), nullable=True),
        sa.Column('break_end', sa.Time(), nullable=True),
        sa.Column('is_working_day', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('weekday')
    )
    
    # Create settings table
    op.create_table('settings',
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )
    
    # Create doctor_weekly_schedule table
    op.create_table('doctor_weekly_schedule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('break_start', sa.Time(), nullable=True),
        sa.Column('break_end', sa.Time(), nullable=True),
        sa.Column('is_working_day', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create doctor_schedule_overrides table
    op.create_table('doctor_schedule_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('is_working', sa.Boolean(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('break_start', sa.Time(), nullable=True),
        sa.Column('break_end', sa.Time(), nullable=True),
        sa.Column('reason', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create queue_entries table
    op.create_table('queue_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'NO_SHOW', name='queuestatus'), nullable=False),
        sa.Column('registration_type', sa.Enum('ONLINE', 'WALK_IN', 'DIRECT_LINK', name='registrationtype'), nullable=False),
        sa.Column('estimated_time', sa.DateTime(), nullable=True),
        sa.Column('actual_start_time', sa.DateTime(), nullable=True),
        sa.Column('actual_end_time', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('queue_date', sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create registration_links table
    op.create_table('registration_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=True),
        sa.Column('max_usage', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )


def downgrade() -> None:
    op.drop_table('registration_links')
    op.drop_table('queue_entries')
    op.drop_table('doctor_schedule_overrides')
    op.drop_table('doctor_weekly_schedule')
    op.drop_table('settings')
    op.drop_table('default_clinic_schedule')
    op.drop_table('patients')
    op.drop_table('doctors')
