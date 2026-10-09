"""Evidence-first extraction instructions for the 17-field JSON object."""

from extractor.schema import FIELD_NAMES


SYSTEM_PROMPT = """你是招聘公告信息抽取器。仅根据给出的网页正文、附件和链接提取事实，返回一个 JSON 对象，不要 Markdown 或解释。
JSON 必须且只能含指定的17个字段。无法可靠判断时填 null，禁止猜测、编造单位类型、日期、岗位或 URL。
一份公告只生成一条记录；多个岗位按共同要求与差异合理汇总，不逐岗位拆行。
正文若写“详见附件”，必须从提供的附件内容提取实际要求；能读到“本科及以上”就不能只写“详见附件”。
岗位、专业与地点都要按招聘活动汇总，不能把数百个岗位要求逐项罗列。专业/硬性要求请合并相近学科，控制在180个汉字以内，列出主要领域、必要资格差异，并说明依岗位而异；不能用未经证实的概括替代已见到的要求。
不要写“多数岗位”“所有岗位”“普遍要求”等整体判断。只涉及某些岗位的证书、技能、党员身份、倒班、出差或异地调派，必须明确写“部分岗位”。
“专业/硬性要求”只写报考时须具备的资格；入职后的培养、轮岗和跟岗安排不能写成硬性要求。原文对某一专业另设条件时，必须保留适用对象，例如“英语专业毕业生须通过专八”，不得把专八并列成所有人的可选考试。
单位类型和所属集团/主管单位固定填 null；后续由有官方证据的组织名录核验步骤填写。
更新时间固定填 null；它是 RecruitIntel 数据记录最近内容更新时间，由本地保存步骤维护，不是公告发布日期。
日期使用 YYYY-MM-DD；招聘状态只允许：招聘中、即将截止、已截止，无法判断填 null。
报名入口优先采用“投递指引/官方网申入口”的明确链接，不能把普通“招聘岗位”页当作报名入口，不能自行拼接网站地址。
"""


def build_user_prompt(material: str, source_url: str, links: list[tuple[str, str]], today: str) -> str:
    if len(material) > 160_000:
        raise ValueError("公告及附件文本超过 160000 字符，请先确认材料范围；未进行截断抽取。")
    link_lines = "\n".join(f"- {label or '链接'}: {url}" for label, url in links)
    field_lines = "\n".join(f'"{name}": null' for name in FIELD_NAMES)
    return f"""核验日期：{today}
公告 URL：{source_url}

可用页面链接：
{link_lines or '无'}

请输出包含以下17个键的单个 JSON 对象，所有键都必须存在。序号填 1；官方公告填公告 URL；最后核验日期填核验日期。
{{
{field_lines}
}}

以下为全部已获取材料，附件内容与网页正文同等重要：
{material}
"""
