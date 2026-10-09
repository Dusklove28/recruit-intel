# RecruitIntel V1

输入一个公开招聘公告 URL，读取同一招聘专题中的相关页面和附件，输出一条 17 字段招聘记录，并保存到本地 SQLite 与 XLSX。多个岗位会汇总成一行。

## 安装

建议使用 Python 3.12。进入本目录后安装依赖：

```bash
python -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填写已测试成功的百炼配置：

```text
DASHSCOPE_API_KEY=你的密钥
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=你已测试的模型名
```

也可直接设置同名环境变量。`.env`、本地数据库、附件、缓存和导出的 Excel 均被 Git 忽略。不要把密钥写入代码或提交到仓库。

## 运行

```bash
python main.py "https://campus.51job.com/cofco/brochure.html"
```

程序会显示专题页面数、附件数、岗位详情数、抽取和校验结果。输出文件位于 `data/output/2027届央国企事业编招聘汇总.xlsx`；原始材料、17 字段及招聘内容字段的证据 URL 保存在 `data/recruitment.sqlite3`。再次输入同一个 URL 会更新该条记录。

运行测试：

```bash
python -m pytest -q
```

## V1 范围

- 只探索输入 URL 所在域名、同一专题目录中的招聘简章、岗位、详情、投递指引等相关页面；最多读取 15 个专题页面，不做全站遍历。
- 优先解析专题页面公开提供的结构化岗位数据。中粮案例使用专题页自身的岗位列表接口，并仅查询该列表返回的岗位 ID。该专题公开脚本中的客户端请求值只在运行时读取，不写入代码、日志或数据库。
- 支持下载并解析专题内明确链接的 PDF、XLS、XLSX、DOCX。扫描 PDF 会记为“需要OCR”，暂不做 OCR。
- 报名入口只采用明确的网申或报名链接；不会把普通岗位列表页当作报名入口。遇到登录页会停止，不处理登录、验证码或反爬机制。
- 组织信息仅按 `processing/organization_registry.py` 中已核实的官方单位全称精确匹配。当前最小名录收录中粮集团有限公司，依据国务院国资委央企名录与中央企业定义，填写“央企”和“国务院国资委”，并保存两列的证据 URL；其他单位无匹配时留空，不让模型猜测。后续扩充名录须逐条核对官方证据。
- “更新时间”是本地记录最近内容更新时间，首次收录填当天；仅重新核验、17 列中其他内容字段未变时保持原日期；内容字段变化时更新为当天。“最后核验日期”每次检查后更新。前者为系统维护日期，没有公告来源 URL。没有可靠证据的字段留空；一条公告始终只导出一行。
- 不包含全国自动巡检、腾讯文档同步、浏览器逐岗点击或大型爬虫系统。

## 文件位置

- `main.py`：单 URL 命令行入口。
- `collectors/`：专题页面、附件和公开岗位数据读取。
- `parsers/`：HTML 与附件文本解析。
- `extractor/`、`processing/`：17 字段抽取、校验和证据关联。
- `storage/`、`exporters/`：SQLite 保存和 XLSX 导出。
- `tests/`：离线单元测试。
