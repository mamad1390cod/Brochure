# 📚 Bot-File-School

ربات تلگرام مدیریت و ارائه جزوه‌های کلاس دهم

A professional Telegram bot for managing, categorizing, and searching school notes.

## 🏗 Architecture

```
Field (رشته تحصیلی) → Subject (درس) → Chapter (فصل) → Note (جزوه)
Field (رشته تحصیلی) → Subject (درس) → Homework Task (تکلیف)
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
- 📅 Browse active homework by assignment day, field, and subject; open its
  description and optional image
- 🔍 Inline search in any chat
- 📥 Download/view note files

### For Admins
- 🔐 Secure admin authentication (hashed passwords)
- 📚 Full CRUD for Fields, Subjects, Chapters, Notes
- ✅ Approve/reject pending notes
- 🗂 Review pending notes from a button list with submitter details and the
  original approval/rejection actions
- 📝 Create homework for a field, subject, and weekday, with instructions,
  optional image, and a Jalali deadline (Tehran time); expired homework is
  automatically removed from active lists
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

`/start` always opens the regular user menu. The admin-panel button is added
only for the configured Owner or an active admin identified by Telegram user
ID; usernames and display names are never used to grant a role. Admin callbacks
are checked against the current role, login session, and permission grants.

Inline keyboards are visible to every member when sent in a group, so their
appearance is not an access control. The bot persists each interactive
message's chat, message, owner, and active callback data in
`inline_keyboard_ownership`; callbacks from another user or an old/changed
button are rejected before reaching a handler. Old interactive messages from
before this feature have no ownership record and must be recreated (for
example, by sending `/start` again). Unauthenticated non-owner admins must
start the panel login in a private chat so they never enter a password in a
group.

## 🗄 Database Tables

- **study_fields** - Study fields (رشته‌ها)
- **subjects** - Subjects (درس‌ها)
- **chapters** - Chapters (فصل‌ها)
- **notes** - Notes (جزوه‌ها)
- **tasks** / **task_categories** - Field/subject assignments with weekday,
  optional image, and automatic expiration after their deadline
- **admins** - Admin accounts (hashed passwords)
- **admin_permissions** - Admin permission grants
- **inline_keyboard_ownership** - Persisted owner and active callbacks for each interactive bot message
- **users** - Registered users
- **allowed_users** - Trusted users (auto-approve)
- **settings** - Bot settings
- **logs** - Audit log

## 🔒 Security

- Passwords stored as PBKDF2-HMAC-SHA256 with a random salt; legacy salted SHA-256 hashes are upgraded after a successful login
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

Application and framework logs are written to `logs/bot.log` (rotated at 5 MiB,
keeping five backups) and to the console. Set `LOG_LEVEL=DEBUG` in `.env` when
you need detailed diagnostics.

## 💾 Automatic Backups

After successful startup, the bot creates a backup every four hours and sends
it as a document to the owner configured by `MAIN_ADMIN_ID`. Each ZIP contains
a transaction-consistent SQLite snapshot at `database/main_database.db` and a
`backup_manifest.json` with file sizes, SHA-256 hashes where applicable, and
integrity-check results. The snapshot uses SQLite's online backup API, so it
also includes committed data held in the WAL.

Archives are written under `data/backups/`. The most recent successfully sent
archive is retained locally; older archives are removed only after a newer
archive has been checked and delivered. If delivery fails, that archive is
retained and the owner is notified when possible. A later successful delivery
replaces the prior local archive.

Note and homework media are stored by Telegram and referenced by file IDs in
SQLite; the project does not persist those uploads in a local media directory.
Temporary conversion files, logs, source code, `.env`, and other secrets are
not included in the archive. Restore by extracting the snapshot database and
using it as the configured database file; the bot token and other secrets
must be configured separately and are never backed up.

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
