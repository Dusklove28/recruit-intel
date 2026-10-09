# 提示词总结：

你现在负责实现 RecruitIntel 的第一个可运行版本。

远程仓库：
https://github.com/Dusklove28/recruit-intel
这是一个空仓库，默认分支 main。

我已经在本机成功测试阿里云百炼 API：
Python -> OpenAI兼容接口 -> Qwen -> 正常返回结果。
API Key 已经配置在本机环境中。

重要要求：
1. 我要参与项目的重要功能决策，不允许你擅自替我做重要产品/架构决策。
2. 如果遇到下面情况，请立即暂停并询问我：
   - 有两种以上明显不同的实现方案；
   - 需要改变17列字段定义；
   - 需要选择新的数据源；
   - 需要决定腾讯文档同步方案；
   - 需要绕过登录、验证码、反爬；
   - 需要引入大型框架、数据库或明显增加复杂度；
   - 发现现有设计存在明显问题，需要重构。
3. 普通代码实现、bug修复、测试、格式整理不需要询问我。
4. 不要泄露、打印、提交任何 API Key。
5. `.env`、数据库、下载附件、输出Excel、缓存必须加入 `.gitignore`。
6. 不要过度工程化，不要使用微服务、Redis、Celery、Docker、Agent、RAG。

第一步：
先检查当前工作目录。

如果当前目录不是准备作为 recruit-intel 项目根目录的目录，
不要直接创建文件，先暂停并告诉我：

- 当前路径
- 你建议的项目路径
等我确认。

如果目录正确，再继续。

V1目标
====================

先只完成一个最小闭环：

输入一个真实招聘公告 URL

↓
下载并解析 HTML

↓
自动发现附件：
PDF / XLS / XLSX / DOCX

↓
下载附件

↓
解析附件文本和表格

↓
将网页正文 + 附件内容合并

↓
调用 Qwen

↓
严格输出17字段结构化 JSON

↓
Pydantic校验

↓
保存 SQLite

↓
导出 XLSX

暂时不要实现：
- 自动巡检全国招聘网站
- 腾讯文档同步
- OCR
- 多站点大规模爬虫

先把“一个URL -> 一条高质量、可靠招聘数据”做稳定。

17个正式字段
====================

1. 序号
2. 单位名称
3. 单位类型
4. 所属集团/主管单位
5. 招聘批次
6. 招聘岗位
7. 招聘对象
8. 学历要求
9. 专业/硬性要求
10. 工作地点
11. 更新时间
12. 截止时间
13. 招聘状态
14. 官方公告
15. 报名入口
16. 最后核验日期
17. 备注

单位类型优先规范为：
央企
央企子公司
地方国企
事业单位

无法可靠判断的数据：
返回 null / 空值，
禁止编造。

特别注意：
如果网页正文写“详见附件”，必须继续读取附件。

例如：
网页：
“学历要求详见附件1”

附件 XLSX：
“本科及以上”

最终必须提取：
学历要求 = 本科及以上

不要把“详见公告”“详见附件”作为最终结果，
除非确实无法解析附件。

一份公告包含多个岗位时不要拆成几百行，
要进行合理汇总，例如：

学历要求：
“本科及以上；部分岗位要求硕士研究生”

专业/硬性要求：
“计算机、电气、机械、自动化等相关专业，具体岗位要求见公告”

建议目录
====================

保持简单：

recruit-intel/
│
├── main.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── collectors/
│   ├── __init__.py
│   └── generic.py
│
├── parsers/
│   ├── __init__.py
│   ├── html_parser.py
│   ├── pdf_parser.py
│   ├── excel_parser.py
│   └── docx_parser.py
│
├── extractor/
│   ├── __init__.py
│   ├── schema.py
│   ├── prompts.py
│   └── llm_extractor.py
│
├── processing/
│   ├── __init__.py
│   ├── normalize.py
│   └── validate.py
│
├── storage/
│   ├── __init__.py
│   └── database.py
│
├── exporters/
│   ├── __init__.py
│   └── excel_exporter.py
│
├── data/
│   ├── attachments/
│   └── output/
│
└── tests/

如果你认为这个目录需要明显修改：
先暂停告诉我原因，不要自行重构。

LLM
====================

使用现有阿里云百炼 OpenAI Compatible API。

配置全部从环境变量读取，例如：

DASHSCOPE_API_KEY
LLM_BASE_URL
LLM_MODEL

不要在代码里写死 Key。

优先使用我当前已经测试成功的模型配置。

LLM输出必须尽可能使用 JSON，
并使用 Pydantic 做强校验。

temperature 尽量低，
因为这里是信息抽取，不是创作。

附件解析
====================

HTML：
requests/httpx + BeautifulSoup/lxml

PDF：
优先 PyMuPDF

XLS/XLSX：
pandas/openpyxl/xlrd

DOCX：
python-docx

暂时不要OCR。

如果遇到扫描PDF：
记录“需要OCR”，不要擅自引入OCR框架。

附件下载需要：
- 处理相对URL；
- 保留原始URL；
- 合理文件名；
- 超时和异常处理；
- 不因单个附件失败导致整个任务崩溃。

SQLite
====================

SQLite作为本地主数据源。

至少保存：
- 17字段
- source_url
- raw_text 或原始材料引用
- created_at
- updated_at

设计简单的唯一键避免重复。

如果唯一键设计存在明显取舍，
请先暂停询问我，不要自己定复杂规则。

Excel
====================

输出：
data/output/2027届央国企事业编招聘汇总.xlsx

字段顺序必须与17列一致。

第一版只要求：
- 表头
- 合理列宽
- 自动换行
- 冻结表头
- 自动筛选
- 官方公告/报名入口可点击

不要花大量时间美化。

CLI
====================

希望最终可以：

python main.py "https://example.com/job"

运行后显示类似：

开始解析……
发现附件 2 个
PDF解析成功
XLSX解析成功
LLM抽取成功
Pydantic校验通过
SQLite保存成功
Excel导出成功

并打印关键字段摘要。

测试要求
====================

先使用一个简单样例完成单元测试。

然后必须让我提供或确认一个“真实招聘公告 URL”。

不要自己随便选一个真实网站作为最终验收样例。

到需要真实URL时：
暂停并向我要URL。

我会深度参与这个测试过程。

Git与GitHub
====================

项目达到以下状态后再提交：

- 一个URL能够跑通完整流程；
- 基础测试通过；
- README有最基本的安装和使用方法；
- `.env`未被跟踪；
- data目录中的数据库、附件、输出文件未被提交；
- API Key没有出现在 git diff / git status 中。

提交前先执行安全检查：

git status
git diff --cached

确认没有：
.env
API Key
数据库
下载附件
用户数据

然后初始化/连接仓库：

git init
git branch -M main
git remote add origin https://github.com/Dusklove28/recruit-intel.git

如果 origin 已存在，则先检查：
git remote -v

不要重复添加。

然后：

git add .
git status

再次确认敏感信息没有被加入。

如果安全检查通过：

git commit -m "feat: bootstrap RecruitIntel MVP"
git push -u origin main

如果 push 前出现：
- 非预期已有提交；
- 远端不是空仓库；
- 分支冲突；
- 身份认证问题；
- 需要 force push；

必须暂停并询问我。
禁止 force push。

开发节奏
====================

不要一口气实现未来所有功能。

按以下阶段：

阶段A：
项目骨架 + 单元测试 + API封装

阶段B：
HTML与附件解析

阶段C：
17字段LLM抽取

阶段D：
SQLite + XLSX

阶段E：
真实招聘公告测试

阶段F：
README + Git提交 + push

每完成一个阶段：
简短告诉我：

- 完成了什么
- 测试结果
- 下一步做什么

如果不需要我决策，可以继续。

但到“真实招聘公告测试”时必须暂停，
让我提供URL。

第一条回复先做：
1. 检查当前目录；
2. 告诉我你准备在哪里建立项目；
3. 简要列出将安装的依赖；
4. 如果路径需要我确认，就暂停等待。

不要现在就开始写全国爬虫。

---



---
