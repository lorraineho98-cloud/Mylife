"""Gmail（只读）：只提取分类/发件人/主题/金额，不保存正文和附件。"""
import re
from datetime import date
from .. import database, google_auth

API = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
BILL = re.compile(r"invoice|bill|statement|receipt|payment|账单|发票|收据|缴费", re.I)
ACTION = re.compile(r"due|overdue|action required|verify|confirm|reminder|到期|逾期|请确认", re.I)
AMOUNT = re.compile(r"(?:RM|MYR)\s?([\d,]+(?:\.\d{1,2})?)", re.I)


def classify(subject, snippet):
    text = f"{subject} {snippet}"
    category = "bill" if BILL.search(text) else "other"
    m = AMOUNT.search(text)
    amount = float(m.group(1).replace(",", "")) if m else None
    return category, bool(ACTION.search(text)), amount


def sender_name(raw):
    return re.sub(r"<.*?>", "", raw).strip(' "') or raw


def run(days=2):
    listing = google_auth.get(API, {"q": f"newer_than:{days}d", "maxResults": 50})
    for ref in listing.get("messages", []):
        mid = ref["id"]
        if database.query("SELECT 1 AS x FROM emails WHERE message_id=%s", (mid,)):
            continue
        msg = google_auth.get(f"{API}/{mid}", {"format": "metadata",
                              "metadataHeaders": ["From", "Subject"]})
        h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
        subject, sender = h.get("Subject", ""), sender_name(h.get("From", ""))
        category, action, amount = classify(subject, msg.get("snippet", ""))
        database.execute(
            "INSERT INTO emails (message_id, category, summary, action_needed) VALUES (%s,%s,%s,%s)",
            (mid, category, f"{sender}: {subject}"[:200], int(action)))
        if category == "bill" and amount:
            database.execute(
                "INSERT INTO expenses (vendor, amount, category, spent_on, source) VALUES (%s,%s,%s,%s,%s)",
                (sender, amount, "bill", date.today().isoformat(), "gmail"))
        if action:
            database.execute(
                "INSERT INTO tasks (title, status, source) VALUES (%s,'open','email')",
                (f"处理邮件: {subject}"[:150],))
    database.log_scrape("gmail", "inbox", "ok")
