"""购物价格监控：只读公开页面的 schema.org JSON-LD 价格，遵守 robots.txt。"""
import json
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse
import requests
from .. import config, database, notification

WATCHLIST = Path(__file__).resolve().parents[2] / "config" / "watchlist.json"
FEED = Path(__file__).resolve().parents[2] / "data" / "prices_latest.json"


def allowed(url):
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{p.scheme}://{p.netloc}/robots.txt")
    try:
        rp.read()
        return rp.can_fetch(config.USER_AGENT, url)
    except Exception:
        return False  # 无法确认就不抓


def extract_price(html):
    for block in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            offers = node.get("offers") if isinstance(node, dict) else None
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict) and offers.get("price") is not None:
                return float(offers["price"])
    return None


def fetch_price(url, retries=3):
    if not allowed(url):
        raise PermissionError("robots.txt 不允许自动访问")
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=20)
            r.raise_for_status()
            price = extract_price(r.text)
            if price is None:
                raise ValueError("页面没有可读取的价格")
            return price
        except PermissionError:
            raise
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise last


def record_price(item, price):
    database.execute(
        "INSERT INTO products (name, url, volume_ml, target_price) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (url) DO NOTHING",
        (item["name"], item["url"], item.get("volume_ml"), item.get("target_price")))
    pid = database.query("SELECT id FROM products WHERE url=%s", (item["url"],))[0]["id"]
    prev = database.query("SELECT MIN(price) AS m FROM price_history WHERE product_id=%s", (pid,))[0]["m"]
    database.execute("INSERT INTO price_history (product_id, price) VALUES (%s,%s)", (pid, price))
    return prev


def export_feed(item, price, today=None):
    """把价格追加到 data/prices_latest.json（App 同步用）；同一商品同一天只留最新一条。"""
    from datetime import date
    today = today or date.today().isoformat()
    FEED.parent.mkdir(exist_ok=True)
    rows = json.loads(FEED.read_text(encoding="utf-8")) if FEED.exists() else []
    rows = [r for r in rows if not (r["url"] == item["url"] and r["date"] == today)]
    rows.append({"name": item["name"], "store": urlparse(item["url"]).netloc.replace("www.", ""),
                 "price": price, "ml": item.get("volume_ml") or 0, "date": today, "url": item["url"]})
    FEED.write_text(json.dumps(rows[-400:], ensure_ascii=False, indent=1), encoding="utf-8")


def run():
    items = json.loads(WATCHLIST.read_text(encoding="utf-8"))["items"]
    for item in items:
        try:
            price = fetch_price(item["url"])
            prev_min = record_price(item, price)
            export_feed(item, price)
            database.log_scrape("shopping", item["url"], "ok")
            target = item.get("target_price")
            if prev_min is not None and price < prev_min:
                reason = "历史最低价"
            elif target and price <= target:
                reason = "低于目标价"
            else:
                continue
            per100 = f"\n每100ml: RM{price / item['volume_ml'] * 100:.2f}" if item.get("volume_ml") else ""
            notification.notify(f"price:{item['url']}:{price}", f"🛒 {item['name']} {reason}",
                                f"现价 RM{price:.2f}{per100}\n{item['url']}\n（请自行确认后下单）")
        except Exception as e:
            database.log_scrape("shopping", item["url"], "error", str(e))
