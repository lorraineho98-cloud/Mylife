#!/usr/bin/env python3
"""每天按 config/job_feed.json 搜职位，合并多个来源，写入 data/jobs_extra.json。

来源（有哪个 key 就用哪个，至少要有一个）：
  1. Jooble API      —— 环境变量 JOOBLE_API_KEY      （聚合本地招聘站，免费）
  2. JSearch API     —— 环境变量 RAPIDAPI_KEY        （Google for Jobs，覆盖 LinkedIn / Indeed / JobStreet 等）
key 只放在 GitHub Secrets，不要写进代码。只用标准库。

输出字段和 index.html 的“批量导入职位”一致：
title, company, location, salary_min, salary_max, salary_period,
url, posted, source, hybrid。
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "job_feed.json")
OUT = os.path.join(ROOT, "data", "jobs_extra.json")
JOOBLE_API = "https://jooble.org/api/"
JSEARCH_HOST = "jsearch.p.rapidapi.com"
JSEARCH_API = "https://jsearch.p.rapidapi.com/search"

NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?")
TAG = re.compile(r"</?[^>]+>")
HYBRID = re.compile(r"hybrid|wfh|work from home|remote", re.I)


def today_myt():
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    return now.date()


def parse_salary(text):
    """文字薪资 -> (min, max, period)；解析不了返回 (None, None, None)。"""
    if not text:
        return None, None, None
    low = text.lower()
    if re.search(r"hour|/hr|per hr|daily|per day|/day", low):
        return None, None, None
    nums = []
    for m in NUM.finditer(text.replace("\u2013", "-")):
        try:
            n = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            n *= 1000
        if n >= 1000:
            nums.append(n)
    if not nums:
        return None, None, None
    lo, hi = min(nums), max(nums)
    if re.search(r"year|annum|annual|p\.a|/yr|per yr", low) or hi >= 30000:
        period = "year"
    else:
        period = "month"
    return int(lo), int(hi), period


def monthly_top(j):
    hi = j.get("salary_max") if j.get("salary_max") is not None else j.get("salary_min")
    if hi is None:
        return None
    return hi / 12 if j.get("salary_period") == "year" else hi


def http_json(req, timeout=40):
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------- Jooble ----------------
def jooble_search(key, kw, loc):
    req = urllib.request.Request(
        JOOBLE_API + key,
        data=json.dumps({"keywords": kw, "location": loc, "page": 1}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return http_json(req).get("jobs") or []


def jooble_convert(raw):
    title = TAG.sub("", raw.get("title") or "").strip()
    link = (raw.get("link") or "").strip()
    if not title or not link:
        return None
    snippet = TAG.sub(" ", raw.get("snippet") or "")
    lo, hi, period = parse_salary(raw.get("salary") or "")
    j = {
        "title": title,
        "company": (raw.get("company") or "").strip(),
        "location": (raw.get("location") or "").strip(),
        "url": link,
        "posted": (raw.get("updated") or "")[:10],
        "source": (raw.get("source") or "Jooble").strip(),
        "hybrid": bool(HYBRID.search(title + " " + snippet)),
    }
    if lo is not None:
        j["salary_min"], j["salary_max"], j["salary_period"] = lo, hi, period
    return j


# ---------------- JSearch ----------------
def jsearch_search(key, kw, loc, country, date_posted):
    params = {
        "query": "%s jobs in %s" % (kw, loc),
        "page": "1",
        "num_pages": "1",  # 超过 1 页会按 2 倍计费，免费额度很小，保持 1
        "country": country,
        "date_posted": date_posted,
    }
    req = urllib.request.Request(
        JSEARCH_API + "?" + urllib.parse.urlencode(params),
        headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": JSEARCH_HOST},
    )
    return http_json(req).get("data") or []


def jsearch_convert(raw):
    title = (raw.get("job_title") or "").strip()
    link = (raw.get("job_apply_link") or "").strip()
    if not title or not link:
        return None
    loc = ", ".join(x for x in [raw.get("job_city"), raw.get("job_state")] if x)
    j = {
        "title": title,
        "company": (raw.get("employer_name") or "").strip(),
        "location": loc,
        "url": link,
        "posted": (raw.get("job_posted_at_datetime_utc") or "")[:10],
        "source": (raw.get("job_publisher") or "JSearch").strip(),
        "hybrid": bool(raw.get("job_is_remote")) or bool(
            HYBRID.search(title + " " + (raw.get("job_description") or "")[:1500])
        ),
    }
    period = (raw.get("job_salary_period") or "").lower()
    cur = (raw.get("job_salary_currency") or "").upper()
    lo, hi = raw.get("job_min_salary"), raw.get("job_max_salary")
    if (lo or hi) and period in ("month", "year") and cur in ("", "MYR"):
        lo = lo if lo else hi
        hi = hi if hi else lo
        j["salary_min"], j["salary_max"], j["salary_period"] = int(lo), int(hi), period
    return j


# ---------------- 合并 ----------------
def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def main():
    jooble_key = os.environ.get("JOOBLE_API_KEY", "").strip()
    rapid_key = os.environ.get("RAPIDAPI_KEY", "").strip()
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    use_jooble = bool(jooble_key and (cfg.get("jooble") or {}).get("enabled", True))
    js_cfg = cfg.get("jsearch") or {}
    use_jsearch = bool(rapid_key and js_cfg.get("enabled", True))
    if not (use_jooble or use_jsearch):
        print("缺少 JOOBLE_API_KEY 或 RAPIDAPI_KEY（至少设一个）", file=sys.stderr)
        return 1

    min_sal = cfg.get("min_salary_month", 6000)
    max_age = cfg.get("max_age_days", 45)
    per = cfg.get("max_per_search", 40)
    bad = [x.lower() for x in cfg.get("exclude_title", [])]
    today = today_myt()
    js_left = int(js_cfg.get("max_requests_per_run", 6))

    by_url, by_key, out = {}, {}, []
    ok = 0

    def add(j):
        if any(b in j["title"].lower() for b in bad):
            return False
        top = monthly_top(j)
        if top is not None and top < min_sal:
            return False
        if j["posted"]:
            try:
                if (today - datetime.date.fromisoformat(j["posted"])).days > max_age:
                    return False
            except ValueError:
                j["posted"] = ""
        k = norm(j["title"]) + "|" + norm(j["company"])
        old = by_url.get(j["url"]) or (by_key.get(k) if j["company"] else None)
        if old is not None:  # 跨来源重复：只补齐缺失的薪资
            if old.get("salary_min") is None and j.get("salary_min") is not None:
                for f in ("salary_min", "salary_max", "salary_period"):
                    old[f] = j[f]
            return False
        by_url[j["url"]] = j
        if j["company"]:
            by_key[k] = j
        out.append(j)
        return True

    for s in cfg.get("searches", []):
        kw, loc = s["keywords"], s.get("location", "Kuala Lumpur")
        if use_jooble:
            try:
                raws = jooble_search(jooble_key, kw, loc)[:per]
                ok += 1
                n = sum(1 for r in raws if (lambda j: j and add(j))(jooble_convert(r)))
                print("[Jooble] %s: 抓到 %d，新增 %d" % (kw, len(raws), n))
            except Exception as e:
                print("[Jooble] 失败 %s: %s" % (kw, e), file=sys.stderr)
        if use_jsearch and js_left > 0:
            js_left -= 1
            try:
                raws = jsearch_search(rapid_key, kw, loc, js_cfg.get("country", "my"),
                                      js_cfg.get("date_posted", "month"))[:per]
                ok += 1
                n = sum(1 for r in raws if (lambda j: j and add(j))(jsearch_convert(r)))
                print("[JSearch] %s: 抓到 %d，新增 %d" % (kw, len(raws), n))
            except Exception as e:
                print("[JSearch] 失败 %s: %s" % (kw, e), file=sys.stderr)

    if ok == 0:
        print("所有搜索都失败，保留旧文件", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("完成：共 %d 条职位" % len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
