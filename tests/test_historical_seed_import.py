from openpyxl import Workbook

from discovery.historical_seed_import import load_priority_batch


def test_priority_import_requires_a_tier_history_domain_and_non_wechat(tmp_path):
    path = tmp_path / "history.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "高价值Seed"
    sheet.append([
        "公司名称", "匹配Key", "历史记录数", "覆盖批次数", "出现批次", "最近出现",
        "历史代表URL", "候选根入口", "入口复用等级", "建议平台", "建议域名", "URL特征",
        "投递域名稳定度", "核验状态",
    ])
    sheet.append(["甲集团", "甲", 8, 4, "2025春/秋;2026春/秋", "2026秋", "https://jobs.a.cn/2026", "https://jobs.a.cn/", "A-高", "北森", "jobs.a.cn", None, 1, None])
    sheet.append(["乙集团", "乙", 3, 2, "2025秋;2026秋", "2026秋", "https://mp.weixin.qq.com/old", "https://jobs.b.cn/", "A-高", "自建", "jobs.b.cn", None, 1, None])
    sheet.append(["丙集团", "丙", 8, 4, "2025春/秋;2026春/秋", "2026秋", "https://jobs.c.cn/2026", "https://jobs.c.cn/", "B-高", "自建", "jobs.c.cn", None, 1, None])
    workbook.save(path)

    records = load_priority_batch(path, limit=1)
    assert len(records) == 1
    assert records[0].canonical_name == "甲集团"
    assert records[0].historical_url.endswith("/2026")
    assert records[0].candidate_root_url == "https://jobs.a.cn/"


def test_priority_import_deduplicates_company_names(tmp_path):
    path = tmp_path / "history.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "高价值Seed"
    sheet.append([
        "公司名称", "匹配Key", "历史记录数", "覆盖批次数", "出现批次", "最近出现",
        "历史代表URL", "候选根入口", "入口复用等级", "建议平台", "建议域名", "URL特征",
        "投递域名稳定度", "核验状态",
    ])
    for n in range(2):
        sheet.append(["甲集团", "甲", 8 + n, 4, "四季", "2026秋", f"https://jobs.a.cn/{n}", "https://jobs.a.cn/", "A-高", "自建", "jobs.a.cn", None, 1, None])
    workbook.save(path)

    records = load_priority_batch(path, limit=1)
    assert len(records) == 1
    assert records[0].historical_records == 9
