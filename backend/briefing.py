"""每日生活摘要 + 运行状态。"""
from datetime import date
from . import database, notification


def count(sql):
    return database.query(sql)[0]["c"]


def build():
    prices = count("SELECT COUNT(*) AS c FROM price_history WHERE DATE(checked_at)=DATE('now')") \
        if database.is_sqlite() else \
        count("SELECT COUNT(*) AS c FROM price_history WHERE checked_at::date = CURRENT_DATE")
    errors = database.query("SELECT module, target, error FROM scraper_logs WHERE status='error' "
                            "ORDER BY id DESC LIMIT 5")
    tasks = count("SELECT COUNT(*) AS c FROM tasks WHERE status='open'")
    mails = count("SELECT COUNT(*) AS c FROM emails WHERE action_needed=1")
    events = database.query("SELECT title, starts_at FROM calendar_events ORDER BY starts_at LIMIT 5")
    lines = [f"MyLife OS · Daily Briefing · {date.today()}",
             f"商品价格检查: {prices}", f"待办事项: {tasks}", f"需处理邮件: {mails}"]
    lines += [f"📅 {e['starts_at']} {e['title']}" for e in events]
    lines.append("系统状态: 正常" if not errors else f"系统状态: ⚠️ 最近 {len(errors)} 条错误")
    lines += [f"  - {e['module']}: {e['error']}" for e in errors]
    return "\n".join(lines)


def send():
    text = build()
    return notification.notify(f"briefing:{date.today()}", "MyLife OS 每日摘要", text)
