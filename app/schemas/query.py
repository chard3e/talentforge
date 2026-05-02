from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class Seniority(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"

class Degree(str, Enum):
    BSC = "bsc"
    MSC = "msc"
    PHD = "phd"

class LanguageReq(BaseModel):
    code: str
    min_level: str = "B1"

class QuerySpec(BaseModel):
    title: Optional[str] = None
    seniority: Optional[Seniority] = None
    must_have_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    min_experience_years: Optional[int] = None
    preferred_industries: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    languages: List[LanguageReq] = Field(default_factory=list)
    education_level: Optional[Degree] = None
    must_have_certifications: List[str] = Field(default_factory=list)
    free_text: Optional[str] = None