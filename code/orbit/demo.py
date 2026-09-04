"""
Orbit — runnable demo.

Simulates a small club over several biweekly cycles to show the whole loop:
  * register members,
  * generate + commit a rotation proposal each cycle (keep-50 / swap-50),
  * run each group's event (owner-run or auto-run fallback),
  * record attendance, update reputation,
  * assess group health and surface at-risk groups.

Run from the code/ directory:

    python -m orbit.demo

No third-party dependencies. Deterministic (fixed seeds), so output is stable.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from orbit.domain.models import GeoPoint, Venue
from orbit.services.repository import InMemoryRepository
from orbit.services.club_service import ClubService
from orbit.services.matching_service import MatchingService
from orbit.services.event_service import EventService
from orbit.services.reputation_service import ReputationService
from orbit.services.health_service import HealthService

AREAS = ["north", "south"]
NICHES = ["creatives", "new-in-town", "runners"]
AVAIL = [{"tue_pm"}, {"thu_pm"}, {"tue_pm", "thu_pm"}]


def bar(width: int, ch: str = "=") -> str:
    return ch * width


def seed_club(clubs: ClubService, repo: InMemoryRepository, n: int) -> str:
    """Create a club with a partner venue and n members."""
    club = clubs.create_club("Orbit Demo Club", "Demo City", min_density=6)
    repo.add_venue(
        Venue(club_id=club.id, name="The Fallback Tavern", partner=True, vetted=True)
    )
    rng = random.Random(7)
    for i in range(n):
        # Give members a coarse area via a location that buckets to N/S.
        area = AREAS[i % len(AREAS)]
        lat = 1.0 if area == "north" else 9.0
        clubs.register_member(
            club_id=club.id,
            name=f"Member {i:02d}",
            email=f"m{i}@demo.orbit",
            availability=set(rng.choice(AVAIL)),
            location=GeoPoint(lat, 1.0),
            niche=rng.choice(NICHES),
        )
    return club.id


def run_cycle(
    club_id: str,
    cycle_index: int,
    start: date,
    repo: InMemoryRepository,
    matching: MatchingService,
    events: EventService,
    reputation: ReputationService,
    health: HealthService,
) -> None:
    print(f"\n{bar(64)}")
    print(f"CYCLE {cycle_index}  (starts {start.isoformat()})")
    print(bar(64))

    cycle = matching.create_cycle(club_id, start)
    proposal = matching.generate_proposal(cycle.id, seed=cycle_index)
    groups = matching.commit_proposal(cycle.id, proposal)

    print(f"Formed {len(groups)} group(s); unplaced: {len(proposal.unplaced)}")

    rng = random.Random(100 + cycle_index)
    for g in groups:
        owner_tag = "no owner" if not g.owner_id else f"owner={g.owner_id[:8]}"
        print(f"\n  {g.name}  (size {g.size}, {owner_tag})")

        # Simulate ownership: 1-in-4 cycles nobody hosts -> fallback event.
        nobody_hosts = rng.random() < 0.25
        if nobody_hosts:
            g.owner_id = None

        ev = events.create_event_for_group(
            g.id, datetime.combine(start + timedelta(days=4), datetime.min.time())
        )
        kind = "FALLBACK (club-run)" if ev.is_fallback else "owner-run"
        print(f"    event: {kind}")

        # Everyone RSVPs; most attend, a few no-show.
        attended, no_show = [], []
        for mid in g.member_ids:
            events.rsvp(ev.id, mid)
            if rng.random() < 0.8:
                attended.append(mid)
            else:
                no_show.append(mid)
        events.record_attendance(ev.id, attended, no_show)
        reputation.process_event_attendance(attended, no_show)
        rate = len(attended) / max(1, len(g.member_ids))
        print(f"    attendance: {len(attended)}/{g.size} ({rate:.0%})")

    # Health assessment for the cycle.
    at_risk = health.get_at_risk_groups(cycle.id)
    print(f"\n  Health: {len(at_risk)} at-risk group(s) flagged for Health Watcher.")
    for r in at_risk:
        reason = "no owner" if not r.has_owner else f"attendance {r.attendance_rate:.0%}"
        print(f"    - {r.group_name}: {reason}")


def main() -> None:
    repo = InMemoryRepository()
    clubs = ClubService(repo)
    matching = MatchingService(repo)
    events = EventService(repo)
    reputation = ReputationService(repo)
    health = HealthService(repo)

    print(bar(64, "#"))
    print("ORBIT — Rotating Social Club  |  multi-cycle simulation")
    print(bar(64, "#"))

    club_id = seed_club(clubs, repo, n=16)
    print(f"Seeded club with {len(repo.members_for_club(club_id))} members.")
    print(f"Density reached: {clubs.check_density(club_id)}")

    start = date(2026, 1, 6)  # a Tuesday
    for i in range(1, 5):  # 4 biweekly cycles
        run_cycle(club_id, i, start, repo, matching, events, reputation, health)
        start = start + timedelta(days=14)

    # Final reputation snapshot: who's most reliable after 4 cycles.
    print(f"\n{bar(64)}")
    print("FINAL REPUTATION (top 5 by reliability, then streak)")
    print(bar(64))
    members = repo.members_for_club(club_id)
    ranked = sorted(
        members, key=lambda m: (-m.reliability_score, -m.current_streak, m.name)
    )
    for m in ranked[:5]:
        print(
            f"  {m.name}: score={m.reliability_score:3d}  streak={m.current_streak}"
        )

    print("\nDemo complete. This exercised: registration, density gate, "
          "keep-50/swap-50 rotation, owner + fallback events, RSVP/attendance, "
          "reputation, and group-health flagging.")


if __name__ == "__main__":
    main()
