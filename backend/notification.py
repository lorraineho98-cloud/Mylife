"""Telegram + Email 通知，带去重（同一 dedup_key 只发一次）。"""
import smtplib
from email.message import EmailMessage
import requests
from . import config, database


def send_telegram(text):
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text}, timeout=20)
    r.raise_for_status()
    return True


def send_email(subject, body):
    if not (config.SMTP_USER and config.SMTP_PASSWORD and config.EMAIL_TO):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, config.SMTP_USER, config.EMAIL_TO
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)
    return True


def notify(dedup_key, title, body):
    """返回 True=已发送，False=重复或未配置渠道。"""
    if database.query("SELECT 1 AS x FROM notifications WHERE dedup_key=%s", (dedup_key,)):
        return False
    sent = []
    for name, fn in (("telegram", lambda: send_telegram(f"{title}\n\n{body}")),
                     ("email", lambda: send_email(title, body))):
        try:
            if fn():
                sent.append(name)
        except Exception as e:  # 一个渠道失败不影响另一个
            database.log_scrape("notification", name, "error", str(e))
    if not sent:
        return False
    database.execute(
        "INSERT INTO notifications (dedup_key, channel, title, status) VALUES (%s,%s,%s,%s)",
        (dedup_key, ",".join(sent), title, "sent"))
    return True
