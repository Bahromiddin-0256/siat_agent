# Dental Clinic Bot - Quick Setup Guide

This guide will help you get the dental clinic queue management bot up and running.

## Prerequisites

- Python 3.10 or higher
- PostgreSQL 12 or higher (or use Docker)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- Your Telegram ID from [@userinfobot](https://t.me/userinfobot)

## Setup Steps

### 1. Get Your Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the instructions:
   - Choose a name for your bot (e.g., "My Dental Clinic")
   - Choose a username (e.g., "my_dental_clinic_bot")
4. Save the token that BotFather gives you

### 2. Get Your Telegram ID

1. Open Telegram and search for `@userinfobot`
2. Send `/start` command
3. The bot will reply with your Telegram ID (a number like 123456789)
4. Save this ID - you'll be the admin

### 3. Configure Environment

```bash
# Copy the example environment file
cp .env.dental.example .env

# Edit the .env file
nano .env  # or use any text editor
```

Edit these required fields:

```bash
BOT_TOKEN=your_token_from_botfather
ADMIN_IDS=your_telegram_id
DATABASE_URL=postgresql+asyncpg://dental_user:dental_password@localhost:5432/dental_clinic
```

### 4. Option A: Run with Docker (Recommended)

```bash
# Set your bot token in docker-compose.yml or use .env
export BOT_TOKEN="your_token_here"
export ADMIN_IDS="your_telegram_id"

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f bot

# Stop services
docker-compose down
```

### 4. Option B: Run Manually

#### Install PostgreSQL

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**macOS:**
```bash
brew install postgresql
brew services start postgresql
```

#### Create Database

```bash
# Connect to PostgreSQL
sudo -u postgres psql

# In PostgreSQL prompt:
CREATE USER dental_user WITH PASSWORD 'dental_password';
CREATE DATABASE dental_clinic OWNER dental_user;
\q
```

#### Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # On Linux/Mac
# or
.venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r dental_requirements.txt
```

#### Run the Bot

```bash
# Using the startup script
./start_dental_bot.sh

# Or directly
python -m app.main
```

### 5. Initialize Default Schedule

Once the bot is running, send this command in Telegram:

```
/init_schedule
```

This creates the default clinic schedule (Monday-Friday 09:00-18:00).

### 6. Add Your First Doctor

Send this command to the bot:

```
/adddoctor
```

Follow the prompts to add a doctor:
1. Enter doctor's name
2. Enter specialty
3. Enter doctor's Telegram ID (or 0 to skip)

### 7. Test the Bot

As a patient (use another Telegram account or ask someone):
1. Start the bot: `/start`
2. Click "Ro'yxatdan o'tish" (Register)
3. Select a doctor
4. Share phone number
5. Enter name

As a doctor:
1. Send `/doctor` to access doctor panel
2. View queue, confirm registrations, etc.

## Common Issues

### Bot Not Responding

**Check if bot is running:**
```bash
docker-compose ps  # If using Docker
# or check your terminal where you ran python -m app.main
```

**Check logs:**
```bash
docker-compose logs bot  # If using Docker
```

**Verify bot token:**
Make sure BOT_TOKEN in .env is correct (no spaces, quotes, etc.)

### Database Connection Error

**Check PostgreSQL is running:**
```bash
sudo systemctl status postgresql  # Linux
brew services list  # macOS
```

**Verify credentials:**
Make sure DATABASE_URL in .env matches your PostgreSQL setup.

**Test connection:**
```bash
psql -U dental_user -d dental_clinic -h localhost
```

### "You don't have admin rights"

Make sure your Telegram ID is in the ADMIN_IDS in .env file.

Get your ID from @userinfobot and update .env:
```bash
ADMIN_IDS=123456789
```

## Configuration Options

You can customize these in `.env`:

```bash
# Working hours
CLINIC_OPEN=09:00
CLINIC_CLOSE=18:00

# Lunch break
LUNCH_BREAK_START=13:00
LUNCH_BREAK_END=14:00

# Queue settings
DEFAULT_DURATION=20          # Minutes per patient
MAX_QUEUE_SIZE=50           # Maximum patients per day
NOTIFICATION_THRESHOLD=3    # Notify when X patients ahead

# Daily reset
DAILY_RESET_TIME=08:00      # When to reset queue each day
```

## Production Deployment

### Using systemd (Linux)

Create `/etc/systemd/system/dental-bot.service`:

```ini
[Unit]
Description=Dental Clinic Bot
After=network.target postgresql.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/siat_agent
Environment="PATH=/path/to/siat_agent/.venv/bin"
ExecStart=/path/to/siat_agent/.venv/bin/python -m app.main
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dental-bot
sudo systemctl start dental-bot
sudo systemctl status dental-bot
```

### Using Docker in Production

```bash
# Build and run in detached mode
docker-compose up -d

# Enable auto-restart
docker update --restart unless-stopped dental_clinic_bot

# View logs
docker-compose logs -f

# Update and restart
git pull
docker-compose down
docker-compose up -d --build
```

## Backup

### Database Backup

```bash
# Manual backup
pg_dump -U dental_user dental_clinic > backup_$(date +%Y%m%d).sql

# Restore
psql -U dental_user dental_clinic < backup_20240101.sql
```

### Automated Daily Backup

Add to crontab:
```bash
0 2 * * * pg_dump -U dental_user dental_clinic > /backups/dental_$(date +\%Y\%m\%d).sql
```

## Monitoring

### Check Bot Status

```bash
# Health check
curl http://localhost:8000/health

# View metrics (if running)
curl http://localhost:8000/
```

### View Logs

```bash
# Docker
docker-compose logs -f bot

# Systemd
sudo journalctl -u dental-bot -f

# Manual run
# Logs are printed to console
```

## Support

For issues:
1. Check this guide
2. Check logs for error messages
3. Verify configuration in .env
4. Ensure PostgreSQL is running
5. Ensure bot token is valid

## Next Steps

After setup:
1. Add all your doctors
2. Configure doctor schedules if needed
3. Test registration flows
4. Train staff on using doctor panel
5. Announce to patients

## Security Notes

- Keep your BOT_TOKEN secret
- Use strong PostgreSQL password
- Keep .env file secure (never commit to git)
- Regularly backup your database
- Keep system updated

## Updates

To update the bot:

```bash
# Pull latest code
git pull

# Update dependencies
pip install -r dental_requirements.txt  # Manual
# or
docker-compose up -d --build  # Docker

# Restart
sudo systemctl restart dental-bot  # Systemd
# or
docker-compose restart bot  # Docker
```
