"""用法: python -m backend.main [init-db|shopping|jobs|jobs-verify|briefing|healthcheck|test-notify|backup]"""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from . import config, database, briefing, notification
from .shopping import monitor
from .email import gmail
from .tasks import calendar
from .jobs import scraper


def healthcheck():
    errors = database.query("SELECT COUNT(*) AS c FROM scraper_logs WHERE status='error'")[0]["c"]
    if errors:
        notification.notify(f"health:{datetime.now():%Y-%m-%d}", "⚠️ MyLife OS 运行错误",
                            f"累计 {errors} 条错误记录，请查看 scraper_logs。")


def backup():
    out = Path("backups"); out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if database.is_sqlite():
        shutil.copy(config.DATABASE_URL.replace("sqlite:///", ""), out / f"mylife_{stamp}.db")
    else:
        with open(out / f"mylife_{stamp}.sql", "wb") as f:
            subprocess.run(["pg_dump", config.DATABASE_URL], stdout=f, check=True)


COMMANDS = {
    "init-db": database.init_schema,
    "shopping": monitor.run,
    "gmail": gmail.run,
    "calendar": calendar.run,
    "jobs": scraper.run,
    "jobs-verify": scraper.verify,
    "briefing": briefing.send,
    "healthcheck": healthcheck,
    "backup": backup,
    "test-notify": lambda: notification.notify(
        f"test:{datetime.now().isoformat()}", "MyLife OS 测试通知", "Telegram / Email 通道正常 ✅"),
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        sys.exit(__doc__)
    database.init_schema()
    COMMANDS[cmd]()
