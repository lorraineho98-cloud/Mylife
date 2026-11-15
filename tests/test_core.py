import os
import pytest

@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    from backend import config, database
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    database.init_schema()

def test_extract_price():
    from backend.shopping.monitor import extract_price
    html = '<script type="application/ld+json">{"@type":"Product","offers":{"price":"12.90"}}</script>'
    assert extract_price(html) == 12.9
    assert extract_price("<html></html>") is None

def test_notification_dedup(monkeypatch):
    from backend import notification
    monkeypatch.setattr(notification, "send_telegram", lambda t: True)
    monkeypatch.setattr(notification, "send_email", lambda s, b: False)
    assert notification.notify("k1", "t", "b") is True
    assert notification.notify("k1", "t", "b") is False  # 不重复发送

def test_price_history_and_log():
    from backend import database
    from backend.shopping import monitor
    item = {"name": "A", "url": "https://x.test/a"}
    assert monitor.record_price(item, 10.0) is None
    assert monitor.record_price(item, 8.0) == 10.0
    database.log_scrape("shopping", "u", "error", "boom")
    from backend import briefing
    assert "错误" in briefing.build()
