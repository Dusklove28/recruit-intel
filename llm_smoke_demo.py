import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)

response = client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    messages=[
        {
            "role": "user",
            "content": """
从下面招聘信息中提取单位、招聘对象和学历要求：

中国某集团启动2027届校园招聘，
面向2027届应届毕业生，
招聘岗位要求本科及以上学历。

仅返回简洁结果。
"""
        }
    ],
    temperature=0,
)

print(response.choices[0].message.content)