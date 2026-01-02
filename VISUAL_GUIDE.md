# 🦷 Dental Clinic Bot - Visual Guide

## 📱 User Interface Flow

### Patient Journey

```
┌─────────────────────────────────────────────┐
│  🦷 Stomatologiya klinikasiga xush kelibsiz │
│                                             │
│  ┌──────────────┐  ┌──────────────┐       │
│  │📋 Navbatni   │  │📝 Ro'yxatdan │       │
│  │   ko'rish    │  │   o'tish     │       │
│  └──────────────┘  └──────────────┘       │
│                                             │
│  ┌──────────────┐  ┌──────────────┐       │
│  │ℹ️ Mening     │  │❌ Bekor      │       │
│  │   holatim    │  │   qilish     │       │
│  └──────────────┘  └──────────────┘       │
│                                             │
│  ┌──────────────┐                          │
│  │❓ Yordam     │                          │
│  └──────────────┘                          │
└─────────────────────────────────────────────┘
```

### Registration Flow

```
START
  │
  ├─→ Select "Ro'yxatdan o'tish"
  │
  ├─→ Choose Doctor
  │     ┌────────────────────────────────┐
  │     │ 👨‍⚕️ Dr. Ahmad - Umumiy       │
  │     │    Navbatda: ~15 kishi         │
  │     │    Kutish: ~5 soat             │
  │     ├────────────────────────────────┤
  │     │ 👨‍⚕️ Dr. Malika - Ortodontiya │
  │     │    Navbatda: ~8 kishi          │
  │     │    Kutish: ~2.5 soat           │
  │     └────────────────────────────────┘
  │
  ├─→ Share Phone Number
  │     [📱 Telefon raqamni yuborish]
  │
  ├─→ Enter Name
  │     "Iltimos, ismingizni kiriting"
  │
  └─→ REGISTERED
        ✅ Ro'yxatdan o'tdingiz!
        📍 Navbatingiz: #7
        ⏰ Taxminiy vaqt: 14:30
        ⏳ Shifokor tasdiqlashini kuting...
```

### Doctor Panel

```
┌─────────────────────────────────────────────┐
│  👨‍⚕️ Shifokor paneli - Dr. Ahmad           │
│                                             │
│  📅 Bugun: 15-yanvar, 2025                 │
│                                             │
│  📊 Statistika:                             │
│  • Navbatda: 12 kishi                      │
│  • Qabulda: 1 kishi                        │
│  • Tugatilgan: 5 kishi                     │
│  • Jami: 18 kishi                          │
│                                             │
│  ┌──────────────┐  ┌──────────────┐       │
│  │📋 Mening     │  │✅ Bemor      │       │
│  │   navbatim   │  │   chiqdi     │       │
│  └──────────────┘  └──────────────┘       │
│                                             │
│  ┌──────────────┐  ┌──────────────┐       │
│  │➕ Bemor      │  │🔗 Havola     │       │
│  │   qo'shish   │  │   olish      │       │
│  └──────────────┘  └──────────────┘       │
│                                             │
│  ┌──────────────┐  ┌──────────────┐       │
│  │⚙️ Sozlamalar │  │📊 Statistika │       │
│  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────┘
```

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    TELEGRAM                             │
│                  (User Interface)                       │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  AIOGRAM 3.X BOT                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐         │
│  │  Patient   │ │   Doctor   │ │   Admin    │         │
│  │  Handlers  │ │  Handlers  │ │  Handlers  │         │
│  └────────────┘ └────────────┘ └────────────┘         │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  FASTAPI BACKEND                        │
│  ┌─────────────────────────────────────────────────┐   │
│  │              SERVICES LAYER                     │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │  Queue   │ │Available │ │Notification│      │   │
│  │  │ Service  │ │  Service │ │  Service  │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘        │   │
│  │                                                  │   │
│  │  ┌──────────────────────────────┐               │   │
│  │  │   Scheduler Service          │               │   │
│  │  │   (Daily Reset, Summaries)   │               │   │
│  │  └──────────────────────────────┘               │   │
│  └─────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              SQLALCHEMY 2.0 (Async ORM)                 │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  POSTGRESQL DATABASE                    │
│  ┌─────────┐ ┌─────────┐ ┌──────────────┐             │
│  │ Doctors │ │Patients │ │Queue Entries │             │
│  └─────────┘ └─────────┘ └──────────────┘             │
│                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌────────┐        │
│  │   Schedules  │ │   Settings   │ │ Links  │        │
│  └──────────────┘ └──────────────┘ └────────┘        │
└─────────────────────────────────────────────────────────┘
```

## 📊 Data Flow Diagrams

### Patient Registration Flow

```
Patient                Bot              Service           Database
  │                     │                  │                 │
  │──[/start]──────────>│                  │                 │
  │                     │                  │                 │
  │<──[Main Menu]───────│                  │                 │
  │                     │                  │                 │
  │──[Register]────────>│                  │                 │
  │                     │                  │                 │
  │                     │──[Get Doctors]──>│                 │
  │                     │                  │──[SELECT]──────>│
  │                     │                  │<──[Doctors]─────│
  │                     │<──[Doctor List]──│                 │
  │                     │                  │                 │
  │<──[Select Doctor]───│                  │                 │
  │                     │                  │                 │
  │──[Doctor ID]───────>│                  │                 │
  │                     │                  │                 │
  │<──[Share Phone]─────│                  │                 │
  │                     │                  │                 │
  │──[Phone Number]────>│                  │                 │
  │                     │                  │                 │
  │<──[Enter Name]──────│                  │                 │
  │                     │                  │                 │
  │──[Name]────────────>│                  │                 │
  │                     │                  │                 │
  │                     │──[Create Entry]─>│                 │
  │                     │                  │──[INSERT]──────>│
  │                     │                  │<──[Entry]───────│
  │                     │<──[Entry]────────│                 │
  │                     │                  │                 │
  │<──[Confirmation]────│                  │                 │
  │   (Position #7)     │                  │                 │
```

### Queue Update Flow

```
Doctor                 Bot              Service           Database
  │                     │                  │                 │
  │──[Complete]────────>│                  │                 │
  │                     │                  │                 │
  │                     │──[Update Status]>│                 │
  │                     │                  │──[UPDATE]──────>│
  │                     │                  │<──[OK]──────────│
  │                     │<──[OK]───────────│                 │
  │                     │                  │                 │
  │                     │──[Recalculate]──>│                 │
  │                     │                  │──[UPDATE ALL]──>│
  │                     │                  │<──[Updated]─────│
  │                     │<──[Done]─────────│                 │
  │                     │                  │                 │
  │                     │──[Notify Next]──>│                 │
  │                     │                  │                 │
  │<──[Updated]─────────│                  │                 │
  │                     │                  │                 │
  │                     │ (To all waiting patients)          │
  │                     │──[Send Update]───────────────────> │
```

## 🗄️ Database Schema Visualization

```
┌──────────────────────┐
│      DOCTORS         │
│──────────────────────│
│ • id (PK)            │
│ • telegram_id        │
│ • name               │
│ • specialty          │
│ • average_duration   │
│ • uses_custom_sched  │
└──────────┬───────────┘
           │
           │ 1:N
           │
┌──────────▼───────────┐       ┌──────────────────────┐
│  QUEUE_ENTRIES       │   N:1 │      PATIENTS        │
│──────────────────────│◀──────│──────────────────────│
│ • id (PK)            │       │ • id (PK)            │
│ • doctor_id (FK)     │       │ • telegram_id        │
│ • patient_id (FK)    │       │ • phone_number       │
│ • position           │       │ • name               │
│ • status             │       └──────────────────────┘
│ • registration_type  │
│ • estimated_time     │
│ • queue_date         │
└──────────────────────┘

┌──────────────────────┐
│ DOCTOR_WEEKLY_       │
│ SCHEDULE             │
│──────────────────────│
│ • doctor_id (FK)     │──┐
│ • weekday            │  │
│ • start_time         │  │
│ • end_time           │  │
│ • break_start/end    │  │
└──────────────────────┘  │ N:1
                          │
┌──────────────────────┐  │
│ DOCTOR_SCHEDULE_     │  │
│ OVERRIDES            │  │
│──────────────────────│  │
│ • doctor_id (FK)     │──┘
│ • date               │
│ • is_working         │
│ • start/end times    │
│ • reason             │
└──────────────────────┘

┌──────────────────────┐
│ DEFAULT_CLINIC_      │
│ SCHEDULE             │
│──────────────────────│
│ • weekday (PK)       │
│ • start_time         │
│ • end_time           │
│ • break_start/end    │
│ • is_working_day     │
└──────────────────────┘
```

## ⏱️ Queue Status State Machine

```
   ┌─────────┐
   │  START  │
   └────┬────┘
        │
        │ Patient registers online
        ▼
   ┌─────────┐
   │ PENDING │ ──────────────┐
   └────┬────┘               │
        │                    │ Doctor rejects
        │ Doctor confirms    │
        ▼                    ▼
   ┌──────────┐         ┌──────────┐
   │CONFIRMED │         │CANCELLED │
   └────┬─────┘         └──────────┘
        │
        │ Patient enters
        ▼
   ┌────────────┐
   │IN_PROGRESS │
   └─────┬──────┘
         │
         │ Appointment ends
         ▼
   ┌──────────┐
   │COMPLETED │
   └──────────┘

   Alternative paths:
   - Patient cancels: ANY → CANCELLED
   - No show: CONFIRMED → NO_SHOW (automatic at day end)
```

## 📅 Daily Schedule Example

```
Clinic Schedule (Default)
═════════════════════════════════════════════

Monday - Friday:  09:00 ─────────┬───────── 18:00
                                 │
                            13:00-14:00
                           (Lunch Break)

Saturday - Sunday: NOT WORKING

Example Doctor (Dr. Ahmad):
─────────────────────────────────────────────
Position | Patient      | Status      | Time
─────────────────────────────────────────────
   #1    | Aziz K.      | IN_PROGRESS | 09:00
   #2    | Madina S.    | CONFIRMED   | 09:20
   #3    | Sardor T.    | CONFIRMED   | 09:40
   #4    | Nilufar A.   | PENDING     | 10:00
   #5    | Javohir A.   | CONFIRMED   | 10:20
   ...   | ...          | ...         | ...
   
   Lunch Break: 13:00 - 14:00
   
   #15   | Patient X    | CONFIRMED   | 14:00
   #16   | Patient Y    | CONFIRMED   | 14:20
   ...   | ...          | ...         | ...
```

## 🔔 Notification Timeline

```
Timeline of a Patient's Experience
═══════════════════════════════════════════

08:30 │ Registration
      │ ✅ Ro'yxatdan o'tdingiz!
      │ 📍 Navbat: #7
      │ ⏰ Taxminiy: 10:00
      │
09:00 │ Doctor confirms
      │ ✅ Navbatingiz tasdiqlandi!
      │
09:30 │ Position update
      │ 🔄 Navbat yangilandi
      │ 📍 Yangi o'rningiz: #4
      │
09:45 │ Turn approaching
      │ ⏰ Navbatingiz yaqinlashmoqda!
      │ Sizdan oldin 2 kishi
      │
10:00 │ Your turn
      │ 🔔 Sizning navbatingiz!
      │ Iltimos, kabinetiga kiring
      │
10:20 │ Completed
      │ ✅ Qabul tugallandi
      │ Rahmat!
```

## 🎯 Quick Reference

### Bot Commands

| Command | User Type | Description |
|---------|-----------|-------------|
| `/start` | All | Start bot / Main menu |
| `/doctor` | Doctor | Doctor panel |
| `/admin` | Admin | Admin panel |
| `/adddoctor` | Admin | Add new doctor |
| `/init_schedule` | Admin | Initialize schedule |

### Queue Status Codes

| Status | Meaning | Who can set |
|--------|---------|-------------|
| `PENDING` | Awaiting confirmation | System (online reg) |
| `CONFIRMED` | Confirmed by doctor | Doctor |
| `IN_PROGRESS` | Currently with doctor | Doctor |
| `COMPLETED` | Finished | Doctor |
| `CANCELLED` | Cancelled | Patient or Doctor |
| `NO_SHOW` | Didn't show up | System (auto) |

### Registration Types

| Type | Description | Confirmation |
|------|-------------|--------------|
| `ONLINE` | Via bot | Required |
| `WALK_IN` | Added by doctor | Not required |
| `DIRECT_LINK` | Via special link | Not required |

---

**Legend:**
- ✅ Fully implemented
- ⚠️ Partially implemented
- ❌ Not implemented
- 🔄 In progress
