"""
Orbit — Rotating Social Club
Core domain: enums.

Pure standard library. No third-party dependencies.
"""
from enum import Enum


class MemberStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    BANNED = "banned"


class MemberRole(str, Enum):
    MEMBER = "member"
    OWNER = "owner"


class GroupStatus(str, Enum):
    FORMING = "forming"
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    DISSOLVING = "dissolving"
    MERGED = "merged"
    ROTATING = "rotating"


class CycleStatus(str, Enum):
    PLANNED = "planned"
    PROPOSED = "proposed"
    COMMITTED = "committed"
    CLOSED = "closed"


class EventType(str, Enum):
    SMALL = "small"   # biweekly group event
    BIG = "big"       # monthly club gathering


class EventStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    FULL = "full"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RsvpStatus(str, Enum):
    GOING = "going"
    WAITLIST = "waitlist"
    DECLINED = "declined"
    NO_SHOW = "no_show"


class VolunteerType(str, Enum):
    BIG_EVENT_HOST = "big_event_host"
    WELCOMER = "welcomer"
    HEALTH_WATCHER = "health_watcher"
    ROTATION_STEWARD = "rotation_steward"


class SubscriptionTier(str, Enum):
    FREE = "free"
    PLUS = "plus"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class PaymentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    PENDING = "pending"


class NotificationChannel(str, Enum):
    PUSH = "push"
    EMAIL = "email"
    SMS = "sms"


class NotificationStatus(str, Enum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
