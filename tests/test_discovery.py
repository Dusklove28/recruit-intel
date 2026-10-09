from collectors.discovery import parse_listing, recent_sasac_pages
from storage.candidates import save_candidates, update_candidate
from storage.database import connect_database


def test_official_listing_only_yields_explicit_2027_campus_links(tmp_path):
    html = '''<a href="/a">甲集团2027届校园招聘</a>
    <a href="/b">乙集团2026届校园招聘</a>
    <a href="/c">丙公司2027年社会招聘</a>
    <a href="/a">甲集团2027届校园招聘</a>'''
    items = parse_listing(html, "https://gzw.example/list", "测试国资委")
    assert len(items) == 1
    assert items[0].notice_url == "https://gzw.example/a"
    with connect_database(tmp_path / "jobs.sqlite3") as database:
        assert save_candidates(database, items) == 1
        assert save_candidates(database, items) == 0
        state = database.execute("SELECT state FROM candidates").fetchone()[0]
        assert state == "待核验"
        update_candidate(database, items[0].notice_url, "正式收录", official_url="https://company.example/campus")
        state, official = database.execute("SELECT state, official_url FROM candidates").fetchone()
        assert (state, official) == ("正式收录", "https://company.example/campus")


def test_sasac_recent_archive_pages_are_bounded():
    html = "".join(f'<a href="index_7325475_{i}.html"></a>' for i in range(1, 12))
    pages = recent_sasac_pages(html, "http://wap.sasac.gov.cn/list/index.html")
    assert len(pages) == 6
    assert pages[0].endswith("_6.html")
    assert pages[-1].endswith("_11.html")
