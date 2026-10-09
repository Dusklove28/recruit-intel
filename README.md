# RecruitIntel V1

输入一个公开招聘公告 URL，读取同一招聘专题中的相关页面和附件，输出一条 17 字段招聘记录，并保存到本地 SQLite 与 XLSX。多个岗位会汇总成一行。当前面向客户的成品范围为 2027 届央企、央企子公司、地方国企校园招聘，不收录事业单位。

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

程序会显示专题页面数、附件数、岗位详情数、抽取和校验结果。成品文件位于 `data/output/2027届央国企校招汇总.xlsx`，只导出组织身份已核验、明确属于 2027 届校招且当前仍可投递的记录；原始材料、17 字段及招聘内容字段的证据 URL 保存在 `data/recruitment.sqlite3`。再次输入同一个 URL 会更新该条记录。

运行测试：

```bash
python -m pytest -q
```

## 首批来源试运行

```bash
python first_batch.py
```

该命令只读取已批准的国务院国资委、北京、上海、深圳四个招聘栏目；国务院国资委只看首页和最近六页归档，其余栏目只看首个公开页面。发现结果先保存在 SQLite 的 `candidates` 表，默认状态为“待核验”，不会直接进入正式 `recruitment` 表或客户 Excel。企业官网公告、报名入口、组织身份核验完成后，才可标记为“正式收录”。当前首批仍在试运行，尚未完成全国地方国企覆盖。

## 企业招聘源试运行

`discovery/seeds.json` 是独立维护的企业招聘入口清单，记录企业名称、类型、上级集团、招聘入口、官方域名、平台、来源、核验日期和启用状态。首批只含 20 家央企或其子公司；`source` 是逐家检查的官方页面，不直接复制第三方项目的数据文件。运行时的访问结果和最近实际检查日期分别写入 SQLite 的 `career_seed_checks` 与 `career_seeds`，不会把一个站点的失败当成整批失败。

```bash
python batch_discovery.py --limit 20
```

流程先识别招聘平台，再用通用官网页面或北森公开校招接口发现 2027 届活动。通用页面只查看 Seed 入口及其明确指向的最多 3 条活动；北森最多读取 3 页公开岗位列表。平台尚未接入、访问受限、缺少明确活动或组织身份证据的线索进入候选区，不会直接进入客户 Excel。北森公开岗位中的学历、地点等字段保存为带来源 URL 的 17 字段草稿；没有明确活动公告和投递入口时不正式收录。当前不使用浏览器自动化，也不处理登录、验证码、请求签名或 JS Challenge。

每次运行输出 `data/output/seed_batch_report.json` 和 `data/output/2027届央国企校招汇总.xlsx`。报告使用 `success`、`no_2027_recruitment`、`expired`、`pending_manual_review`、`access_control`、`unsupported_platform`、`parse_failed` 七种检查状态。`access_control` 保存失败入口、HTTP 状态和检查时间；例如国家电网 HTTP 412 只记录并跳过。报告中的学历、专业和链接字段比例以本批正式收录记录为分母；发现活动的解析率和正式收录率单独统计。原国资委栏目候选继续保存在 `candidates`，不会在这条流程中删除或逐条重试。

源清单与活动记录分开维护的思路参考 [xiaozhao-radar](https://github.com/jiabaobei/xiaozhao-radar)；按招聘平台复用适配器、按届别筛选的思路参考 [career-agent](https://github.com/mengxi111/career-agent)；公开 ATS 接口优先、记录源核验时间的思路参考 [openhire](https://github.com/gzchenhao/openhire)。本项目的 20 个入口来自逐家官方页面核验，未复制这些项目的代码或批量导入其 Seed 数据，也未接入腾讯文档同步。

## V1 范围

- 只探索输入 URL 所在域名、同一专题目录中的招聘简章、岗位、详情、投递指引等相关页面；最多读取 15 个专题页面，不做全站遍历。
- 优先解析专题页面公开提供的结构化岗位数据。中粮案例使用专题页自身的岗位列表接口，并仅查询该列表返回的岗位 ID。该专题公开脚本中的客户端请求值只在运行时读取，不写入代码、日志或数据库。
- 支持下载并解析专题内明确链接的 PDF、XLS、XLSX、DOCX。扫描 PDF 会记为“需要OCR”，暂不做 OCR。
- 报名入口只采用明确的网申或报名链接；不会把普通岗位列表页当作报名入口。遇到登录页会停止，不处理登录、验证码或反爬机制。
- 组织信息只按官方单位全称和组织关系证据核验。已有中粮集团的精确记录；遇到新的央企集团本级时按需读取国务院国资委央企名录，只保存实际匹配的单位及证据。央企子公司、地方国企缺少官方关系证据时进入“待核验”，不让模型猜测，也不写入正式招聘表。国务院国资委移动站的 HTTPS 证书在本次试运行中已过期，公开名录改用同域 HTTP 页面读取，不关闭证书校验。
- “更新时间”是本地记录最近内容更新时间，首次收录填当天；仅重新核验、17 列中其他内容字段未变时保持原日期；内容字段变化时更新为当天。“最后核验日期”每次检查后更新。前者为系统维护日期，没有公告来源 URL。没有可靠证据的字段留空；一条公告始终只导出一行。
- 不包含全国地方国企自动巡检、腾讯文档同步、浏览器逐岗点击或大型爬虫系统。
- 建行总部指定公告 `20260903163254718082` 已截止，仅用作公开正文接口与 PDF 附件验收。运行该 URL 时，默认把数据库和 Excel 写入 `data/cache/ccb_acceptance.*`，不写入当前可投递汇总表。只设置普通浏览器 User-Agent，不使用登录态、验证码或复杂浏览器模拟；仅请求该公告 ID 对应的公开接口和接口列出的 PDF。

## 文件位置

- `main.py`：单 URL 命令行入口。
- `collectors/`：专题页面、附件和公开岗位数据读取。
- `parsers/`：HTML 与附件文本解析。
- `extractor/`、`processing/`：17 字段抽取、校验和证据关联。
- `storage/`、`exporters/`：SQLite 保存和 XLSX 导出。
- `tests/`：离线单元测试。
