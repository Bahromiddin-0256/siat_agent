# Dental Clinic Queue Management Telegram Bot

A comprehensive Telegram bot for managing patient queues in a dental clinic. Built with FastAPI, aiogram 3.x, and PostgreSQL.

## Features

- **Multi-Doctor Queue System**: Each doctor maintains their own independent queue
- **Real-Time Queue Updates**: Automatic notifications when queue positions change
- **Doctor Availability Scheduling**: Custom schedules per doctor with fallback to clinic defaults
- **Multiple Registration Flows**:
  - Online registration with phone verification
  - Walk-in patient registration by doctors
  - Direct link registration (no confirmation required)
- **Estimated Wait Times**: Configurable appointment duration with automatic calculation
- **Daily Queue Reset**: Automatic reset at clinic opening time
- **Uzbek Language UI**: All bot messages and interface in Uzbek

## Technology Stack

- **Backend**: FastAPI
- **Telegram Bot**: aiogram 3.x
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy 2.0 (async)
- **Task Scheduler**: APScheduler
- **Async Support**: asyncio

## Project Structure

```
dental_clinic_bot/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # Settings and environment
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py       # DB connection
│   │   └── models.py           # SQLAlchemy models
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── bot.py              # aiogram bot instance
│   │   ├── handlers/
│   │   │   └── patient.py      # Patient handlers
│   │   ├── keyboards/
│   │   │   ├── inline.py       # Inline keyboards
│   │   │   └── reply.py        # Reply keyboards
│   │   ├── states/
│   │   │   └── registration.py # FSM states
│   │   └── middlewares/
│   ├── services/
│   │   ├── queue_service.py    # Queue management
│   │   └── availability_service.py  # Doctor schedules
│   └── utils/
├── dental_requirements.txt
├── docker-compose.yml
├── Dockerfile
└── .env.dental.example
```

## Installation

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone <repository-url>
cd siat_agent
```

2. Create environment file:
```bash
cp .env.dental.example .env
```

3. Edit `.env` and set your bot token:
```bash
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_IDS=your_telegram_id
```

4. Start the services:
```bash
docker-compose up -d
```

### Manual Installation

1. Install Python 3.10+:
```bash
python --version  # Should be 3.10 or higher
```

2. Install dependencies:
```bash
pip install -r dental_requirements.txt
```

3. Set up PostgreSQL:
```bash
createdb dental_clinic
```

4. Configure environment:
```bash
cp .env.dental.example .env
# Edit .env with your settings
```

5. Run the application:
```bash
python -m app.main
```

## Configuration

### Environment Variables

Edit `.env` file:

```bash
# Telegram Bot
BOT_TOKEN=your_bot_token_here
ADMIN_IDS=123456789,987654321

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/dental_clinic

# Application Settings
TIMEZONE=Asia/Tashkent
DEFAULT_DURATION=20              # Average appointment duration in minutes
CLINIC_OPEN=09:00
CLINIC_CLOSE=18:00
DAILY_RESET_TIME=08:00
MAX_QUEUE_SIZE=50
NOTIFICATION_THRESHOLD=3         # Notify when X patients ahead
LINK_EXPIRY_HOURS=24
LUNCH_BREAK_START=13:00
LUNCH_BREAK_END=14:00

# API
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=false
```

## Getting Your Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` command
3. Follow the instructions to create your bot
4. Copy the token and paste it in `.env` file

## Getting Your Telegram ID

1. Open Telegram and search for [@userinfobot](https://t.me/userinfobot)
2. Send `/start` command
3. Copy your ID and paste it in `.env` file as ADMIN_IDS

## Usage

### For Patients

1. Start the bot: `/start`
2. Click "Ro'yxatdan o'tish" (Register)
3. Select a doctor
4. Share phone number
5. Enter your name
6. Wait for doctor confirmation

### For Doctors

Doctors need to be added to the system by an admin first. Once added:

1. Access doctor panel: `/doctor`
2. View queue: "Mening navbatim"
3. Mark patient as completed: "Bemor chiqdi"
4. Add walk-in patient: "Bemor qo'shish"
5. Generate registration link: "Havola olish"

### For Admins

1. Access admin panel: `/admin`
2. Add doctors: "Shifokorlar"
3. Configure settings: "Sozlamalar"
4. View statistics: "Statistika"

## Database Models

The system uses the following main models:

- **Doctor**: Doctor information and settings
- **Patient**: Patient contact information
- **QueueEntry**: Queue entries with status tracking
- **DoctorWeeklySchedule**: Weekly working hours per doctor
- **DoctorScheduleOverride**: Date-specific schedule exceptions
- **DefaultClinicSchedule**: Fallback schedule for all doctors
- **RegistrationLink**: Direct registration links
- **Setting**: System configuration

## API Endpoints

- `GET /` - Root endpoint with version info
- `GET /health` - Health check endpoint

Additional API routes will be added for:
- Doctor management
- Queue management
- Statistics and reporting

## Features in Detail

### Queue Management

- Automatic position calculation
- Real-time estimated time updates
- Support for multiple queue statuses:
  - PENDING: Waiting for doctor confirmation
  - CONFIRMED: Confirmed by doctor
  - IN_PROGRESS: Patient currently with doctor
  - COMPLETED: Appointment finished
  - CANCELLED: Cancelled by patient or doctor
  - NO_SHOW: Patient didn't show up

### Doctor Availability

Three-tier availability system:
1. **Date Override**: Specific date exceptions (holidays, special hours)
2. **Weekly Schedule**: Doctor's regular weekly schedule
3. **Default Clinic Schedule**: Fallback for all doctors

### Registration Types

1. **ONLINE**: Standard online registration requiring phone verification and doctor confirmation
2. **WALK_IN**: Physical walk-in patients added directly by doctor
3. **DIRECT_LINK**: Registration via doctor-generated link (no confirmation needed)

## Development

### Running Tests

```bash
pytest tests/
```

### Database Migrations

Using Alembic:

```bash
# Generate migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Troubleshooting

### Bot Not Responding

1. Check if bot is running:
```bash
docker-compose ps
```

2. Check logs:
```bash
docker-compose logs bot
```

3. Verify bot token is correct in `.env`

### Database Connection Issues

1. Check PostgreSQL is running:
```bash
docker-compose ps postgres
```

2. Verify database credentials in `.env`

3. Check database logs:
```bash
docker-compose logs postgres
```

## Security Considerations

- Phone verification via Telegram's contact sharing
- Admin authentication by Telegram ID
- Time-limited registration links
- Input validation with Pydantic
- No sensitive data in logs

## Future Enhancements

- [ ] SMS notifications for non-Telegram users
- [ ] Multi-language support (Uzbek, Russian, English)
- [ ] Appointment scheduling for specific times
- [ ] Payment integration
- [ ] Web dashboard for clinic management
- [ ] Analytics and reporting
- [ ] Queue display screen for clinic TV

## Support

For issues and questions:
- Check the documentation
- Review logs: `docker-compose logs bot`
- Verify configuration in `.env`

## License

This project is created for dental clinic queue management.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request
