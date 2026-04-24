# app/schemas/experiment_schema.py
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime


class ExperimentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    traffic_split: Dict[str, int]  # {"group_a": 50, "group_b": 50}
    group_configs: Dict[str, Dict]  # 各组参数
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class ExperimentUpdate(BaseModel):
    is_active: Optional[bool] = None
    traffic_split: Optional[Dict[str, int]] = None
    group_configs: Optional[Dict[str, Dict]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class ExperimentResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    traffic_split: Dict[str, int]
    group_configs: Dict[str, Dict]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ExperimentLogResponse(BaseModel):
    id: int
    experiment_id: int
    user_id: int
    group_name: str
    query_text: str
    answer_text: str
    latency_ms: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True