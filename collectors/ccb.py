"""Read the one approved, public CCB announcement and its declared PDF.

The announcement HTML is a template. Its own JavaScript calls NHR106 with the
announcement ID. This collector makes only that same-ID request and follows
the PDF URL returned by the public response; it does not enumerate notices.
"""

from dataclasses import replace
from pathlib import Path
import re
import ssl
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter

from collectors.campaign import CampaignBundle
from collectors.generic import AttachmentLink, REQUEST_TIMEOUT, fetch_announcement
from parsers.html_parser import parse_html


CCB_HOST = "job2.ccb.com"
CCB_ANNOUNCEMENT_PATH = "/cn/job/announcement.html"
APPROVED_ANNO_ID = "20260903163254718082"
EXPECTED_TITLE = "中国建设银行总部2027年度校园招聘公告"
DETAIL_API = (
    "https://job2.ccb.com/tran/WCCMainPlatV5?CCB_IBSVersion=V5"
    "&isAjaxRequest=true&SERVLET_NAME=WCCMainPlatV5&TXCODE=NHR106"
)
FILE_DOWNLOAD_PATH = "/tran/FileDownloadZPServlet?param="


class CCBPublicTLSAdapter(HTTPAdapter):
    """Allow this host's legacy TLS handshake while retaining cert checks."""

    def build_connection_pool_key_attributes(self, request, verify, cert):
        host, options = super().build_connection_pool_key_attributes(request, verify, cert)
        context = ssl.create_default_context()
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        options["ssl_context"] = context
        return host, options


def is_ccb_announcement(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == CCB_HOST and parsed.path == CCB_ANNOUNCEMENT_PATH


def create_ccb_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    session.max_redirects = 0  # Never follow a response to another host or page.
    session.mount(f"https://{CCB_HOST}/", CCBPublicTLSAdapter())
    return session


def collect_ccb_campaign(source_url: str, session: requests.Session) -> CampaignBundle:
    if not is_ccb_announcement(source_url):
        raise ValueError("不是建行招聘公告 URL")
    ids = parse_qs(urlparse(source_url).query).get("annoId", [])
    if ids != [APPROVED_ANNO_ID]:
        raise ValueError("当前仅批准读取指定的建行招聘公告，不遍历其他公告")

    shell = fetch_announcement(source_url, session)
    if not is_ccb_announcement(shell.final_url):
        raise ValueError("建行公告跳转离开已批准页面")
    session.cookies.clear()  # Public response cookies are not needed.

    api_url = f"{DETAIL_API}&annoId={APPROVED_ANNO_ID}"
    response = session.get(api_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    if urlparse(response.url).hostname != CCB_HOST or not response.content:
        raise ValueError("建行公开正文接口未返回可用内容")
    detail = response.json()
    if detail.get("SUCCESS") != "true" or detail.get("annoTitle") != EXPECTED_TITLE:
        raise ValueError("建行公告接口未返回指定公告")
    content = detail.get("annoContent")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("建行公告正文为空")
    session.cookies.clear()

    parsed = parse_html(content)
    page = replace(
        shell,
        text=(
            f"公告标题：{detail['annoTitle']}\n"
            f"发布单位：{detail.get('annoOrgName') or '未标注'}\n"
            f"公告发布时间：{detail.get('annoDate') or '未标注'}\n"
            f"正文接口：{api_url}\n{parsed.text}"
        ),
        links=parsed.links,
    )
    attachments: list[AttachmentLink] = []
    for item in detail.get("attachList") or []:
        filename = str(item.get("file_Name") or "").strip()
        path_token = str(item.get("filePath") or "")
        if Path(filename).suffix.lower() != ".pdf" or not re.fullmatch(r"[0-9A-Fa-f]+", path_token):
            continue
        original_url = FILE_DOWNLOAD_PATH + path_token
        attachments.append(AttachmentLink(original_url, urljoin(source_url, original_url), filename))
    if not attachments:
        raise ValueError("指定建行公告没有可核验的公开 PDF 附件")
    return CampaignBundle(
        source_url, [page], attachments, [], [], [api_url],
        ("招聘岗位", "工作地点"),
    )
