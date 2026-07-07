"""SQLAlchemy models for missions."""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Enum, Index, ForeignKey, JSON
from sqlalchemy.orm import relationship
import enum

from mission_authority.database import Base


class MissionStatus(str, enum.Enum):
    """Mission status enum."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class Mission(Base):
    """Mission record.

    A mission is a human-approved, time-bounded authorization for an agent
    to perform a specific task with defined scopes (permissions).
    """
    __tablename__ = "missions"

    # Identity
    mission_id = Column(String(64), primary_key=True)
    external_id = Column(String(128), nullable=True, index=True)

    # Description
    task = Column(Text, nullable=False)
    agent_id = Column(String(256), nullable=False, index=True)

    # Authorization
    scope = Column(JSON, nullable=False)  # List[str]
    sub_agents = Column(JSON, nullable=True)  # Optional[List[SubAgent]]

    # Lifecycle
    status = Column(
        Enum(MissionStatus),
        nullable=False,
        default=MissionStatus.PENDING,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_by = Column(String(256), nullable=False)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(256), nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Validation
    validation = Column(JSON, nullable=False)  # ValidationPolicy dict

    # Audit
    usage_count = Column(Integer, default=0)
    last_exchange_at = Column(DateTime, nullable=True)

    # Metadata
    labels = Column(JSON, nullable=True)
    annotations = Column(JSON, nullable=True)

    # Relationships
    expansions = relationship("ScopeExpansion", back_populates="mission", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Mission {self.mission_id} status={self.status}>"


class ScopeExpansion(Base):
    """Scope expansion request.

    When an agent needs additional scopes mid-execution, it requests
    an expansion with justification. User approves or denies.
    """
    __tablename__ = "scope_expansions"

    expansion_id = Column(String(64), primary_key=True)
    mission_id = Column(String(64), ForeignKey("missions.mission_id"), nullable=False, index=True)
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    requested_by = Column(String(256), nullable=False)  # Agent ID
    additional_scopes = Column(JSON, nullable=False)  # List[str]
    justification = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(256), nullable=True)

    # Relationship
    mission = relationship("Mission", back_populates="expansions")

    def __repr__(self):
        return f"<ScopeExpansion {self.expansion_id} status={self.status}>"


# Indexes for common queries
Index("idx_missions_agent_status", Mission.agent_id, Mission.status)
Index("idx_missions_status_created", Mission.status, Mission.created_at.desc())
