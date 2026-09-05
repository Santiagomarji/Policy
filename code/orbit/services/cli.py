"""
Orbit — command-line interface.

Drives the whole loop from the terminal against a local JSON store, so the
club can be operated independently with no server, database, or cloud.

Run from the code/ directory:

    python -m orbit.cli --help
    python -m orbit.cli club-create --name "My Club" --city "Austin"
    python -m orbit.cli member-add --club <ID> --name "Sam" --email sam@x.io --niche creatives --avail tue_pm
    python -m orbit.cli cycle-create --club <ID> --start 2026-01-06
    python -m orbit.cli cycle-run --cycle <ID> --seed 1
    python -m orbit.cli groups --cycle <ID>
    python -m orbit.cli health --cycle <ID>

State is stored in orbit.json by default (override with --db).
"""
from __future__ import annotations

import argparse
from datetime import date

from ..domain.models import GeoPoint
from .club_service import ClubService
from .health_service import HealthService
from .json_repository import JsonFileRepository
from .matching_service import MatchingService


def _repo(args: argparse.Namespace) -> JsonFileRepository:
    return JsonFileRepository(args.db)


def cmd_club_create(args: argparse.Namespace) -> None:
    repo = _repo(args)
    club = ClubService(repo).create_club(args.name, args.city, args.min_density)
    print(f"Created club {club.id}\n  name={club.name}  city={club.city}"
          f"  min_density={club.min_density}")


def cmd_club_list(args: argparse.Namespace) -> None:
    repo = _repo(args)
    if not repo.clubs:
        print("(no clubs yet)")
        return
    for c in repo.clubs.values():
        n = len(repo.members_for_club(c.id))
        print(f"{c.id}  {c.name} ({c.city})  members={n}")


def cmd_member_add(args: argparse.Namespace) -> None:
    repo = _repo(args)
    clubs = ClubService(repo)
    loc = None
    if args.lat is not None and args.lng is not None:
        loc = GeoPoint(args.lat, args.lng)
    m = clubs.register_member(
        club_id=args.club,
        name=args.name,
        email=args.email,
        availability=set(args.avail or []),
        location=loc,
        niche=args.niche,
    )
    density = clubs.check_density(args.club)
    print(f"Added member {m.id}  ({m.name})")
    print(f"Club density met: {density} "
          f"({len(repo.members_for_club(args.club))} members)")


def cmd_cycle_create(args: argparse.Namespace) -> None:
    repo = _repo(args)
    cycle = MatchingService(repo).create_cycle(
        args.club, date.fromisoformat(args.start), args.duration
    )
    print(f"Created cycle {cycle.id}\n  {cycle.start_date} -> {cycle.end_date}"
          f"  status={cycle.status.value}")


def cmd_cycle_run(args: argparse.Namespace) -> None:
    """Generate + commit a rotation proposal for a cycle."""
    repo = _repo(args)
    matching = MatchingService(repo)
    proposal = matching.generate_proposal(args.cycle, seed=args.seed)
    groups = matching.commit_proposal(args.cycle, proposal)
    print(f"Committed cycle {args.cycle}: {len(groups)} group(s), "
          f"{len(proposal.unplaced)} unplaced")
    for g in groups:
        owner = g.owner_id[:8] if g.owner_id else "—"
        print(f"  {g.name}: size={len(g.member_ids)}  owner={owner}")


def cmd_groups(args: argparse.Namespace) -> None:
    repo = _repo(args)
    groups = repo.groups_for_cycle(args.cycle)
    if not groups:
        print("(no groups for this cycle — run cycle-run first)")
        return
    for g in groups:
        print(f"{g.name} [{g.id[:8]}]  status={g.status.value}  "
              f"size={len(g.member_ids)}  owner={(g.owner_id or '—')[:8]}")
        for mid in g.member_ids:
            m = repo.members.get(mid)
            name = m.name if m else mid
            tag = "  (owner)" if mid == g.owner_id else ""
            print(f"    - {name}{tag}")


def cmd_health(args: argparse.Namespace) -> None:
    repo = _repo(args)
    reports = HealthService(repo).assess_all_groups(args.cycle)
    if not reports:
        print("(no groups to assess)")
        return
    for r in reports:
        flag = "AT-RISK" if r.at_risk else "ok"
        print(f"{r.group_name}: attendance={r.attendance_rate:.0%}  "
              f"owner={'yes' if r.has_owner else 'NO'}  [{flag}]")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orbit",
        description="Orbit rotating social club — terminal operator.",
    )
    p.add_argument("--db", default="orbit.json",
                   help="path to the local JSON store (default: orbit.json)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("club-create", help="create a club")
    sp.add_argument("--name", required=True)
    sp.add_argument("--city", required=True)
    sp.add_argument("--min-density", dest="min_density", type=int, default=30)
    sp.set_defaults(func=cmd_club_create)

    sp = sub.add_parser("club-list", help="list clubs")
    sp.set_defaults(func=cmd_club_list)

    sp = sub.add_parser("member-add", help="register a member")
    sp.add_argument("--club", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--email", required=True)
    sp.add_argument("--niche", default=None)
    sp.add_argument("--avail", nargs="*", default=[],
                    help="availability day tokens, e.g. tue_pm thu_pm")
    sp.add_argument("--lat", type=float, default=None)
    sp.add_argument("--lng", type=float, default=None)
    sp.set_defaults(func=cmd_member_add)

    sp = sub.add_parser("cycle-create", help="create a rotation cycle")
    sp.add_argument("--club", required=True)
    sp.add_argument("--start", required=True, help="YYYY-MM-DD")
    sp.add_argument("--duration", type=int, default=14)
    sp.set_defaults(func=cmd_cycle_create)

    sp = sub.add_parser("cycle-run", help="generate + commit groups for a cycle")
    sp.add_argument("--cycle", required=True)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_cycle_run)

    sp = sub.add_parser("groups", help="show groups for a cycle")
    sp.add_argument("--cycle", required=True)
    sp.set_defaults(func=cmd_groups)

    sp = sub.add_parser("health", help="assess group health for a cycle")
    sp.add_argument("--cycle", required=True)
    sp.set_defaults(func=cmd_health)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
