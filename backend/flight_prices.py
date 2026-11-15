#!/usr/bin/env python3
"""每天查 config/flight_routes.json 里各路线的最低价，写入 data/flights_latest.json。

数据来自 Travelpayouts (Aviasales) Data API，是用户搜索过的缓存价格，
属于参考价，不是实时报价。只用标准库，不需要改 requirements.txt。
需要环境变量 TRAVELPAYOUTS_TOKEN（放在 GitHub Secrets，不要写进代码）。

可选：设置 IGNAV_API_KEY 后，只有当某条路线的缓存价创了新低，才会用
Ignav 的实时接口核对一次（每天最多 live_check.max_per_day 次，
Ignav 的 1000 次免费额度是一次性的，不是每月）。

可选：设置 BARK_KEY（Bark 推送的设备 key）后，当天有路线创新低时，
会合并成一条推送发到手机。自建 Bark 服务器可再设 BARK_SERVER。
key 只放在 GitHub Secrets，不要写进代码。
"""
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "flight_routes.json")
OUT = os.path.join(ROOT, "data", "flights_latest.json")
API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"
LIVE_API = "https://ignav.com/api/fares/one-way"
KEEP_DAYS = 120


def today_myt():
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    return now.strftime("%Y-%m-%d")


def fetch_cheapest(route, token, currency):
    params = {
        "origin": route["origin"],
        "destination": route["destination"],
        "departure_at": route["depart"],
        "sorting": "price",
        "direct": "false",
        "currency": currency,
        "limit": 5,
        "page": 1,
    }
    if route.get("return"):
        params["return_at"] = route["return"]
        params["one_way"] = "false"
    else:
        params["one_way"] = "true"
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Access-Token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    data = body.get("data") or []
    if not body.get("success", True) or not data:
        return None
    best = min(data, key=lambda x: x.get("price") or 1e12)
    if not best.get("price"):
        return None
    link = best.get("link") or ""
    return {
        "price": best["price"],
        "airline": best.get("airline", ""),
        "departure_at": best.get("departure_at", ""),
        "url": SITE + link if link.startswith("/") else link,
    }


def fetch_live(origin, destination, date, key, market):
    """用 Ignav 查某一天的实时最低价；失败返回 None（失败的请求不计费）。"""
    tries = ([{"market": market}] if market else []) + [{}]
    for extra in tries:
        payload = {"origin": origin, "destination": destination, "departure_date": date}
        payload.update(extra)
        req = urllib.request.Request(
            LIVE_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={"X-Api-Key": key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                body = json.load(r)
        except Exception as e:
            print("实时核对失败 %s-%s: %s" % (origin, destination, e), file=sys.stderr)
            continue
        prices = [(i.get("price") or {}) for i in (body.get("itineraries") or [])]
        prices = [p for p in prices if p.get("amount")]
        if prices:
            best = min(prices, key=lambda p: p["amount"])
            return {"price": best["amount"], "currency": best.get("currency", "")}
    return None


def send_bark(lows, key, server):
    """把当天所有新低合并成一条 Bark 推送。失败只打印，不影响任务。"""
    server = (server or "https://api.day.app").rstrip("/")
    lines = []
    for x in lows:
        line = "%s %s %s" % (x["name"], x["price"], x["currency"].upper())
        if x.get("live"):
            line += "（实时核对 %s %s）" % (x["live"]["price"], x["live"]["currency"])
        lines.append(line)
    title = "机票新低 %d 条" % len(lows)
    body = "\n".join(lines)
    link = next((x["url"] for x in lows if x.get("url")), "")
    payload = {"device_key": key, "title": title, "body": body, "group": "flights"}
    if link:
        payload["url"] = link
    try:
        req = urllib.request.Request(
            server + "/push",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print("已发送 Bark 推送：%s" % title)
    except Exception as e:
        print("Bark 推送失败: %s" % e, file=sys.stderr)


def load_previous():
    try:
        with open(OUT, encoding="utf-8") as f:
            return {x["name"]: x for x in json.load(f) if isinstance(x, dict) and x.get("name")}
    except (OSError, ValueError):
        return {}


def main():
    token = os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip()
    if not token:
        print("缺少环境变量 TRAVELPAYOUTS_TOKEN", file=sys.stderr)
        return 1
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    currency = cfg.get("currency", "myr")
    live_cfg = cfg.get("live_check") or {}
    live_key = os.environ.get("IGNAV_API_KEY", "").strip()
    live_on = bool(live_cfg.get("enabled") and live_key)
    live_left = int(live_cfg.get("max_per_day", 2))
    live_min_hist = int(live_cfg.get("min_history", 3))
    bark_key = os.environ.get("BARK_KEY", "").strip()
    bark_server = os.environ.get("BARK_SERVER", "").strip()
    lows = []
    prev = load_previous()
    day = today_myt()
    cutoff = (datetime.date.fromisoformat(day) - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    out, ok = [], 0
    for route in cfg.get("routes", []):
        name = route["name"]
        old = prev.get(name, {})
        history = [h for h in old.get("history", []) if h.get("date", "") >= cutoff]
        rec = {
            "name": name,
            "origin": route["origin"],
            "destination": route["destination"],
            "depart": route["depart"],
            "currency": currency,
            "price": old.get("price"),
            "airline": old.get("airline", ""),
            "departure_at": old.get("departure_at", ""),
            "url": old.get("url", ""),
            "date": old.get("date", ""),
            "history": history,
        }
        if old.get("live"):
            rec["live"] = old["live"]
        try:
            found = fetch_cheapest(route, token, currency)
        except Exception as e:  # 单条路线失败不影响其他路线
            print("失败 %s: %s" % (name, e), file=sys.stderr)
            found = None
        if found:
            rec.update(found)
            rec["date"] = day
            prior = [h["price"] for h in history if h.get("date") != day and h.get("price")]
            rec["history"] = [h for h in history if h.get("date") != day] + [
                {"date": day, "price": found["price"]}
            ]
            ok += 1
            dep = (found.get("departure_at") or "")[:10]
            is_low = len(prior) >= live_min_hist and found["price"] < min(prior)
            if is_low:
                lows.append(rec)
            if live_on and live_left > 0 and dep and is_low:
                live_left -= 1
                live = fetch_live(route["origin"], route.get("live_destination", route["destination"]),
                                  dep, live_key, live_cfg.get("market"))
                if live:
                    live.update({"checked_at": day, "departure_date": dep})
                    rec["live"] = live
                    print("  实时核对 %s: %s %s" % (name, live["price"], live["currency"]))
            print("%s: %s %s" % (name, found["price"], currency.upper()))
        else:
            print("没有查到价格: %s" % name)
        if rec["price"]:
            out.append(rec)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("完成：%d / %d 条路线有价格" % (ok, len(cfg.get("routes", []))))
    if bark_key and lows:
        send_bark(lows, bark_key, bark_server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
