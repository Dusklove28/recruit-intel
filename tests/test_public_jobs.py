from collectors.public_jobs import JobDetail, StructuredJobs, _extract_section


def test_job_detail_sections_and_aggregate_fields():
    text = "专业要求：机械、电气相关专业 岗位职责：维护设备 任职资格：持有电工证优先"
    assert _extract_section(text, "专业要求", r"岗位职责|任职资格") == "机械、电气相关专业"
    assert _extract_section(text, "任职资格|任职要求", r"岗位职责|专业要求") == "持有电工证优先"

    jobs = StructuredJobs(
        campaign_page_url="https://campus.51job.com/cofco/campus.html",
        listing_url="https://be.51job.com/zhongliang/index.php/index/position_list",
        detail_api_url="https://coapi.51job.com/job_detail.php",
        total_jobs=3,
        jobs=[
            {"jobId": "1", "degree": "本科", "address": "北京"},
            {"jobId": "2", "degree": "硕士", "address": "上海"},
            {"jobId": "3", "degree": "大专", "address": "北京"},
        ],
        details=[JobDetail("1", "设备岗", "本科", "北京", "机械、电气相关专业", "持有电工证优先", text)],
        warnings=[],
    )
    assert jobs.education_summary == "大专、本科、硕士（各岗位要求不同）"
    assert jobs.location_summary == "北京、上海"
    assert "机械、电气相关专业" in jobs.prompt_summary()
