"""Run one-time, interactive OAuth consent and print a refresh token."""

import os
import sys


def main() -> int:
    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print(
            "Set GOOGLE_DRIVE_CLIENT_ID and GOOGLE_DRIVE_CLIENT_SECRET "
            "in this local shell first.",
            file=sys.stderr,
        )
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Install project requirements before running OAuth setup.",
            file=sys.stderr,
        )
        return 2

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        print(
            "Google did not issue a refresh token. Revoke this app's access "
            "and repeat the consent flow.",
            file=sys.stderr,
        )
        return 1

    print(
        "Copy this value directly into Railway Variables as "
        "GOOGLE_DRIVE_REFRESH_TOKEN. Do not share it or commit it:\n"
        f"{credentials.refresh_token}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
