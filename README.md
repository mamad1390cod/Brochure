# 📚 Bot-File-School

ربات تلگرام مدیریت و ارائه جزوه‌های کلاس دهم

A professional Telegram bot for managing, categorizing, and searching school notes.

## 🏗 Architecture

```
Field (رشته تحصیلی) → Subject (درس) → Chapter (فصل) → Note (جزوه)
```

## 📁 Project Structure

```
Bot-File-School/
├── main.py              # Entry point
├── config.py            # Environment configuration
├── database.py          # SQLite schema & connection
├── models.py            # Data access layer (CRUD operations)
├── handlers.py          # User-facing handlers (/start, search, browse)
├── notes.py             # Note submission flow (FSM)
├── admin.py             # Admin panel & management
├── inline.py            # Telegram inline search
├── keyboards.py         # Inline keyboard builders
├── permissions.py       # Permission system
├── security.py          # Password hashing & rate limiting
├── utils.py             # Helper functions
├── logger.py            # Logging configuration
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (create from .env.example)
├── .env.example         # Environment template
├── .gitignore
├── README.md
└── data/
    └── school_notes.db  # SQLite database (auto-created)
```

## 🚀 Setup & Installation

### 1. Clone or download the project

```bash
cd Bot-File-School
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
BOT_TOKEN=your_bot_token_from_BotFather
MAIN_ADMIN_ID=your_telegram_numeric_id
ADMIN_PASSWORD=your_secure_password
ALLOWED_GROUP_ID=-100xxxxxxxxxx
```

### 5. Run the bot

```bash
python main.py
```

## 🔑 Getting Your Telegram ID

1. Send a message to [@userinfobot](https://t.me/userinfobot)
2. Copy the numeric ID
3. Set it as `MAIN_ADMIN_ID` in `.env`

## 🤖 Setting Up the Bot

1. Go to [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow instructions
3. Copy the bot token to `.env`
4. Enable Inline Mode:
   - Send `/setinline` to BotFather
   - Select your bot
   - Enter placeholder text (e.g., "جستجوی جزوه...")

## ✨ Features

### For Regular Users
- 📚 Browse notes by Field → Subject → Chapter
- 🔎 Search notes by keyword
- ➕ Submit new notes (step-by-step flow)
- 🔍 Inline search in any chat
- 📥 Download/view note files

### For Admins
- 🔐 Secure admin authentication (hashed passwords)
- 📚 Full CRUD for Fields, Subjects, Chapters, Notes
- ✅ Approve/reject pending notes
- 👨‍💼 Manage admins with granular permissions
- 👥 Manage trusted users (skip approval)
- 📋 View operation logs
- 📊 Bot statistics
- ⚙️ Settings management

## 🔐 Permission System

Each admin can have granular permissions:

| Permission | Description |
|---|---|
| `view_panel` | View admin panel |
| `view_notes` | View notes |
| `add_note` | Add notes |
| `delete_note` | Delete notes |
| `edit_note` | Edit notes |
| `add_field` | Add study fields |
| `delete_field` | Delete study fields |
| `add_subject` | Add subjects |
| `delete_subject` | Delete subjects |
| `add_chapter` | Add chapters |
| `delete_chapter` | Delete chapters |
| `manage_users` | Manage trusted users |
| `manage_admins` | Manage admins |
| `manage_settings` | Manage settings |

## 🗄 Database Tables

- **study_fields** - Study fields (رشته‌ها)
- **subjects** - Subjects (درس‌ها)
- **chapters** - Chapters (فصل‌ها)
- **notes** - Notes (جزوه‌ها)
- **admins** - Admin accounts (hashed passwords)
- **admin_permissions** - Admin permission grants
- **users** - Registered users
- **allowed_users** - Trusted users (auto-approve)
- **settings** - Bot settings
- **logs** - Audit log

## 🔒 Security

- Passwords stored as SHA-256 with random salt
- Rate limiting on admin login attempts
- No secrets in source code (all in `.env`)
- Parameterized SQL queries (no injection)
- Permission checks on all admin operations
- Optional group restriction

## 📝 Commands

| Command | Description |
|---|---|
| `/start` | Start the bot |
| `/جزوه` | Start note submission |
| `/help` | Show help |

## 🔧 Configuration Options

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `MAIN_ADMIN_ID` | Main admin Telegram ID |
| `ADMIN_PASSWORD` | Main admin password |
| `ALLOWED_GROUP_ID` | Restrict bot to specific group |
| `DATABASE_PATH` | SQLite database path |
| `ENABLE_INLINE_SEARCH` | Enable inline search |
| `INLINE_SEARCH_ALLOWED_USERS` | Comma-separated user IDs |
| `MAX_LOGIN_ATTEMPTS` | Max failed login attempts |
| `LOGIN_LOCKOUT_MINUTES` | Lockout duration |

## 📄 Supported File Types

- 🖼 Photos
- 🎬 Videos
- 📎 Documents (PDF, Word, etc.)
- 🎵 Audio
- 🎤 Voice messages

## 🛠 Built With

- [aiogram 3](https://docs.aiogram.dev/) - Async Telegram Bot framework
- [SQLite](https://sqlite.org/) - Database
- [python-dotenv](https://github.com/theskumar/python-dotenv) - Environment management

## 📜 License

MIT License
