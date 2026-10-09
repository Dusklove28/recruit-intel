"""The exact 17 public fields of one recruitment announcement."""

from datetime import date
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecruitmentRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    sequence: int = Field(alias="序号", ge=1)
    unit_name: str | None = Field(alias="单位名称")
    unit_type: Literal["央企", "央企子公司", "地方国企", "事业单位"] | None = Field(alias="单位类型")
    parent_unit: str | None = Field(alias="所属集团/主管单位")
    batch: str | None = Field(alias="招聘批次")
    positions: str | None = Field(alias="招聘岗位", max_length=400)
    audience: str | None = Field(alias="招聘对象")
    education: str | None = Field(alias="学历要求")
    requirements: str | None = Field(alias="专业/硬性要求", max_length=240)
    location: str | None = Field(alias="工作地点", max_length=180)
    updated_date: date | None = Field(alias="更新时间")
    deadline: date | None = Field(alias="截止时间")
    status: Literal["招聘中", "即将截止", "已截止"] | None = Field(alias="招聘状态")
    official_url: str | None = Field(alias="官方公告")
    application_url: str | None = Field(alias="报名入口")
    verified_date: date | None = Field(alias="最后核验日期")
    notes: str | None = Field(alias="备注")

    @field_validator("updated_date", "deadline", "verified_date", mode="before")
    @classmethod
    def require_iso_date(cls, value):
        if value is None or isinstance(value, date):
            return value
        if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
            return value
        raise ValueError("日期必须是 YYYY-MM-DD 或 null")

    @field_validator("official_url", "application_url")
    @classmethod
    def require_web_url(cls, value):
        if value is None:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("链接必须是 HTTP/HTTPS URL")
        return value

    @field_validator("requirements")
    @classmethod
    def avoid_unverified_population_claims(cls, value):
        if value and re.search(r"多数岗位|大部分岗位|绝大多数岗位|所有岗位|全部岗位|均要求|普遍要求", value):
            raise ValueError("专业汇总不得使用未经逐岗核实的整体数量判断")
        return value


FIELD_NAMES = list(RecruitmentRecord.model_fields[field].alias for field in RecruitmentRecord.model_fields)
