# Google Drive and Railway deployment

## Storage design

- SQLite remains the authoritative store for users, notes, homework, schedules,
  settings, and file metadata.
- Google Drive stores note uploads, homework images, received conversion files,
  and generated conversion outputs. Files are private; the application does not
  create public permissions or share links.
- The `stored_files` table maps an internal UUID and application purpose to a
  Drive file ID, Telegram file identifiers, name, MIME type, size, checksum,
  uploader, and timestamps. `notes.storage_file_id` and
  `tasks.storage_file_id` associate media with existing records.
- Existing `file_id` columns are retained. A usable Telegram file ID is tried
  first for delivery; when Telegram rejects that reference, the bot downloads
  the private Drive object and sends that file instead.
- Drive uploads have a deterministic source key in Drive `appProperties`.
  Retrying after an upload succeeds but its SQLite write fails finds the same
  private Drive object instead of uploading another copy.
- Upload is completed and verified before the note or homework record is
  created. If the subsequent SQLite write fails, a retry can reuse the Drive
  object. If Telegram delivery fails after a generated file is stored, that
  Drive copy and its metadata are retained.
- Deleting a note or homework item permanently deletes its private Drive file
  when no other note or task references that stored file. A shared file is
  retained until its remaining records are removed. Drive failures leave the
  database record and storage reference available for a retry; a Drive `404`
  is treated as an already-completed deletion.

## Google Cloud OAuth setup

The application uses a Google user OAuth refresh token with the
`drive.file` scope. It does **not** assume that a service account has access to
a user's Drive, and it does not use a service account or create public files.
The OAuth user owns the uploaded files and the private `Brochure` folder that
the application creates on first use.

1. In Google Cloud Console, create/select a project and enable **Google Drive
   API**.
2. Configure the OAuth consent screen for the people who administer the bot.
   While the app is in Testing, add the Drive-owning Google account as a test
   user. For a long-running deployment, publish/configure the consent screen
   appropriately; a testing-mode refresh token can expire after seven days.
3. Create an OAuth client with application type **Desktop app**. Do not create
   or download a service-account key for this integration.
4. In a trusted local shell, set `GOOGLE_DRIVE_CLIENT_ID` and
   `GOOGLE_DRIVE_CLIENT_SECRET` to the client values and run:

   ```powershell
   .\.venv\Scripts\python.exe authorize_google_drive.py
   ```

   Sign in as the Drive-owning account and approve the requested `drive.file`
   access. Copy the resulting refresh token directly to Railway Variables.
   Do not put the token in a committed file, command history, issue, or chat.
5. Add these Railway Variables:

   | Variable | Value |
   |---|---|
   | `GOOGLE_DRIVE_CLIENT_ID` | OAuth Desktop client ID |
   | `GOOGLE_DRIVE_CLIENT_SECRET` | OAuth Desktop client secret |
   | `GOOGLE_DRIVE_REFRESH_TOKEN` | Refresh token from the local consent flow |
   | `GOOGLE_DRIVE_FOLDER_ID` | Optional existing folder ID; it must be accessible to this OAuth user and must not be publicly shared. Leave empty to let the app create its private `Brochure` folder |
   | `DATABASE_PATH` | `/data/school_notes.db` |

   Set secrets in Railway's Variables interface. None of the Google values
   belong in GitHub. The bot refreshes short-lived access tokens when needed.

Google Drive storage consumes the selected Google account's quota. Google
accounts have provider-defined storage limits; this implementation does not
provide extra storage or bypass Drive API quotas. Monitor that account's
available capacity and API usage. Use a private folder owned by the OAuth
account: Drive permissions inherited from a configured folder are not changed
by the application.

## Railway database volume and existing data

Attach a Railway Volume mounted at `/data`, and set:

```text
DATABASE_PATH=/data/school_notes.db
```

The configuration resolves absolute paths directly, so this setting is used
instead of the repository-relative development default. Do not point SQLite
at Google Drive. SQLite and its active WAL/SHM files must remain on the mounted
volume.

Before changing an existing deployment:

1. Stop/pause the current bot to prevent concurrent writes.
2. Make and download a verified backup of the current SQLite database using
   the project's backup feature or SQLite's online backup API. Keep that copy
   unchanged and private.
3. Attach the volume and copy the old database without replacing an existing
   destination. If the old database and new volume are both accessible to a
   one-time process, run:

   ```text
   python migrate_database_path.py --source <existing-database-path> --destination /data/school_notes.db
   ```

   The utility refuses to overwrite the destination, uses SQLite's online
   backup API, compares per-table row counts, runs `integrity_check`, and leaves
   the source untouched. If the old database is only accessible in the former
   Railway deployment, use a Railway shell/one-time command where both paths
   are mounted, or securely download the backup and place it on the new volume
   before starting the bot. Never commit or upload the database to a public
   repository.
4. Deploy the code and verify `DATABASE_PATH` and the volume mount before
   starting the normal service. `init_database()` performs additive,
   idempotent schema migrations; it does not reset existing records.
5. Verify existing user, note, task, and schedule counts before enabling
   writes. Keep the pre-deployment copy until verification is complete.

Do **not** set `/data/school_notes.db` before copying the old database if the
volume path is empty: SQLite would correctly initialize a new empty database
there, but it cannot recover records that were left in the old ephemeral path.
This project cannot inspect Railway's remote volume or determine whether
Railway currently contains records absent from the local checkout.

## Migrate existing note and homework media

The current schema stores existing uploaded media as Telegram `file_id`s, not
local upload paths. Once the code and Drive OAuth variables are deployed:

1. Keep the bot stopped while migrating, or schedule a maintenance window.
2. Confirm the Drive-owning OAuth user has quota and can use the API.
3. Run in the deployed application environment:

   ```text
   python migrate_files_to_drive.py
   ```

4. Review the printed `migrated` and `failed` counts and the application log.
   The utility downloads each legacy Telegram file, uploads it to Drive,
   verifies the returned Drive object, then links it to the existing row.
   Original Telegram IDs and all existing note/task metadata remain unchanged.
5. Rerunning the command is safe: linked rows are skipped; stable Telegram
   unique IDs and Drive `appProperties` make unfinished uploads resumable.
   Failed or expired Telegram IDs are reported and retained in SQLite for
   investigation rather than being deleted.
6. Restart the bot and test an old note and homework image from Telegram.
   Retain the original database backup until all required files have been
   verified.

If Railway cannot reach Telegram's file download endpoint for a legacy media
item, that item cannot be migrated by the utility until a working Telegram
file ID or original file is supplied. The item is reported; unrelated rows
are not removed.

## Generated and temporary files

In-app image-to-PDF, Word-to-PDF, PDF-to-Word, admin image conversion, and
admin report exports are uploaded to Drive before local temporary files are
cleaned up. Conversion inputs are also uploaded. Temporary working copies are
created only as needed by Telegram downloads and the existing conversion
libraries, and are removed after processing.

There is also an optional standalone PDF bot configured through
`PDF_BOT_PATH`. Its script is not part of this repository, so configure that
variable only with a path that exists on the target machine. Leave it unset
when the external script is unavailable; the main bot and its in-app PDF tools
continue to work. The separate program's handlers write to its own
`temp_images` folder and are **not** changed or migrated by this integration.
Deploy it separately and update it to use the same storage service if needed.

## Rollback

If the new Drive configuration or deployment fails:

1. Stop the service.
2. Restore the saved SQLite database to the mounted `/data` volume using a
   verified copy; do not overwrite an active database or delete active
   `-wal`/`-shm` files.
3. Roll back to the previous application version if necessary. Its existing
   `file_id` references remain in the database, and uploaded items remain
   available through Telegram as long as Telegram still accepts those IDs.
4. Keep the Drive files and current database backup until the rollback and
   restored user flows have been verified.

The integration does not automatically perform a destructive production
migration or delete legacy media references.
