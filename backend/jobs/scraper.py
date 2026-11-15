"""求职职位抓取。只读公开页面，抓之前检查 robots.txt（无法确认就不抓）。
输出 data/jobs_latest.json（App 可从 GitHub 同步）和 data/jobs_seen.json（记录已见过的职位）。
用法: python -m backend.main jobs | jobs-verify
"""
import hashlib
import html as htmllib
import json
import re
import time
import urllib.robotparser
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "jobs.json"
DATA = ROOT / "data"

RANGE = re.compile(
    r"(?:RM|MYR)\s?([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:-|–|—|to)\s*(?:RM|MYR)?\s?([\d,]+(?:\.\d+)?)\s*(k)?"
    r"(?:\s*(?:per|/|a)\s*(year|annum|month|mth|yr)|\s*(monthly|annually|yearly))?", re.I)


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


# ---------- 解析 ----------
def _num(s, k):
    n = float(s.replace(",", ""))
    return n * 1000 if k else n


def _monthly(lo, hi, period):
    """period: 'year' | 'month' | None（None 时按数值大小猜）。返回月薪 (lo, hi)。"""
    if period is None:
        period = "year" if (hi or lo or 0) >= 30000 else "month"
    f = 12 if period == "year" else 1
    r = lambda x: None if x is None else int(round(x / f))
    return r(lo), r(hi)


def parse_salary_text(text):
    """从文本找 'RM 4,500 – RM 6,000 per month' / 'MYR55,000 - MYR90,000 per year'，换算成月薪。"""
    m = RANGE.search(text or "")
    if not m:
        return None, None
    lo, hi = _num(m.group(1), m.group(2)), _num(m.group(3), m.group(4))
    word = (m.group(5) or m.group(6) or "").lower()
    period = "year" if word[:1] in ("y", "a") else "month" if word[:1] == "m" else None
    return _monthly(lo, hi, period)


def salary_from_jsonld(base):
    if not isinstance(base, dict):
        return None, None
    val = base.get("value")
    if not isinstance(val, dict):
        val = {"minValue": val, "maxValue": val} if val not in (None, "") else {}
    try:
        lo = float(val["minValue"]) if val.get("minValue") not in (None, "") else None
        hi = float(val["maxValue"]) if val.get("maxValue") not in (None, "") else lo
    except (ValueError, TypeError):
        return None, None
    unit = str(val.get("unitText", "")).upper()
    period = "year" if "YEAR" in unit else "month" if "MONTH" in unit else None
    return _monthly(lo, hi, period)


def strip_tags(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def jsonld_nodes(h):
    for block in re.findall(r"<script[^>]*ld\+json[^>]*>(.*?)</script>", h, re.S | re.I):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                if "@graph" in n:
                    stack.extend(n["@graph"])
                yield n


def _loc(node):
    jl = node.get("jobLocation")
    jl = jl[0] if isinstance(jl, list) and jl else jl
    addr = jl.get("address", {}) if isinstance(jl, dict) else {}
    if isinstance(addr, dict):
        return ", ".join(str(addr.get(k)) for k in ("addressLocality", "addressRegion") if addr.get(k))
    return str(addr or "")


def _day(s):
    return str(s)[:10] if s and re.match(r"\d{4}-\d{2}-\d{2}", str(s)) else ""


def parse_job(h, url, source):
    """返回职位 dict；找不到标题就返回 None。"""
    text = strip_tags(h)
    job = {"title": "", "company": "", "location": "", "salary_min": None, "salary_max": None,
           "url": url, "posted": "", "valid_through": "", "source": source}
    for n in jsonld_nodes(h):
        if str(n.get("@type", "")).lower() == "jobposting":
            org = n.get("hiringOrganization")
            job.update(title=str(n.get("title", "")).strip(),
                       company=(org.get("name") if isinstance(org, dict) else str(org or "")),
                       location=_loc(n), posted=_day(n.get("datePosted")),
                       valid_through=_day(n.get("validThrough")))
            job["salary_min"], job["salary_max"] = salary_from_jsonld(n.get("baseSalary"))
            desc = strip_tags(str(n.get("description", "")))
            text = (desc + " " + text) if desc else text
            break
    if not job["title"]:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S | re.I) or re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I)
        job["title"] = strip_tags(m.group(1)) if m else ""
    if not job["title"]:
        return None
    if job["salary_min"] is None and job["salary_max"] is None:
        job["salary_min"], job["salary_max"] = parse_salary_text(text[:30000])
    if not job["location"] and re.search(r"kuala lumpur", text, re.I):
        job["location"] = "Kuala Lumpur"
    job["hybrid"] = bool(re.search(r"hybrid|work from home", text, re.I))
    job["_text"] = text[:1500]
    return job


# ---------- 筛选 ----------
def keep(job, cfg, today=None):
    """返回 (是否保留, 原因)。"""
    today = today or date.today()
    title = job["title"].lower()
    blob = (title + " " + job.get("_text", "")).lower()
    if any(x in title for x in cfg["exclude_title"]):
        return False, "排除职称"
    if not any(k in blob for k in cfg["must_match_any"]):
        return False, "不相关"
    loc = job.get("location", "").lower()
    if loc and not any(k in loc for k in cfg["location_any"]):
        return False, "地点不符"
    top = job["salary_max"] if job["salary_max"] is not None else job["salary_min"]
    if top is None:
        if not cfg.get("keep_unknown_salary", True):
            return False, "薪资未公开"
    elif top < cfg["min_salary_month"]:
        return False, "薪资过低"
    if job["valid_through"] and job["valid_through"] < today.isoformat():
        return False, "已过期"
    if job["posted"]:
        try:
            if (today - date.fromisoformat(job["posted"])).days > cfg["max_age_days"]:
                return False, "发布太久"
        except ValueError:
            pass
    return True, ""


def find_links(h, base, pattern, limit):
    if not pattern:
        return []
    out = []
    for m in re.finditer(pattern, h):
        u = urljoin(base, m.group(0))
        if u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


# ---------- 网络（requests 延迟导入，方便离线测试） ----------
class Fetcher:
    def __init__(self, cfg):
        import requests
        from .. import config
        self.s = requests.Session()
        self.s.headers["User-Agent"] = config.USER_AGENT
        self.delay = cfg.get("delay_seconds", 2.0)
        self.robots = {}

    def allowed(self, url):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=15)
                if r.status_code == 404:
                    rp.parse([])  # 没有 robots.txt = 无限制
                elif r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # 无法确认就不抓
            except Exception:
                rp = None
            self.robots[base] = rp
        rp = self.robots[base]
        from .. import config
        return bool(rp and rp.can_fetch(config.USER_AGENT, url))

    def get(self, url):
        """返回 (html, 原因)。不允许或失败时 html 为 None。"""
        if not self.allowed(url):
            return None, "robots.txt 不允许或无法确认"
        time.sleep(self.delay)
        try:
            r = self.s.get(url, timeout=20)
        except Exception as e:
            return None, f"请求失败: {e}"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.text, ""


def search_urls(src, cfg):
    out = []
    for t in src.get("search_urls", []):
        if "{kw" in t:
            out += [t.format(kw=quote_plus(k), kw_slug=k.replace(" ", "-")) for k in cfg["keywords"]]
        else:
            out.append(t)
    return out


def collect(cfg, fetcher, report=None):
    """抓所有来源，返回 (保留的职位列表, 统计)。"""
    stats, jobs, seen_urls = [], [], set()
    targets = []
    for src in cfg["sources"]:
        if not src.get("enabled"):
            continue
        links = []
        for su in search_urls(src, cfg):
            h, why = fetcher.get(su)
            n = find_links(h, su, src["link_pattern"], cfg["max_links_per_source"]) if h else []
            stats.append(f"[{src['name']}] 搜索页 {su} → " + (f"{len(n)} 个职位链接" if h else f"跳过（{why}）"))
            links += [u for u in n if u not in links]
        targets += [(src["name"], u) for u in links[:cfg["max_links_per_source"]]]
    targets += [("已知职位", u) for u in cfg.get("seed_urls", [])]
    for name, u in targets:
        if u in seen_urls:
            continue
        seen_urls.add(u)
        h, why = fetcher.get(u)
        if not h:
            stats.append(f"  × {u} {why}")
            continue
        job = parse_job(h, u, name)
        if not job:
            stats.append(f"  × {u} 读不到标题")
            continue
        ok, reason = keep(job, cfg)
        stats.append(f"  {'✓' if ok else '×'} {job['title'][:50]} {'' if ok else '(' + reason + ')'}")
        if ok:
            jobs.append(job)
    return jobs, stats


def to_feed(jobs):
    jobs.sort(key=lambda j: -(j["salary_max"] or j["salary_min"] or 0))
    return [{k: j[k] for k in ("title", "company", "location", "salary_min", "salary_max", "url",
                                "posted", "source", "hybrid")} for j in jobs]


def run(dry_run=False):
    cfg = load_config()
    fetcher = Fetcher(cfg)
    jobs, stats = collect(cfg, fetcher)
    print("\n".join(stats))
    feed = to_feed(jobs)
    seen_p, feed_p = DATA / "jobs_seen.json", DATA / "jobs_latest.json"
    seen = json.loads(seen_p.read_text(encoding="utf-8")) if seen_p.exists() else {}
    new = [j for j in feed if j["url"] not in seen]
    print(f"保留 {len(feed)} 个，其中新职位 {len(new)} 个")
    if not feed:
        print("⚠️ 没有符合条件的职位。如果上面的搜索页都显示 0 个链接或跳过，请运行 jobs-verify 检查网址。")
    if dry_run:
        return feed
    DATA.mkdir(exist_ok=True)
    feed_p.write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    today = date.today().isoformat()
    for j in feed:
        seen.setdefault(j["url"], {"first_seen": today, "title": j["title"]})
    seen_p.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    if new:
        from .. import notification
        lines = []
        for j in new[:10]:
            sal = (f"RM{j['salary_min'] or '?'}–{j['salary_max']}/月" if j["salary_max"] else "薪资未公开")
            lines.append(f"• {j['title']} — {j['company'] or j['source']} — {sal}\n  {j['url']}")
        key = "jobs:" + hashlib.sha1("".join(sorted(j["url"] for j in new)).encode()).hexdigest()[:12]
        notification.notify(key, f"💼 发现 {len(new)} 个新职位", "\n".join(lines))
    return feed


def verify():
    """不写文件，逐个来源报告：robots 是否允许、找到多少链接、能解析多少职位。"""
    cfg = load_config()
    jobs, stats = collect(cfg, Fetcher(cfg))
    print("\n".join(stats))
    print(f"\n合计通过筛选 {len(jobs)} 个。某个来源显示'0 个职位链接'或'跳过'，说明网址格式要调整或该站不允许抓取。")
