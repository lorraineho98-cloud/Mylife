"""Google Calendar（只读）：同步未来 2 天的日程。"""
from datetime import datetime, timedelta, timezone
from .. import database, google_auth

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def run(days=2):
    now = datetime.now(timezone.utc)
    data = google_auth.get(API, {
        "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(),
        "singleEvents": "true", "orderBy": "startTime"})
    for ev in data.get("items", []):
        start = ev["start"].get("dateTime") or ev["start"].get("date")
        database.execute(
            "INSERT INTO calendar_events (event_id, title, starts_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (event_id) DO UPDATE SET title=excluded.title, starts_at=excluded.starts_at",
            (ev["id"], ev.get("summary", "(无标题)"), start))
    database.log_scrape("calendar", "primary", "ok")
