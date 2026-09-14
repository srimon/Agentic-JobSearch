"""Shared validated intake and employer-specific resume routing."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.guardrails.content import safe_link

class Demographics(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    race_ethnicity:str=Field('',max_length=240)
    gender_sex:str=Field('',max_length=120)
    pronouns:str=Field('',max_length=120)
    gender_identity:str=Field('',max_length=120)
    sexual_orientation:str=Field('',max_length=120)
    veteran_status:Literal['not_provided','protected_veteran','not_protected_veteran','prefer_not_to_disclose']='not_provided'
    disability_status:Literal['not_provided','yes','no','prefer_not_to_disclose']='not_provided'
    use_for_applications:bool=False

class Intake(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    full_name:str=Field('',max_length=160)
    email:str=Field('',max_length=254)
    phone:str=Field('',max_length=40)
    location:str=Field('',max_length=160)
    linkedin_url:str=Field('',max_length=400)
    portfolio_url:str=Field('',max_length=400)
    authorized_us:Literal['unknown','yes','no']='unknown'
    sponsorship:Literal['unknown','yes','no']='unknown'
    relocate:Literal['unknown','yes','no']='unknown'
    workplace:list[Literal['Remote','Hybrid','On-site']]=Field(default_factory=list,max_length=3)
    desired_base_usd:int|None=Field(None,ge=0,le=10000000)
    notice_period:str=Field('',max_length=160)
    excluded_companies:str=Field('',max_length=1000)
    demographics:Demographics=Field(default_factory=Demographics)
    confirmed:bool=False

    @field_validator('email')
    @classmethod
    def valid_email(cls,value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value): raise ValueError('Invalid email')
        return value

    @field_validator('linkedin_url','portfolio_url')
    @classmethod
    def valid_url(cls,value):
        if value and not safe_link(value): raise ValueError('HTTPS URL required')
        return value

def capital_one(company):
    name=re.sub(r'[^a-z0-9]+',' ',company.lower()).strip()
    return name in {'capital one','capital one financial','capital one financial corporation','capital one financial corp','capital one services','capital one services llc','capital one national association'}

