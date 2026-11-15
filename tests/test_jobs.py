from datetime import date
from backend.jobs import scraper as sc

CFG = {"must_match_any": ["export", "customer service"], "exclude_title": ["intern"],
       "location_any": ["kuala lumpur", "malaysia"], "min_salary_month": 6000,
       "keep_unknown_salary": True, "max_age_days": 45}
TODAY = date(2026, 11, 15)


def page(title="Export Customer Service Executive", sal='{"@type":"MonetaryAmount","currency":"MYR","value":{"minValue":72000,"maxValue":90000,"unitText":"YEAR"}}',
         extra='"datePosted":"2026-11-01","validThrough":"2026-12-31"'):
    return ('<html><script type="application/ld+json">{"@type":"JobPosting","title":"%s","hiringOrganization":{"name":"ABC Sdn Bhd"},'
            '"jobLocation":{"address":{"addressLocality":"Kuala Lumpur"}},"baseSalary":%s,%s,"description":"<p>Hybrid role</p>"}</script></html>'
            % (title, sal, extra))


def test_salary_text():
    assert sc.parse_salary_text("RM 4,500 – RM 6,000 per month") == (4500, 6000)
    assert sc.parse_salary_text("MYR55,000 - MYR90,000 per year") == (4583, 7500)
    assert sc.parse_salary_text("RM8k - 10k") == (8000, 10000)
    assert sc.parse_salary_text("no salary here") == (None, None)


def test_parse_jsonld_job():
    j = sc.parse_job(page(), "https://x.test/j1", "T")
    assert j["title"] == "Export Customer Service Executive" and j["company"] == "ABC Sdn Bhd"
    assert (j["salary_min"], j["salary_max"]) == (6000, 7500)
    assert j["location"] == "Kuala Lumpur" and j["hybrid"] and j["posted"] == "2026-11-01"
    assert sc.keep(j, CFG, TODAY) == (True, "")


def test_filters():
    low = sc.parse_job(page(sal='{"value":{"minValue":3000,"maxValue":4000,"unitText":"MONTH"}}'), "u", "T")
    assert sc.keep(low, CFG, TODAY) == (False, "薪资过低")
    exp = sc.parse_job(page(extra='"validThrough":"2026-08-31"'), "u", "T")
    assert sc.keep(exp, CFG, TODAY) == (False, "已过期")
    old = sc.parse_job(page(extra='"datePosted":"2026-01-01"'), "u", "T")
    assert sc.keep(old, CFG, TODAY) == (False, "发布太久")
    intern = sc.parse_job(page(title="Export Intern"), "u", "T")
    assert sc.keep(intern, CFG, TODAY) == (False, "排除职称")
    unrelated = sc.parse_job(page(title="Graphic Designer"), "u", "T")
    assert sc.keep(unrelated, CFG, TODAY) == (False, "不相关")
    nosal = sc.parse_job(page(sal="null"), "u", "T")
    assert sc.keep(nosal, CFG, TODAY)[0] is True  # 薪资未公开默认保留


def test_fallback_html_without_jsonld():
    h = "<html><h1>Export Customer Service</h1><p>Kuala Lumpur. RM 6,500 - RM 8,000 per month. Hybrid.</p></html>"
    j = sc.parse_job(h, "u", "T")
    assert (j["salary_min"], j["salary_max"]) == (6500, 8000) and j["location"] == "Kuala Lumpur"


def test_find_links_and_search_urls():
    h = '<a href="/job-detail/a/ref/1">A</a><a href="/job-detail/a/ref/1">A</a><a href="/job-detail/b/ref/2">B</a>'
    assert sc.find_links(h, "https://s.test/jobs", r"/job-detail/[^\"'#?\s<>]+", 10) == [
        "https://s.test/job-detail/a/ref/1", "https://s.test/job-detail/b/ref/2"]
    cfg = {"keywords": ["export customer service"]}
    assert sc.search_urls({"search_urls": ["https://s.test/{kw_slug}?q={kw}"]}, cfg) == [
        "https://s.test/export-customer-service?q=export+customer+service"]


def test_collect_with_fake_fetcher():
    class Fake:
        def get(self, url):
            if "search" in url:
                return '<a href="/job-detail/x/1">x</a>', ""
            if url.endswith("/job-detail/x/1"):
                return page(), ""
            return None, "HTTP 404"
    cfg = dict(CFG, keywords=["a"], max_links_per_source=5,
               sources=[{"name": "S", "enabled": True, "search_urls": ["https://s.test/search"], "link_pattern": "/job-detail/[^\"'#?\\s<>]+"}],
               seed_urls=["https://s.test/gone"])
    jobs, stats = sc.collect(cfg, Fake())
    assert len(jobs) == 1 and any("HTTP 404" in s for s in stats)
    feed = sc.to_feed(jobs)
    assert feed[0]["salary_max"] == 7500 and "_text" not in feed[0]


def test_price_feed_export(tmp_path, monkeypatch):
    import json
    from backend.shopping import monitor
    monkeypatch.setattr(monitor, "FEED", tmp_path / "p.json")
    item = {"name": "洗发水", "url": "https://www.shop.test/a", "volume_ml": 700}
    monitor.export_feed(item, 20.0, "2026-11-15")
    monitor.export_feed(item, 18.5, "2026-11-15")   # 同一天覆盖
    monitor.export_feed(item, 19.0, "2026-11-16")
    rows = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert [r["price"] for r in rows] == [18.5, 19.0] and rows[0]["store"] == "shop.test" and rows[0]["ml"] == 700
