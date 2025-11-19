"""
Database Schemas for SnusQuit B2C App

Each Pydantic model represents a collection in MongoDB. The collection name
is the lowercase of the class name (e.g., User -> "user").
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
import datetime as dt

class User(BaseModel):
    name: str = Field(..., description="User's display name")
    email: Optional[str] = Field(None, description="Email (optional)")
    country: Optional[str] = Field(None, description="Country code")

class Plan(BaseModel):
    user_id: str = Field(..., description="Reference to user _id as string")
    goal_type: Literal["quit", "reduce"] = Field("quit", description="Quit fully or reduce usage")
    start_date: dt.date = Field(..., description="Plan start date")
    target_date: Optional[dt.date] = Field(None, description="Target quit date (optional)")
    baseline_portions_per_day: Optional[float] = Field(None, ge=0, description="Typical daily portions before plan")
    target_portions_per_day: Optional[float] = Field(None, ge=0, description="Target daily portions if reducing")

class Checkin(BaseModel):
    user_id: str = Field(..., description="Reference to user _id as string")
    date: dt.date = Field(..., description="The day this check-in refers to")
    nicotine_free: bool = Field(..., description="Was the day nicotine-free?")
    portions_used: Optional[float] = Field(None, ge=0, description="Estimated portions used today")
    craving_level: Optional[int] = Field(None, ge=1, le=10, description="Craving intensity 1-10")
    note: Optional[str] = Field(None, description="Optional note")

class Tip(BaseModel):
    title: str
    body: str
