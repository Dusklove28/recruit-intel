"""Identify a public recruitment platform from URL and page clues."""

import re
from urllib.parse import urlparse


def detect_platform(url: str, html: str = "", official_domain: str | None = None) -> str:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    page = html[:200_000].lower()
    if host == "app.mokahr.com" or host.endswith(".mokahr.com") or "mokahr" in page:
        return "moka"
    if host.endswith(".zhiye.com") or "getjobadpagelist" in page:
        return "beisen"
    if host.endswith(".jobs.feishu.cn") or host.endswith(".jobs.f.mioffice.cn") or "atsx-pagination" in page:
        return "feishu"
    if host == "campus.51job.com" or ("51job" in host and re.search(r"campus|xyzp", path)):
        return "51job_campus"
    if host.endswith(".hotjob.cn") or host == "hotjob.cn":
        return "hotjob"
    if host == "campus.chinahr.com" or host.endswith(".chinahr.com"):
        return "chinahr"
    if host == "campus.zhaopin.com" or host.endswith(".zhaopin.com.cn") or host.endswith(".zhaopin.com"):
        return "zhilian"
    if host.endswith(".weixin.qq.com") or host == "mp.weixin.qq.com":
        return "wechat"
    if host.endswith(".iguopin.com") or host == "iguopin.com" or host.endswith(".iguopin.cn"):
        return "iguopin"
    domain = (official_domain or "").lower().lstrip(".")
    if domain and (host == domain or host.endswith("." + domain)):
        return "custom"
    return "unknown"
