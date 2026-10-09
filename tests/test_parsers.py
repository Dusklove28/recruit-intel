from collectors.generic import discover_attachments
from parsers.html_parser import parse_html


def test_html_attachment_discovery_resolves_relative_urls_and_keeps_body():
    html = """
    <html><body><nav>无关导航</nav><article>
      <h1>某单位2027届招聘</h1><p>学历要求详见附件1。</p>
      <a href="/files/岗位表.xlsx">附件1：岗位表.xlsx</a>
      <a href="https://example.com/rules.pdf?download=1">招聘办法</a>
      <a href="/other">其他链接</a>
    </article></body></html>
    """
    parsed = parse_html(html)
    attachments = discover_attachments("https://example.com/jobs/notice", parsed.links)

    assert "学历要求详见附件1" in parsed.text
    assert "无关导航" not in parsed.text
    assert [item.url for item in attachments] == [
        "https://example.com/files/岗位表.xlsx",
        "https://example.com/rules.pdf?download=1",
    ]
    assert attachments[0].original_url == "/files/岗位表.xlsx"
