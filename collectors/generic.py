"""Generic collector for a single public HTML announcement URL."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlparse

import requests

from adapters.base import HEADERS
from parsers.html_parser import HTMLLink, parse_html


ATTACHMENT_SUFFIXES = {".pdf", ".xls", ".xlsx", ".docx"}
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
REQUEST_TIMEOUT = (10, 30)


@dataclass(frozen=True)
class AttachmentLink:
    original_url: str
    url: str
    filename: str


@dataclass(frozen=True)
class Announcement:
    source_url: str
    final_url: str
    text: str
    links: list[HTMLLink]
    attachments: list[AttachmentLink]
    html: str = ""


def _check_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("仅支持公开的 HTTP/HTTPS 公告 URL")


def discover_attachments(base_url: str, links: list[HTMLLink]) -> list[AttachmentLink]:
    found: list[AttachmentLink] = []
    seen: set[str] = set()
    for link in links:
        resolved = urljoin(base_url, link.href)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"}:
            continue
        path_name = Path(unquote(parsed.path)).name
        text_name = link.text.strip()
        path_suffix = Path(path_name).suffix.lower()
        text_suffix = Path(text_name).suffix.lower()
        if path_suffix not in ATTACHMENT_SUFFIXES and text_suffix not in ATTACHMENT_SUFFIXES:
            continue
        filename = path_name if path_suffix in ATTACHMENT_SUFFIXES else text_name
        if resolved not in seen:
            found.append(AttachmentLink(link.href, resolved, filename))
            seen.add(resolved)
    return found


def fetch_announcement(url: str, session: requests.Session | None = None) -> Announcement:
    _check_http_url(url)
    client = session or requests.Session()
    response = client.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
    response.raise_for_status()
    final_url = response.url
    _check_http_url(final_url)
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    parsed = parse_html(response.text)
    return Announcement(
        source_url=url,
        final_url=final_url,
        text=parsed.text,
        links=parsed.links,
        attachments=discover_attachments(final_url, parsed.links),
        html=response.text,
    )


def download_attachment(
    link: AttachmentLink, destination_dir: Path, session: requests.Session | None = None
) -> Path:
    _check_http_url(link.url)
    destination_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", link.filename).strip(" .")[:100]
    if not safe_name or Path(safe_name).suffix.lower() not in ATTACHMENT_SUFFIXES:
        raise ValueError("附件文件名缺少支持的扩展名")
    digest = hashlib.sha256(link.url.encode("utf-8")).hexdigest()[:12]
    destination = destination_dir / f"{digest}_{safe_name}"
    client = session or requests.Session()
    try:
        with client.get(link.url, timeout=REQUEST_TIMEOUT, stream=True, headers=HEADERS) as response:
            response.raise_for_status()
            size = 0
            with destination.open("wb") as output:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise ValueError("附件超过 30 MB 限制")
                    output.write(chunk)
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise
