"""
Orbit — REST API (pure standard library, zero dependencies).

Exposes the service layer over HTTP using only ``http.server`` from the
standard library, so it runs anywhere Python runs — no framework, no cloud,
no external services. State persists to a local JSON file
(:class:`JsonFileRepository`).

Run it:

    python -m orbit.api                 # serves on http://127.0.0.1:8080
    ORBIT_DB=orbit.json ORBIT_PORT=9000 python -m orbit.api

The routing logic lives in :class:`OrbitRouter`, which is independent of the
HTTP transport so it can be unit-tested directly (see tests/test_api.py).

Endpoints (all JSON):

    GET  /health
    GET  /clubs
    POST /clubs                       {name, city, min_density?}
    POST /clubs/{id}/members          {name, email, phone?, availability?, niche?, lat?, lng?}
    GET  /clubs/{id}/members
    GET  /clubs/{id}/density
    POST /clubs/{id}/cycles           {start_date: "YYYY-MM-DD", duration_days?}
    GET  /clubs/{id}/cycles
    POST /clubs/{id}/venues           {name, lat?, lng?, vetted?, partner?}
    GET  /clubs/{id}/venues
    POST /cycles/{id}/generate        {seed?}   -> proposal (not committed)
    POST /cycles/{id}/commit          {seed?}   -> generates + commits, returns groups
    GET  /cycles/{id}/groups
    GET  /cycles/{id}/health
    GET  /groups/{id}
    GET  /groups/{id}/events
    POST /groups/{id}/events          {starts_at?: ISO}     -> owner-run or fallback
    GET  /events/{id}                 -> event + rsvps + going_count
    POST /events/{id}/rsvp            {member_id}
    POST /events/{id}/attendance      {attended: [...], no_show: [...]}
    POST /events/{id}/rate            {member_id, score, comment?}
    GET  /events/{id}/ratings         -> rating summary (count, average, comments)
    POST /events/{id}/follow-up       -> send keep-in-touch prompts
    GET  /venues/{id}

    -- member-facing (the customer experience) --
    GET  /members/{id}                -> profile (reliability, streak, people met)
    GET  /members/{id}/group          -> current group + groupmates
    GET  /members/{id}/upcoming       -> next event (or null)
    GET  /members/{id}/connections    -> people met across cycles
    POST /members/{id}/rsvp           -> RSVP self to next event (409 if none) [self-auth]
    POST /members/{id}/block          {other_id}  -> block (symmetric) [self-auth]
    GET  /members/{id}/subscription   -> billing subscription
    POST /members/{id}/subscribe      -> upgrade to Plus [self-auth]
    POST /members/{id}/cancel         -> cancel at period end [self-auth]

Auth model:
  * ORBIT_TOKEN (operator) — if set, gates all non-member writes.
  * member_token — returned once at registration; member-scoped writes
    (/members/{id}/rsvp|block|subscribe|cancel) require the member's own
    token OR the operator token, so a member can only act as themselves.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from . import serialization as ser
from .big_event_service import BigEventService
from .billing_service import BillingService
from .club_service import ClubService
from .event_service import EventService
from .health_service import HealthService
from .matching_service import MatchingService
from .member_service import MemberService
from .notification_service import NotificationService
from .rating_service import RatingService
from .reputation_service import ReputationService
from .repository_factory import flush_repository, make_repository
from .volunteer_service import VolunteerService
from .welcomer_service import WelcomerService


class ApiError(Exception):
    """Raised to return a specific HTTP status with a message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _norm_availability(value: Any) -> set[str]:
    """Normalize availability into a set of tokens.

    Accepts a list/tuple/set of tokens, or a comma/space-separated string
    (as the web UI may send), or None.
    """
    if value is None or value == "":
        return set()
    if isinstance(value, str):
        return {t.strip() for t in value.replace(",", " ").split() if t.strip()}
    return {str(t).strip() for t in value if str(t).strip()}


class OrbitRouter:
    """Transport-independent request router.

    Call :meth:`handle` with a method, path and parsed body; it returns a
    ``(status, body_dict)`` tuple. This makes the whole API unit-testable
    without opening a socket.

    A single lock serializes ``handle`` calls so the (shared) repository and
    the Postgres identity map are never mutated by two threads at once, and so
    per-request ``flush`` is correct under ThreadingHTTPServer.
    """

    # Methods that mutate state (require auth when a token is configured).
    _WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, repo: Any, auth_token: Optional[str] = None) -> None:
        self.repo = repo
        self.auth_token = auth_token or None
        self._lock = threading.Lock()
        self._request_token: Optional[str] = None
        self.clubs = ClubService(repo)
        self.matching = MatchingService(repo)
        self.events = EventService(repo)
        self.reputation = ReputationService(repo)
        self.health = HealthService(repo)
        self.members = MemberService(repo)
        self.big_events = BigEventService(repo)
        self.billing = BillingService(repo)
        self.notifications = NotificationService(repo)
        self.volunteers = VolunteerService(repo)
        self.welcomer = WelcomerService(repo, notifications=self.notifications,
                                        volunteers=self.volunteers)
        self.ratings = RatingService(repo, notifications=self.notifications)

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #
    def handle(
        self,
        method: str,
        path: str,
        body: Optional[dict[str, Any]],
        token: Optional[str] = None,
    ) -> tuple[int, Any]:
        body = body or {}
        segments = [s for s in urlparse(path).path.strip("/").split("/") if s]
        with self._lock:
            self._request_token = token  # available to member-scoped checks
            try:
                # Auth: writes require the operator token when one is
                # configured — EXCEPT member-scoped routes (/members/...),
                # which enforce per-member identity via _require_self so a
                # member can act with their own token.
                is_member_scoped = bool(segments) and segments[0] == "members"
                if (
                    self.auth_token
                    and method in self._WRITE_METHODS
                    and not is_member_scoped
                    and token != self.auth_token
                ):
                    return 401, {"error": "unauthorized: missing or invalid token"}

                result = self._route(method, segments, body)

                # Persist in-place mutations (no-op for JSON/in-memory repos).
                if method in self._WRITE_METHODS:
                    flush_repository(self.repo)
                return result
            except ApiError as e:
                return e.status, {"error": e.message}
            except KeyError as e:
                return 404, {"error": f"not found: {e}"}
            except (ValueError, TypeError) as e:
                return 400, {"error": str(e)}
            finally:
                self._request_token = None

    def _route(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        # GET /health
        if method == "GET" and seg == ["health"]:
            return 200, {"status": "ok", "service": "orbit"}

        # /clubs ...
        if seg and seg[0] == "clubs":
            return self._route_clubs(method, seg, body)
        if seg and seg[0] == "cycles":
            return self._route_cycles(method, seg, body)
        if seg and seg[0] == "groups":
            return self._route_groups(method, seg, body)
        if seg and seg[0] == "events":
            return self._route_events(method, seg, body)
        if seg and seg[0] == "members":
            return self._route_members(method, seg, body)
        if seg and seg[0] == "venues":
            return self._route_venues(method, seg, body)
        if seg and seg[0] == "big-events":
            return self._route_big_events(method, seg, body)
        if seg and seg[0] == "notifications":
            return self._route_notifications(method, seg, body)

        raise ApiError(404, f"no route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /clubs
    # ------------------------------------------------------------------ #
    def _route_clubs(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        if method == "GET" and len(seg) == 1:
            return 200, [ser.club_to_dict(c) for c in self.repo.clubs.values()]

        if method == "POST" and len(seg) == 1:
            self._require(body, "name", "city")
            club = self.clubs.create_club(
                name=body["name"],
                city=body["city"],
                min_density=int(body.get("min_density", 30)),
            )
            return 201, ser.club_to_dict(club)

        if len(seg) >= 2:
            club_id = seg[1]
            if club_id not in self.repo.clubs:
                raise ApiError(404, f"club {club_id} not found")

            # /clubs/{id}/members
            if len(seg) == 3 and seg[2] == "members":
                if method == "POST":
                    self._require(body, "name", "email")
                    loc = None
                    if body.get("lat") is not None and body.get("lng") is not None:
                        from ..domain.models import GeoPoint

                        try:
                            loc = GeoPoint(float(body["lat"]), float(body["lng"]))
                        except (ValueError, TypeError):
                            raise ApiError(400, "lat/lng must be numbers")
                    member = self.clubs.register_member(
                        club_id=club_id,
                        name=body["name"],
                        email=body["email"],
                        phone=body.get("phone", ""),
                        availability=_norm_availability(body.get("availability")),
                        location=loc,
                        niche=body.get("niche"),
                    )
                    # Welcomer onboarding flow (auto welcomer + buddy + welcome).
                    onboarding = self.welcomer.onboard(member.id)
                    payload = ser.member_to_dict(member, include_token=True)
                    payload["onboarding"] = onboarding
                    return 201, payload
                if method == "GET":
                    return 200, [
                        ser.member_to_dict(m)
                        for m in self.repo.members_for_club(club_id)
                    ]

            # /clubs/{id}/density
            if len(seg) == 3 and seg[2] == "density" and method == "GET":
                return 200, {
                    "club_id": club_id,
                    "density_met": self.clubs.check_density(club_id),
                    "member_count": len(self.repo.members_for_club(club_id)),
                }

            # /clubs/{id}/cycles
            if len(seg) == 3 and seg[2] == "cycles":
                if method == "POST":
                    self._require(body, "start_date")
                    cycle = self.matching.create_cycle(
                        club_id=club_id,
                        start_date=date.fromisoformat(body["start_date"]),
                        duration_days=int(body.get("duration_days", 14)),
                    )
                    return 201, ser.cycle_to_dict(cycle)
                if method == "GET":
                    cycles = [
                        ser.cycle_to_dict(c)
                        for c in self.repo.cycles.values()
                        if c.club_id == club_id
                    ]
                    cycles.sort(key=lambda c: c["start_date"])
                    return 200, cycles

            # /clubs/{id}/venues
            if len(seg) == 3 and seg[2] == "venues":
                if method == "POST":
                    self._require(body, "name")
                    from ..domain.models import GeoPoint, Venue

                    loc = None
                    if body.get("lat") is not None and body.get("lng") is not None:
                        try:
                            loc = GeoPoint(float(body["lat"]), float(body["lng"]))
                        except (ValueError, TypeError):
                            raise ApiError(400, "lat/lng must be numbers")
                    venue = self.repo.add_venue(Venue(
                        club_id=club_id,
                        name=body["name"],
                        location=loc,
                        vetted=bool(body.get("vetted", False)),
                        partner=bool(body.get("partner", False)),
                    ))
                    return 201, ser.venue_to_dict(venue)
                if method == "GET":
                    return 200, [
                        ser.venue_to_dict(v)
                        for v in self.repo.venues.values()
                        if v.club_id == club_id
                    ]

            # /clubs/{id}/big-events  (monthly club-wide gathering)
            if len(seg) == 3 and seg[2] == "big-events":
                if method == "POST":
                    self._require(body, "starts_at")
                    ev = self.big_events.create_big_event(
                        club_id=club_id,
                        starts_at=datetime.fromisoformat(body["starts_at"]),
                        host_id=body.get("host_id"),
                        backup_host_id=body.get("backup_host_id"),
                        venue_id=body.get("venue_id"),
                        capacity=body.get("capacity"),
                    )
                    return 201, ser.event_to_dict(ev)
                if method == "GET":
                    from ..domain.enums import EventType
                    return 200, [
                        ser.event_to_dict(e)
                        for e in self.repo.events.values()
                        if e.club_id == club_id and e.type == EventType.BIG
                    ]

            # /clubs/{id}/volunteers
            if len(seg) == 3 and seg[2] == "volunteers":
                if method == "POST":
                    self._require(body, "member_id", "role_type", "term_start")
                    from ..domain.enums import VolunteerType
                    role = self.volunteers.assign_role(
                        club_id=club_id,
                        member_id=body["member_id"],
                        role_type=VolunteerType(body["role_type"]),
                        term_start=date.fromisoformat(body["term_start"]),
                        term_days=int(body.get("term_days", 90)),
                    )
                    return 201, ser.volunteer_role_to_dict(role)
                if method == "GET":
                    on = date.fromisoformat(body["on_date"]) if body.get("on_date") \
                        else date.today()
                    return 200, {
                        "coverage": self.volunteers.coverage(club_id, on),
                        "expiring_soon": [
                            ser.volunteer_role_to_dict(r)
                            for r in self.volunteers.expiring_soon(club_id, on)
                        ],
                    }

        raise ApiError(404, f"no clubs route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /cycles
    # ------------------------------------------------------------------ #
    def _route_cycles(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        if len(seg) < 2:
            raise ApiError(404, "cycle id required")
        cycle_id = seg[1]
        if cycle_id not in self.repo.cycles:
            raise ApiError(404, f"cycle {cycle_id} not found")

        # POST /cycles/{id}/generate  -> proposal only
        if len(seg) == 3 and seg[2] == "generate" and method == "POST":
            proposal = self.matching.generate_proposal(
                cycle_id, seed=int(body.get("seed", 0))
            )
            return 200, self._proposal_to_dict(proposal)

        # POST /cycles/{id}/commit  -> generate + commit
        if len(seg) == 3 and seg[2] == "commit" and method == "POST":
            proposal = self.matching.generate_proposal(
                cycle_id, seed=int(body.get("seed", 0))
            )
            groups = self.matching.commit_proposal(cycle_id, proposal)
            return 201, [ser.group_to_dict(g) for g in groups]

        # GET /cycles/{id}/groups
        if len(seg) == 3 and seg[2] == "groups" and method == "GET":
            return 200, [
                ser.group_to_dict(g)
                for g in self.repo.groups_for_cycle(cycle_id)
            ]

        # GET /cycles/{id}/health
        if len(seg) == 3 and seg[2] == "health" and method == "GET":
            reports = self.health.assess_all_groups(cycle_id)
            return 200, [self._health_to_dict(r) for r in reports]

        raise ApiError(404, f"no cycles route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /groups
    # ------------------------------------------------------------------ #
    def _route_groups(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        if len(seg) < 2:
            raise ApiError(404, "group id required")
        group_id = seg[1]
        if group_id not in self.repo.groups:
            raise ApiError(404, f"group {group_id} not found")

        # GET /groups/{id}
        if len(seg) == 2 and method == "GET":
            return 200, ser.group_to_dict(self.repo.groups[group_id])

        # GET /groups/{id}/events
        if len(seg) == 3 and seg[2] == "events" and method == "GET":
            return 200, [
                ser.event_to_dict(e)
                for e in sorted(
                    self.repo.events_for_group(group_id),
                    key=lambda e: e.starts_at,
                )
            ]

        # POST /groups/{id}/events
        if len(seg) == 3 and seg[2] == "events" and method == "POST":
            starts_at = (
                datetime.fromisoformat(body["starts_at"])
                if body.get("starts_at")
                else datetime.utcnow()
            )
            event = self.events.create_event_for_group(group_id, starts_at)
            return 201, ser.event_to_dict(event)

        raise ApiError(404, f"no groups route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /events
    # ------------------------------------------------------------------ #
    def _route_events(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        if len(seg) < 2:
            raise ApiError(404, "event id required")
        event_id = seg[1]
        if event_id not in self.repo.events:
            raise ApiError(404, f"event {event_id} not found")

        # GET /events/{id}  (includes RSVP summary for a smooth member view)
        if len(seg) == 2 and method == "GET":
            rsvps = self.repo.rsvps_for_event(event_id)
            payload = ser.event_to_dict(self.repo.events[event_id])
            payload["rsvps"] = [ser.rsvp_to_dict(r) for r in rsvps]
            payload["going_count"] = sum(
                1 for r in rsvps if r.status.value == "going"
            )
            return 200, payload

        # POST /events/{id}/rsvp
        if len(seg) == 3 and seg[2] == "rsvp" and method == "POST":
            self._require(body, "member_id")
            rsvp = self.events.rsvp(event_id, body["member_id"])
            return 201, ser.rsvp_to_dict(rsvp)

        # POST /events/{id}/attendance
        if len(seg) == 3 and seg[2] == "attendance" and method == "POST":
            attended = list(body.get("attended", []))
            no_show = list(body.get("no_show", []))
            self.events.record_attendance(event_id, attended, no_show)
            self.reputation.process_event_attendance(attended, no_show)
            return 200, {"event_id": event_id, "attended": len(attended),
                         "no_show": len(no_show)}

        # POST /events/{id}/rate {member_id, score, comment?}
        if len(seg) == 3 and seg[2] == "rate" and method == "POST":
            self._require(body, "member_id", "score")
            rating = self.ratings.rate_event(
                event_id, body["member_id"], int(body["score"]),
                comment=body.get("comment"),
            )
            return 201, ser.rating_to_dict(rating)

        # GET /events/{id}/ratings -> rating summary
        if len(seg) == 3 and seg[2] == "ratings" and method == "GET":
            return 200, self.ratings.event_rating_summary(event_id)

        # POST /events/{id}/follow-up -> send keep-in-touch prompts
        if len(seg) == 3 and seg[2] == "follow-up" and method == "POST":
            notes = self.ratings.send_follow_ups(event_id)
            return 200, {"follow_ups_sent": len(notes)}

        raise ApiError(404, f"no events route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /members  (the member-facing / customer experience)
    # ------------------------------------------------------------------ #
    def _route_members(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        if len(seg) < 2:
            raise ApiError(404, "member id required")
        member_id = seg[1]
        if member_id not in self.repo.members:
            raise ApiError(404, f"member {member_id} not found")

        # GET /members/{id}  -> profile summary
        if len(seg) == 2 and method == "GET":
            return 200, self.members.profile(member_id)

        if len(seg) == 3:
            what = seg[2]

            # GET /members/{id}/group -> current group + groupmates
            if what == "group" and method == "GET":
                g = self.members.current_group(member_id)
                if g is None:
                    return 200, {"group": None, "groupmates": []}
                mates = self.members.groupmates(member_id)
                return 200, {
                    "group": ser.group_to_dict(g),
                    "groupmates": [
                        {"id": m.id, "name": m.name} for m in mates
                    ],
                }

            # GET /members/{id}/upcoming -> next event (or null)
            if what == "upcoming" and method == "GET":
                e = self.members.upcoming_event(member_id)
                return 200, {"event": ser.event_to_dict(e) if e else None}

            # GET /members/{id}/connections -> people met across cycles
            if what == "connections" and method == "GET":
                met = self.members.people_ive_met(member_id)
                return 200, [{"id": m.id, "name": m.name} for m in met]

            # POST /members/{id}/rsvp -> RSVP self to your next event
            if what == "rsvp" and method == "POST":
                self._require_self(member_id)
                e = self.members.upcoming_event(member_id)
                if e is None:
                    raise ApiError(409, "you have no upcoming event to RSVP to")
                rsvp = self.events.rsvp(e.id, member_id)
                return 201, ser.rsvp_to_dict(rsvp)

            # POST /members/{id}/block -> block another member
            if what == "block" and method == "POST":
                self._require_self(member_id)
                self._require(body, "other_id")
                self.members.block_member(member_id, body["other_id"])
                return 200, {"blocked": body["other_id"]}

            # GET /members/{id}/subscription -> current subscription
            if what == "subscription" and method == "GET":
                sub = self.billing.get_or_create_subscription(member_id)
                return 200, ser.subscription_to_dict(sub)

            # POST /members/{id}/subscribe -> upgrade to Plus
            if what == "subscribe" and method == "POST":
                self._require_self(member_id)
                result = self.billing.subscribe_plus(member_id)
                return (201 if result["ok"] else 402), {
                    "subscription": ser.subscription_to_dict(result["subscription"]),
                    "payment": ser.payment_to_dict(result["payment"]),
                    "ok": result["ok"],
                }

            # POST /members/{id}/cancel -> cancel at period end (easy cancel)
            if what == "cancel" and method == "POST":
                self._require_self(member_id)
                sub = self.billing.cancel(member_id)
                return 200, ser.subscription_to_dict(sub)

            # GET /members/{id}/payments -> transparent charge history
            if what == "payments" and method == "GET":
                return 200, [
                    ser.payment_to_dict(p)
                    for p in self.repo.payments_for_member(member_id)
                ]

            # GET /members/{id}/notifications -> pending notifications
            if what == "notifications" and method == "GET":
                return 200, [
                    ser.notification_to_dict(n)
                    for n in self.notifications.pending_for_member(member_id)
                ]

        raise ApiError(404, f"no members route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /venues
    # ------------------------------------------------------------------ #
    def _route_venues(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        # GET /venues/{id}
        if len(seg) == 2 and method == "GET":
            venue_id = seg[1]
            if venue_id not in self.repo.venues:
                raise ApiError(404, f"venue {venue_id} not found")
            return 200, ser.venue_to_dict(self.repo.venues[venue_id])
        raise ApiError(404, f"no venues route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /big-events  (monthly club-wide gathering)
    # ------------------------------------------------------------------ #
    def _route_big_events(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        if len(seg) < 2:
            raise ApiError(404, "big-event id required")
        event_id = seg[1]
        if event_id not in self.repo.events:
            raise ApiError(404, f"big-event {event_id} not found")

        # GET /big-events/{id} -> event + attendance summary + host
        if len(seg) == 2 and method == "GET":
            payload = ser.event_to_dict(self.repo.events[event_id])
            payload["summary"] = self.big_events.attendance_summary(event_id)
            payload["effective_host"] = self.big_events.effective_host(event_id)
            return 200, payload

        if len(seg) == 3:
            what = seg[2]
            # POST /big-events/{id}/rsvp {member_id} -> GOING or WAITLIST
            if what == "rsvp" and method == "POST":
                self._require(body, "member_id")
                rsvp = self.big_events.rsvp(event_id, body["member_id"])
                return 201, ser.rsvp_to_dict(rsvp)
            # POST /big-events/{id}/cancel {member_id} -> free seat + promote
            if what == "cancel" and method == "POST":
                self._require(body, "member_id")
                self.big_events.cancel_rsvp(event_id, body["member_id"])
                return 200, self.big_events.attendance_summary(event_id)

        raise ApiError(404, f"no big-events route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # /notifications
    # ------------------------------------------------------------------ #
    def _route_notifications(
        self, method: str, seg: list[str], body: dict[str, Any]
    ) -> tuple[int, Any]:
        # POST /notifications/dispatch -> deliver due notifications (outbox)
        if len(seg) == 2 and seg[1] == "dispatch" and method == "POST":
            result = self.notifications.dispatch_due()
            return 200, result
        raise ApiError(404, f"no notifications route for {method} /{'/'.join(seg)}")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require(body: dict[str, Any], *keys: str) -> None:
        missing = [k for k in keys if k not in body or body[k] in (None, "")]
        if missing:
            raise ApiError(400, f"missing required field(s): {', '.join(missing)}")

    def _require_self(self, member_id: str) -> None:
        """Enforce that the caller is acting as themselves.

        A member-scoped write is allowed if EITHER:
          * the operator token is configured and was supplied
            (``self._request_token == self.auth_token``), OR
          * the caller supplied the member's own ``member_token``.

        If no operator token is configured and the caller supplied no token,
        the action is allowed (open mode) — the per-member gate only bites once
        members actually have tokens circulating. When a token IS supplied, it
        must match this member (prevents acting as someone else).
        """
        member = self.repo.members.get(member_id)
        if member is None:
            raise ApiError(404, f"member {member_id} not found")
        tok = self._request_token
        # Operator override.
        if self.auth_token and tok == self.auth_token:
            return
        # Member acting as themselves.
        if tok is not None and tok == getattr(member, "member_token", None):
            return
        # No token supplied and no operator token required -> open mode allow.
        if tok is None and not self.auth_token:
            return
        raise ApiError(403, "forbidden: you can only act as yourself")

    @staticmethod
    def _proposal_to_dict(proposal: Any) -> dict[str, Any]:
        return {
            "groups": [
                {"member_ids": g.member_ids, "owner_id": g.owner_id}
                for g in proposal.groups
            ],
            "unplaced": proposal.unplaced,
        }

    @staticmethod
    def _health_to_dict(r: Any) -> dict[str, Any]:
        return {
            "group_id": r.group_id,
            "group_name": r.group_name,
            "attendance_rate": r.attendance_rate,
            "has_owner": r.has_owner,
            "status": r.status.value,
            "at_risk": r.at_risk,
        }


# --------------------------------------------------------------------------- #
# HTTP transport
# --------------------------------------------------------------------------- #
def make_handler(
    router: OrbitRouter, ui_html: Optional[str] = None
) -> Callable[..., BaseHTTPRequestHandler]:
    """Build a request-handler class bound to a router instance.

    If ``ui_html`` is provided, ``GET /`` serves it (the single-file web UI).
    """

    class OrbitHandler(BaseHTTPRequestHandler):
        server_version = "OrbitHTTP/0.1"

        # Silence default noisy logging; keep a concise, safe line.
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            try:
                detail = fmt % args if args else fmt
            except Exception:
                detail = fmt
            print(f"[orbit] {self.command} {self.path} {detail}")

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Orbit-Token"
            )

        def _send(self, status: int, payload: Any) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, html: str) -> None:
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _read_body(self) -> Optional[dict[str, Any]]:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                raise ApiError(400, "invalid JSON body")

        def _token(self) -> Optional[str]:
            # Accept either X-Orbit-Token: <t> or Authorization: Bearer <t>.
            t = self.headers.get("X-Orbit-Token")
            if t:
                return t
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            return None

        def _dispatch(self, method: str) -> None:
            # Serve the UI at GET / (and /index.html) when available.
            if method == "GET" and ui_html is not None:
                p = urlparse(self.path).path
                if p in ("/", "/index.html", "/ui"):
                    self._send_html(ui_html)
                    return
            try:
                body = self._read_body()
                status, payload = router.handle(
                    method, self.path, body, token=self._token()
                )
            except ApiError as e:
                status, payload = e.status, {"error": e.message}
            self._send(status, payload)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return OrbitHandler


def _load_ui() -> Optional[str]:
    """Load the single-file web UI shipped in the package, if present."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # orbit/
    candidate = os.path.join(here, "web", "index.html")
    if os.path.exists(candidate):
        with open(candidate, "r", encoding="utf-8") as fh:
            return fh.read()
    return None


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    repo: Any = None,
    auth_token: Optional[str] = None,
) -> None:
    """Start the Orbit HTTP server (blocking).

    The repository is chosen by :func:`make_repository` (JSON file by default,
    PostgreSQL when ``DATABASE_URL`` is set and psycopg is installed).
    """
    if repo is None:
        repo = make_repository()
    router = OrbitRouter(repo, auth_token=auth_token)
    ui_html = _load_ui()
    handler = make_handler(router, ui_html=ui_html)
    httpd = ThreadingHTTPServer((host, port), handler)
    ui_note = "with web UI at /" if ui_html else "(no UI file found)"
    print(f"Orbit API listening on http://{host}:{port}  {ui_note}")
    if auth_token:
        print("Auth: writes require X-Orbit-Token header.")
    print("Try:  curl http://%s:%d/health" % (host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Orbit API.")
        httpd.server_close()


def main() -> None:
    host = os.environ.get("ORBIT_HOST", "127.0.0.1")
    port = int(os.environ.get("ORBIT_PORT", "8080"))
    auth_token = os.environ.get("ORBIT_TOKEN") or None
    repo = make_repository()
    serve(host=host, port=port, repo=repo, auth_token=auth_token)


if __name__ == "__main__":
    main()
