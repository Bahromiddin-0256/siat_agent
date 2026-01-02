# 🦷 Dental Clinic Queue Management System

A comprehensive **Telegram bot** for managing patient queues in dental clinics. Built with modern async Python technologies, this system digitalizes the traditional queue management process, providing real-time updates, estimated wait times, and efficient patient flow management.

## 🌟 Key Features

### For Patients
- 📝 **Online Registration** - Register from anywhere via Telegram
- 📊 **Real-Time Queue Status** - See your position and estimated wait time
- ⏰ **Notifications** - Get notified when your turn approaches
- 🇺🇿 **Uzbek Interface** - Full support for Uzbek language

### For Doctors
- 👥 **Queue Management** - View and manage your daily patient queue
- ✅ **Patient Status Updates** - Mark patients as in progress or completed
- ➕ **Walk-in Registration** - Add patients who arrive without online registration
- 📊 **Statistics** - Track daily patient flow and completion rates
- ⚙️ **Custom Schedules** - Set your own working hours

### For Administrators
- 👨‍⚕️ **Doctor Management** - Add/remove doctors from the system
- ⚙️ **System Configuration** - Adjust clinic hours, queue sizes, etc.
- 📈 **Analytics** - View clinic-wide statistics
- 🔧 **Settings Management** - Configure default parameters

## 🏗️ Architecture

### Technology Stack

| Component | Technology |
|-----------|------------|
| **Backend** | FastAPI (async) |
| **Bot Framework** | aiogram 3.x |
| **Database** | PostgreSQL |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Migrations** | Alembic |
| **Scheduler** | APScheduler |
| **Container** | Docker + Docker Compose |

### Why These Technologies?

- **FastAPI**: High performance, async support, automatic API docs
- **aiogram 3.x**: Modern async Telegram bot framework with FSM support
- **PostgreSQL**: Reliable, feature-rich RDBMS
- **SQLAlchemy 2.0**: Powerful async ORM with type safety
- **Docker**: Easy deployment and environment consistency

## 📁 Project Structure

```
siat_agent/
├── app/
│   ├── main.py                      # FastAPI application entry
│   ├── config.py                    # Configuration management
│   ├── database/
│   │   ├── models.py               # Database models
│   │   └── connection.py           # DB connection
│   ├── bot/
│   │   ├── bot.py                  # Bot initialization
│   │   ├── handlers/               # Command and callback handlers
│   │   │   ├── patient.py         # Patient interactions
│   │   │   ├── doctor.py          # Doctor panel
│   │   │   └── admin.py           # Admin management
│   │   ├── keyboards/              # Telegram keyboards
│   │   │   ├── inline.py          # Inline keyboards
│   │   │   └── reply.py           # Reply keyboards
│   │   ├── states/                 # FSM states
│   │   │   └── registration.py   # Registration flows
│   │   └── middlewares/            # Bot middlewares
│   ├── services/                    # Business logic
│   │   ├── queue_service.py       # Queue management
│   │   ├── availability_service.py # Doctor schedules
│   │   ├── notification_service.py # Notifications
│   │   └── scheduler_service.py   # Automated tasks
│   └── utils/                       # Utilities
│       ├── time_utils.py          # Time handling
│       └── validators.py          # Input validation
├── alembic/                         # Database migrations
│   ├── versions/                   # Migration scripts
│   └── env.py                      # Alembic environment
├── tests/                           # Test suite
│   ├── unit/                       # Unit tests
│   └── conftest.py                 # Test configuration
├── docker-compose.yml               # Docker orchestration
├── Dockerfile                       # Container definition
├── dental_requirements.txt          # Python dependencies
├── seed_database.py                 # Initial data seeder
├── start_dental_bot.sh             # Startup script
├── .env.dental.example             # Environment template
├── DENTAL_BOT_README.md            # Detailed documentation
├── SETUP_GUIDE.md                  # Setup instructions
└── IMPLEMENTATION_STATUS.md        # Current status
```

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 12+ (or use Docker)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- Your Telegram ID from [@userinfobot](https://t.me/userinfobot)

### Option 1: Docker (Recommended)

```bash
# 1. Copy environment file
cp .env.dental.example .env

# 2. Edit .env with your credentials
nano .env
# Set BOT_TOKEN and ADMIN_IDS

# 3. Start services
docker-compose up -d

# 4. View logs
docker-compose logs -f bot

# 5. Seed initial data
docker-compose exec bot python seed_database.py
```

### Option 2: Manual Installation

```bash
# 1. Clone repository
git clone <repository-url>
cd siat_agent

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r dental_requirements.txt

# 4. Set up PostgreSQL
createdb dental_clinic

# 5. Configure environment
cp .env.dental.example .env
nano .env  # Edit with your settings

# 6. Seed database
python seed_database.py

# 7. Run the bot
python -m app.main
```

## 📖 Documentation

- **[DENTAL_BOT_README.md](DENTAL_BOT_README.md)** - Comprehensive feature documentation
- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** - Detailed setup instructions
- **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** - Current implementation status

## 🎯 Core Workflows

### 1. Patient Registration (Online)

```
Patient → /start
      → Select "Ro'yxatdan o'tish"
      → Choose doctor
      → Share phone number
      → Enter name
      → Wait for doctor confirmation
      → Receive queue position and estimated time
```

### 2. Doctor Queue Management

```
Doctor → /doctor
       → View current queue
       → Mark "Bemor kirdi" (patient entered)
       → Mark "Bemor chiqdi" (patient left)
       → Queue automatically advances
       → Waiting patients notified
```

### 3. Walk-in Registration

```
Doctor → /doctor
       → Select "Bemor qo'shish"
       → Enter patient name
       → Enter phone number
       → Patient immediately added to queue
```

## 🗄️ Database Schema

### Core Tables

- **doctors** - Doctor profiles and settings
- **patients** - Patient contact information
- **queue_entries** - Active and historical queue entries
- **doctor_weekly_schedule** - Regular weekly hours
- **doctor_schedule_overrides** - Date-specific exceptions
- **default_clinic_schedule** - Clinic-wide default hours
- **registration_links** - Direct registration links
- **settings** - System configuration

### Key Features

- ✅ Automatic position recalculation
- ✅ Estimated time based on doctor's average duration
- ✅ Three-tier availability system (override → weekly → default)
- ✅ Status tracking (PENDING → CONFIRMED → IN_PROGRESS → COMPLETED)
- ✅ Multiple registration types (ONLINE, WALK_IN, DIRECT_LINK)

## ⚙️ Configuration

Edit `.env` file:

```bash
# Required
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=your_telegram_id
DATABASE_URL=postgresql+asyncpg://user:pass@host/db

# Optional (defaults shown)
TIMEZONE=Asia/Tashkent
DEFAULT_DURATION=20              # minutes per patient
CLINIC_OPEN=09:00
CLINIC_CLOSE=18:00
LUNCH_BREAK_START=13:00
LUNCH_BREAK_END=14:00
DAILY_RESET_TIME=08:00
MAX_QUEUE_SIZE=50
NOTIFICATION_THRESHOLD=3         # notify when X patients ahead
```

## 🧪 Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio aiosqlite

# Run tests
pytest tests/

# Run with coverage
pytest --cov=app tests/
```

## 📊 Monitoring

### Health Check

```bash
curl http://localhost:8000/health
```

### View Logs

```bash
# Docker
docker-compose logs -f bot

# Manual
# Logs appear in console
```

## 🔒 Security

- ✅ Phone verification via Telegram's contact sharing
- ✅ Admin authentication by Telegram ID whitelist
- ✅ Input validation and sanitization
- ✅ SQL injection prevention (SQLAlchemy ORM)
- ✅ No plaintext passwords stored
- ⚠️ Keep `.env` file secure (never commit)
- ⚠️ Use strong PostgreSQL password
- ⚠️ Keep bot token secret

## 🚀 Deployment

### Production Checklist

- [ ] Set strong PostgreSQL password
- [ ] Configure proper backup strategy
- [ ] Set up monitoring and alerting
- [ ] Enable logging to file
- [ ] Configure rate limiting
- [ ] Set up SSL/TLS if exposing API
- [ ] Review and test all workflows
- [ ] Train staff on system usage
- [ ] Prepare user documentation

### Systemd Service (Linux)

```ini
[Unit]
Description=Dental Clinic Bot
After=network.target postgresql.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/siat_agent
Environment="PATH=/path/to/.venv/bin"
ExecStart=/path/to/.venv/bin/python -m app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

### Backup

```bash
# Database backup
pg_dump -U dental_user dental_clinic > backup.sql

# Automated daily backup (cron)
0 2 * * * pg_dump -U dental_user dental_clinic > /backups/dental_$(date +\%Y\%m\%d).sql
```

## 🛠️ Troubleshooting

### Bot Not Responding

1. Check bot is running: `docker-compose ps`
2. Check logs: `docker-compose logs bot`
3. Verify token in `.env`
4. Test bot token: `curl https://api.telegram.org/bot<TOKEN>/getMe`

### Database Connection Error

1. Check PostgreSQL is running
2. Verify credentials in `.env`
3. Test connection: `psql -U dental_user -d dental_clinic`

### "You don't have admin rights"

- Get your Telegram ID from @userinfobot
- Add it to `ADMIN_IDS` in `.env`
- Restart bot

## 🎓 Learning Resources

- [aiogram Documentation](https://docs.aiogram.dev/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Telegram Bot API](https://core.telegram.org/bots/api)

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📝 License

This project is created for dental clinic queue management.

## 🙏 Acknowledgments

Built with:
- FastAPI by Sebastián Ramírez
- aiogram by Alex Root Junior
- SQLAlchemy by Mike Bayer
- PostgreSQL by PostgreSQL Global Development Group

## 📞 Support

For issues and questions:
- Check documentation files
- Review logs for error messages
- Verify configuration
- Ensure all services are running

---

**Status**: ✅ Core features implemented and functional  
**Version**: 1.0.0  
**Last Updated**: 2024-01-02

Made with ❤️ for better healthcare queue management
