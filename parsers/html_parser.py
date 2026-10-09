"""Extract visible announcement text and links from HTML."""

from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class HTMLLink:
    href: str
    text: str


@dataclass(frozen=True)
class HTMLDocument:
    text: str
    links: list[HTMLLink]


def parse_html(html: str) -> HTMLDocument:
    soup = BeautifulSoup(html, "lxml")
    links = [
        HTMLLink(anchor["href"].strip(), anchor.get_text(" ", strip=True))
        for anchor in soup.select("a[href]")
        if anchor["href"].strip()
    ]
    for node in soup.select("script, style, noscript, nav, header, footer, form"):
        node.decompose()
    candidates = soup.select("article, main, .article, .content, .detail, #content")
    body = max(candidates, key=lambda node: len(node.get_text(" ", strip=True)), default=soup.body or soup)
    text = "\n".join(part.strip() for part in body.stripped_strings if part.strip())
    return HTMLDocument(text=text, links=links)
