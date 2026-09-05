"""
Orbit — (de)serialization helpers.

Converts domain dataclasses <-> plain JSON-safe dicts. Pure standard library.
Used by the JSON file repository and the REST API so both speak the same
wire format. Sets are encoded as sorted lists; enums as their ``.value``;
datetimes as ISO-8601 strings.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..domain.enums import (
    CycleStatus,
    EventStatus,
    EventType,
    GroupStatus,
    MemberRole,
    MemberStatus,
    RsvpStatus,
)
from ..domain.models import (
    Club,
    Cycle,
    Event,
    GeoPoint,
    Group,
    Member,
    Preference,
    Rsvp,
    Venue,
)


# --------------------------------------------------------------------------- #
# Serialize (domain -> dict)
# --------------------------------------------------------------------------- #
def geo_to_dict(g: GeoPoint | None) -> dict[str, float] | None:
    return None if g is None else {"lat": g.lat, "lng": g.lng}


def preference_to_dict(p: Preference) -> dict[str, Any]:
    return {
        "interests": list(p.interests),
        "availability": sorted(p.availability),
        "location": geo_to_dict(p.location),
        "niche": p.niche,
        "personality": sorted(p.personality),
    }


def member_to_dict(m: Member, include_token: bool = False) -> dict[str, Any]:
    """Serialize a member.

    ``include_token`` controls whether the per-member secret is included:
    True for storage (persistence) and the one-time registration response;
    False (default) for list/other API responses so tokens aren't broadcast.
    """
    d = {
        "id": m.id,
        "club_id": m.club_id,
        "name": m.name,
        "email": m.email,
        "phone": m.phone,
        "verified": m.verified,
        "reliability_score": m.reliability_score,
        "current_streak": m.current_streak,
        "status": m.status.value,
        "preference": preference_to_dict(m.preference),
        "created_at": m.created_at.isoformat(),
    }
    if include_token:
        d["member_token"] = m.member_token
    return d


def club_to_dict(c: Club) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "city": c.city,
        "cadence": c.cadence,
        "min_density": c.min_density,
    }


def cycle_to_dict(c: Cycle) -> dict[str, Any]:
    return {
        "id": c.id,
        "club_id": c.club_id,
        "start_date": c.start_date.isoformat(),
        "end_date": c.end_date.isoformat(),
        "status": c.status.value,
    }


def group_to_dict(g: Group) -> dict[str, Any]:
    return {
        "id": g.id,
        "club_id": g.club_id,
        "cycle_id": g.cycle_id,
        "name": g.name,
        "member_ids": list(g.member_ids),
        "owner_id": g.owner_id,
        "streak": g.streak,
        "status": g.status.value,
    }


def event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "id": e.id,
        "group_id": e.group_id,
        "venue_id": e.venue_id,
        "owner_id": e.owner_id,
        "backup_owner_id": e.backup_owner_id,
        "club_id": e.club_id,
        "capacity": e.capacity,
        "type": e.type.value,
        "starts_at": e.starts_at.isoformat(),
        "status": e.status.value,
        "is_fallback": e.is_fallback,
    }


def rsvp_to_dict(r: Rsvp) -> dict[str, Any]:
    return {
        "id": r.id,
        "event_id": r.event_id,
        "member_id": r.member_id,
        "status": r.status.value,
        "attended": r.attended,
        "deposit_cents": r.deposit_cents,
    }


def venue_to_dict(v: Venue) -> dict[str, Any]:
    return {
        "id": v.id,
        "club_id": v.club_id,
        "name": v.name,
        "location": geo_to_dict(v.location),
        "vetted": v.vetted,
        "partner": v.partner,
    }


# --------------------------------------------------------------------------- #
# Deserialize (dict -> domain)
# --------------------------------------------------------------------------- #
def geo_from_dict(d: dict[str, float] | None) -> GeoPoint | None:
    return None if d is None else GeoPoint(lat=d["lat"], lng=d["lng"])


def preference_from_dict(d: dict[str, Any]) -> Preference:
    return Preference(
        interests=list(d.get("interests", [])),
        availability=set(d.get("availability", [])),
        location=geo_from_dict(d.get("location")),
        niche=d.get("niche"),
        personality=set(d.get("personality", [])),
    )


def member_from_dict(d: dict[str, Any]) -> Member:
    kwargs = dict(
        name=d["name"],
        club_id=d["club_id"],
        id=d["id"],
        email=d.get("email", ""),
        phone=d.get("phone", ""),
        verified=d.get("verified", False),
        reliability_score=d.get("reliability_score", 100),
        current_streak=d.get("current_streak", 0),
        status=MemberStatus(d.get("status", "active")),
        preference=preference_from_dict(d.get("preference", {})),
        created_at=datetime.fromisoformat(d["created_at"])
        if d.get("created_at")
        else datetime.utcnow(),
    )
    # Preserve the per-member token across reloads when present.
    if d.get("member_token"):
        kwargs["member_token"] = d["member_token"]
    return Member(**kwargs)


def club_from_dict(d: dict[str, Any]) -> Club:
    return Club(
        name=d["name"],
        city=d["city"],
        id=d["id"],
        cadence=d.get("cadence", "biweekly+monthly"),
        min_density=d.get("min_density", 30),
    )


def cycle_from_dict(d: dict[str, Any]) -> Cycle:
    return Cycle(
        club_id=d["club_id"],
        start_date=date.fromisoformat(d["start_date"]),
        end_date=date.fromisoformat(d["end_date"]),
        id=d["id"],
        status=CycleStatus(d.get("status", "planned")),
    )


def group_from_dict(d: dict[str, Any]) -> Group:
    return Group(
        club_id=d["club_id"],
        cycle_id=d["cycle_id"],
        name=d["name"],
        id=d["id"],
        member_ids=list(d.get("member_ids", [])),
        owner_id=d.get("owner_id"),
        streak=d.get("streak", 0),
        status=GroupStatus(d.get("status", "forming")),
    )


def event_from_dict(d: dict[str, Any]) -> Event:
    return Event(
        group_id=d["group_id"],
        starts_at=datetime.fromisoformat(d["starts_at"]),
        type=EventType(d.get("type", "small")),
        id=d["id"],
        venue_id=d.get("venue_id"),
        owner_id=d.get("owner_id"),
        backup_owner_id=d.get("backup_owner_id"),
        club_id=d.get("club_id"),
        capacity=d.get("capacity"),
        status=EventStatus(d.get("status", "draft")),
        is_fallback=d.get("is_fallback", False),
    )


def rsvp_from_dict(d: dict[str, Any]) -> Rsvp:
    return Rsvp(
        event_id=d["event_id"],
        member_id=d["member_id"],
        status=RsvpStatus(d.get("status", "going")),
        attended=d.get("attended", False),
        deposit_cents=d.get("deposit_cents", 0),
        id=d["id"],
    )


def venue_from_dict(d: dict[str, Any]) -> Venue:
    return Venue(
        club_id=d["club_id"],
        name=d["name"],
        id=d["id"],
        location=geo_from_dict(d.get("location")),
        vetted=d.get("vetted", False),
        partner=d.get("partner", False),
    )


# --------------------------------------------------------------------------- #
# V1 feature models: subscription, payment, notification, volunteer role
# --------------------------------------------------------------------------- #
def subscription_to_dict(s: Any) -> dict[str, Any]:
    return {
        "id": s.id,
        "member_id": s.member_id,
        "tier": s.tier.value,
        "status": s.status.value,
        "price_cents": s.price_cents,
        "renews_at": s.renews_at.isoformat() if s.renews_at else None,
        "cancel_at_period_end": s.cancel_at_period_end,
        "retry_count": s.retry_count,
    }


def payment_to_dict(p: Any) -> dict[str, Any]:
    return {
        "id": p.id,
        "member_id": p.member_id,
        "amount_cents": p.amount_cents,
        "description": p.description,
        "status": p.status.value,
        "subscription_id": p.subscription_id,
        "event_id": p.event_id,
        "refunded_cents": p.refunded_cents,
    }


def notification_to_dict(n: Any) -> dict[str, Any]:
    return {
        "id": n.id,
        "member_id": n.member_id,
        "kind": n.kind,
        "body": n.body,
        "send_at": n.send_at.isoformat() if n.send_at else None,
        "channel": n.channel.value,
        "status": n.status.value,
        "event_id": n.event_id,
        "sent_at": n.sent_at.isoformat() if n.sent_at else None,
    }


def volunteer_role_to_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "member_id": r.member_id,
        "club_id": r.club_id,
        "type": r.type.value,
        "term_start": r.term_start.isoformat(),
        "term_end": r.term_end.isoformat(),
    }


def subscription_from_dict(d: dict[str, Any]) -> Any:
    from ..domain.enums import SubscriptionStatus, SubscriptionTier
    from ..domain.models import Subscription
    return Subscription(
        member_id=d["member_id"],
        tier=SubscriptionTier(d.get("tier", "free")),
        status=SubscriptionStatus(d.get("status", "active")),
        id=d["id"],
        price_cents=d.get("price_cents", 0),
        renews_at=datetime.fromisoformat(d["renews_at"]) if d.get("renews_at") else None,
        cancel_at_period_end=d.get("cancel_at_period_end", False),
        retry_count=d.get("retry_count", 0),
    )


def payment_from_dict(d: dict[str, Any]) -> Any:
    from ..domain.enums import PaymentStatus
    from ..domain.models import Payment
    return Payment(
        member_id=d["member_id"],
        amount_cents=d["amount_cents"],
        description=d.get("description", ""),
        status=PaymentStatus(d.get("status", "pending")),
        id=d["id"],
        subscription_id=d.get("subscription_id"),
        event_id=d.get("event_id"),
        refunded_cents=d.get("refunded_cents", 0),
    )


def notification_from_dict(d: dict[str, Any]) -> Any:
    from ..domain.enums import NotificationChannel, NotificationStatus
    from ..domain.models import Notification
    return Notification(
        member_id=d["member_id"],
        kind=d["kind"],
        body=d.get("body", ""),
        send_at=datetime.fromisoformat(d["send_at"]),
        channel=NotificationChannel(d.get("channel", "push")),
        status=NotificationStatus(d.get("status", "scheduled")),
        id=d["id"],
        event_id=d.get("event_id"),
        sent_at=datetime.fromisoformat(d["sent_at"]) if d.get("sent_at") else None,
    )


def volunteer_role_from_dict(d: dict[str, Any]) -> Any:
    from ..domain.enums import VolunteerType
    from ..domain.models import VolunteerRole
    return VolunteerRole(
        member_id=d["member_id"],
        club_id=d["club_id"],
        type=VolunteerType(d["type"]),
        term_start=date.fromisoformat(d["term_start"]),
        term_end=date.fromisoformat(d["term_end"]),
        id=d["id"],
    )


def rating_to_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "event_id": r.event_id,
        "member_id": r.member_id,
        "score": r.score,
        "comment": r.comment,
    }


def rating_from_dict(d: dict[str, Any]) -> Any:
    from ..domain.models import Rating
    return Rating(
        event_id=d["event_id"],
        member_id=d["member_id"],
        score=d["score"],
        comment=d.get("comment"),
        id=d["id"],
    )
