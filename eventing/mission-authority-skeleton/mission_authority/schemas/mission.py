"""Pydantic schemas for mission API requests/responses."""

from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any


# Request schemas

class ValidationPolicy(BaseModel):
    """Base validation policy."""
    type: str = Field(..., description="Validation type: scheduled, on_demand, or custom")


class ScheduledValidation(ValidationPolicy):
    """Scheduled validation (e.g., daily at 9am)."""
    type: str = "scheduled"
    schedule: str = Field(..., description="Cron expression")
    timezone: str = Field(default="UTC", description="Timezone for schedule")
    window_minutes: int = Field(default=30, description="Time window tolerance")
    duration_days: int = Field(..., description="Mission duration in days")


class OnDemandValidation(ValidationPolicy):
    """On-demand validation with usage limits."""
    type: str = "on_demand"
    max_uses: Optional[int] = Field(None, description="Maximum number of uses")
    cooldown_minutes: Optional[int] = Field(None, description="Cooldown between uses")
    valid_until: datetime = Field(..., description="Mission expiration time")
    business_hours_only: bool = Field(default=False)


class CustomValidation(ValidationPolicy):
    """Custom validation via webhook."""
    type: str = "custom"
    validator_url: str = Field(..., description="Webhook URL for validation")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=5)


class SubAgent(BaseModel):
    """Sub-agent scope breakdown."""
    agent_id: str
    scopes: List[str]
    estimated_duration: Optional[str] = None


class MissionCreateRequest(BaseModel):
    """Request to create a mission."""
    task: str = Field(..., description="Natural language task description")
    agent_id: str = Field(..., description="Agent SPIFFE ID or name")
    scope: List[str] = Field(..., description="List of scopes (permissions)")
    validation: Dict[str, Any] = Field(..., description="Validation policy")
    sub_agents: Optional[List[SubAgent]] = None
    labels: Optional[Dict[str, str]] = None

    @field_validator("scope")
    @classmethod
    def validate_scope_not_empty(cls, v):
        if not v:
            raise ValueError("scope must contain at least one element")
        return v


class MissionApproveRequest(BaseModel):
    """Request to approve a mission.

    approved_by is derived from the authenticated user token when Keycloak is
    enabled. The field is accepted but ignored in that case.
    """
    approved_by: Optional[str] = Field(None, description="Ignored when Keycloak auth is enabled")
    notes: Optional[str] = None


class MissionCancelRequest(BaseModel):
    """Request to cancel a mission. canceled_by is derived from the authenticated user token."""
    reason: Optional[str] = None


class ScopeExpansionRequest(BaseModel):
    """Request to expand mission scopes."""
    requesting_agent: str = Field(..., description="Agent requesting expansion")
    additional_scopes: List[str] = Field(..., description="Additional scopes needed")
    justification: str = Field(..., description="Why these scopes are needed")

    @field_validator("justification")
    @classmethod
    def validate_justification_not_empty(cls, v):
        if not v or len(v.strip()) < 10:
            raise ValueError("justification must be at least 10 characters")
        return v


class ScopeExpansionApproveRequest(BaseModel):
    """Request to approve a scope expansion."""
    approved_by: str = Field(..., description="User approving the expansion")
    notes: Optional[str] = None


class ScopeExpansionDenyRequest(BaseModel):
    """Request to deny a scope expansion."""
    denied_by: str = Field(..., description="User denying the expansion")
    reason: Optional[str] = None


# Response schemas

class MissionResponse(BaseModel):
    """Mission response."""
    mission_id: str
    status: str
    task: str
    agent_id: str
    scope: List[str]
    created_at: datetime
    created_by: str
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    expires_at: datetime
    usage_count: int = 0
    last_exchange_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MissionCreateResponse(BaseModel):
    """Response after creating a mission."""
    mission_id: str
    status: str
    created_at: datetime
    expires_at: datetime
    approval_url: Optional[str] = None


class MissionApproveResponse(BaseModel):
    """Response after approving a mission."""
    mission_id: str
    status: str
    approved_at: datetime
    approved_by: str
    mission_token: str


class MissionListResponse(BaseModel):
    """List of missions."""
    missions: List[MissionResponse]
    total: int
    page: int
    page_size: int


class ScopeExpansionResponse(BaseModel):
    """Scope expansion response."""
    expansion_id: str
    mission_id: str
    status: str
    requested_at: datetime
    requested_by: str
    additional_scopes: List[str]
    justification: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
