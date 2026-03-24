"""
ESPN Fantasy Baseball - Daily Lineup Optimizer
==============================================
Manages pitcher slots for today and optionally additional days.

Priority rules (applied in order):
  1. RPs — always in an active slot (RP slot first, then generic P slot)
  2. SPs with a scheduled start — active slot (SP slot first, then P slot)
     If 9+ SPs are scheduled on one day, lower-priority ones are benched with a warning.
  3. SPs not starting that day — stay in their current active slot unless displaced
     by a starting SP; only benched if their slot is needed for a starting SP or RP
  Slot-type constraints: SP slots → SP-eligible only; RP slots → RP-eligible only;
  P slot → either. A higher-priority player is never displaced for a lower-priority one.

Usage:
    python espn_lineup.py [--days N] [--dry-run]

    --days N    Total days to process starting from today (default: 1 = today only)
    --dry-run   Print planned moves without submitting any changes
"""

import argparse
import datetime
import json
import os
import sys
import time
from urllib.parse import unquote

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed; rely on environment variables

# ── CONFIGURE THESE ──────────────────────────────────────────────────────────
LEAGUE_ID  = "176349"
SEASON     = 2026
MY_TEAM_ID = 5      # Your ESPN team ID (BONR = 5)

# Credentials are loaded from environment variables or a .env file.
# Copy .env.example to .env and fill in your values.
ESPN_S2 = os.environ.get("ESPN_S2", "")
SWID    = os.environ.get("SWID",    "")
ESPN_S2 = unquote(ESPN_S2)
SWID    = unquote(SWID)

if not ESPN_S2 or not SWID:
    print("ERROR: ESPN_S2 and SWID credentials not found.")
    print("  Set them in this file or via environment variables.")
    sys.exit(1)
# ─────────────────────────────────────────────────────────────────────────────

READ_BASE  = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{SEASON}"
WRITE_BASE = f"https://lm-api-writes.fantasy.espn.com/apis/v3/games/flb/seasons/{SEASON}"
COOKIES    = {"espn_s2": ESPN_S2, "SWID": SWID}

# ESPN build hash required by the write API — update if transactions start failing.
# Captured from browser network traffic on 2026-03-24.
ESPN_PLATFORM_VERSION = "c596c1a1951ccecaa3c8993e4ae216b6549a51ca"

SLOT_SP = 13
SLOT_RP = 14
SLOT_P  = 15
SLOT_BE = 16
SLOT_IL = 17

SLOT_NAMES = {
    SLOT_SP: "SP",
    SLOT_RP: "RP",
    SLOT_P:  "P",
    SLOT_BE: "BE",
    SLOT_IL: "IL",
}

# Warn and bench lower-priority SPs if this many or more are scheduled on one day
SP_START_THRESHOLD = 9

# ESPN proTeamId → MLB Stats API teamId
# Used to look up game schedules from statsapi.mlb.com
ESPN_TO_MLB_TEAM = {
    1:  110,  # Baltimore Orioles
    2:  111,  # Boston Red Sox
    3:  108,  # Los Angeles Angels
    4:  145,  # Chicago White Sox
    5:  114,  # Cleveland Guardians
    6:  116,  # Detroit Tigers
    7:  118,  # Kansas City Royals
    8:  158,  # Milwaukee Brewers
    9:  142,  # Minnesota Twins
    10: 147,  # New York Yankees
    11: 133,  # Athletics
    12: 136,  # Seattle Mariners
    13: 140,  # Texas Rangers
    14: 141,  # Toronto Blue Jays
    15: 144,  # Atlanta Braves
    16: 112,  # Chicago Cubs
    17: 113,  # Cincinnati Reds
    18: 117,  # Houston Astros
    19: 119,  # Los Angeles Dodgers
    20: 120,  # Washington Nationals
    21: 121,  # New York Mets
    22: 143,  # Philadelphia Phillies
    23: 134,  # Pittsburgh Pirates
    24: 138,  # St. Louis Cardinals
    25: 135,  # San Diego Padres
    26: 137,  # San Francisco Giants
    27: 115,  # Colorado Rockies
    28: 146,  # Miami Marlins
    29: 109,  # Arizona Diamondbacks
    30: 139,  # Tampa Bay Rays
}
MLB_TO_ESPN_TEAM = {v: k for k, v in ESPN_TO_MLB_TEAM.items()}


# ── Session ───────────────────────────────────────────────────────────────────

def get_session():
    s = requests.Session()
    s.headers.update({
        "Accept":             "application/json",
        "Content-Type":       "application/json",
        "User-Agent":         "Mozilla/5.0",
        "X-Fantasy-Source":   "kona",
        "X-Fantasy-Platform": "kona-PROD-1.4.4-branch-24-01-01",
    })
    # Bake cookies into the session so they are sent on all domains,
    # including the fantasy.espn.com write endpoint.
    s.cookies.set("espn_s2", ESPN_S2)
    s.cookies.set("SWID",    SWID)
    return s


# ── API helpers ───────────────────────────────────────────────────────────────

def get_league_info(session):
    """
    Return (scoring_period_id, latest_scoring_period, slot_counts) where:
      scoring_period_id    — current active scoring period
      latest_scoring_period — highest period the API will accept lineup submissions for
      slot_counts          — ESPN slot ID (int) → number of active slots of that type
    E.g. slot_counts {13: 7, 14: 0, 15: 0, 16: 5, 17: 2} for a league with 7 SP slots.
    """
    url  = f"{READ_BASE}/segments/0/leagues/{LEAGUE_ID}/"
    resp = session.get(url, params={"view": "mSettings"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    scoring_period  = data.get("scoringPeriodId", 0)
    latest_period   = data.get("status", {}).get("latestScoringPeriod", scoring_period)
    raw = (data.get("settings", {})
               .get("rosterSettings", {})
               .get("lineupSlotCounts", {}))
    slot_counts = {int(k): int(v) for k, v in raw.items()}
    return scoring_period, latest_period, slot_counts


def get_roster(session, scoring_period_id, debug=False):
    """Fetch my team's roster entries for the given scoring period."""
    url  = f"{READ_BASE}/segments/0/leagues/{LEAGUE_ID}/"
    resp = session.get(
        url,
        params={"view": "mRoster", "scoringPeriodId": scoring_period_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if debug:
        with open("debug_roster_raw.json", "w") as f:
            json.dump(data, f, indent=2)
        print("  DEBUG: Full roster response written to debug_roster_raw.json")

    for team in data.get("teams", []):
        if team["id"] == MY_TEAM_ID:
            entries = team.get("roster", {}).get("entries", [])
            if debug:
                _debug_print_entries(entries, scoring_period_id)
            return entries
    raise ValueError(f"Team {MY_TEAM_ID} not found in league response.")


def _debug_print_entries(entries, scoring_period_id, schedule=None, probable_starters=None):
    """Print key fields for every roster entry to diagnose parsing issues."""
    print(f"\n  DEBUG: {len(entries)} roster entries for scoring period {scoring_period_id}")
    for e in entries:
        name    = player_name(e)
        slot    = current_slot(e)
        slots   = eligible_slots(e)
        tid     = pro_team_id(e)
        sp_flag = "SP" if is_sp(e) else ("RP" if is_rp(e) else "--")
        game    = has_game(e, scoring_period_id, schedule) if schedule else "?"
        start   = has_start(e, scoring_period_id, probable_starters) if probable_starters else "?"
        print(
            f"    {name:30s}  lineupSlot={slot:2d}  role={sp_flag}  "
            f"proTeam={tid}  hasGame={game}  hasStart={start}  eligibleSlots={slots}"
        )


def submit_lineup(session, items, scoring_period_id, today_period, debug=False):
    """POST a lineup adjustment to ESPN.

    Current scoring periods use type=LINEUP_ADJUSTMENT.
    Future scoring periods use type=FUTURE_ROSTER with memberId + executionType,
    matching the format captured from ESPN's browser client.
    """
    url       = f"{WRITE_BASE}/segments/0/leagues/{LEAGUE_ID}/transactions/"
    is_future = scoring_period_id > today_period

    body = {
        "isLeagueManager": False,
        "scoringPeriodId": scoring_period_id,
        "teamId":          MY_TEAM_ID,
        "type":            "FUTURE_ROSTER" if is_future else "LINEUP_ADJUSTMENT",
        "items": [
            {
                "fromLineupSlotId": item["fromLineupSlotId"],
                "fromTeamId":       0,
                "isKeeper":         False,
                "overallPickNumber": 0,
                "playerId":         item["playerId"],
                "toLineupSlotId":   item["toLineupSlotId"],
                "type":             "LINEUP",
            }
            for item in items
        ],
    }
    if is_future:
        body["memberId"]      = SWID
        body["executionType"] = "EXECUTE"

    write_headers = {
        "Origin":           "https://fantasy.espn.com",
        "Referer":          "https://fantasy.espn.com/",
        "x-fantasy-source": "kona",
        "x-fantasy-platform": "espn-fantasy-web",
    }
    if debug:
        print(f"\n  DEBUG: POST {url}?platformVersion={ESPN_PLATFORM_VERSION}")
        print(f"  DEBUG: Request body: {json.dumps(body, indent=4)}")
    resp = session.post(
        url,
        params={"platformVersion": ESPN_PLATFORM_VERSION},
        json=body,
        headers=write_headers,
        cookies={"espn_s2": ESPN_S2, "SWID": SWID},
        timeout=30,
    )
    if debug:
        print(f"  DEBUG: Response status: {resp.status_code}")
        if resp.history:
            print(f"  DEBUG: Redirects ({len(resp.history)}):")
            for r in resp.history:
                print(f"    {r.status_code} {r.url} → {r.headers.get('Location', '?')}")
        try:
            print(f"  DEBUG: Response body: {json.dumps(resp.json(), indent=4)}")
        except Exception:
            print(f"  DEBUG: Response text: {resp.text[:500]}")
    resp.raise_for_status()
    if "text/html" in resp.headers.get("Content-Type", ""):
        raise ValueError(
            "Write endpoint returned HTML instead of JSON — credentials may be "
            "invalid or the request was not routed to the API."
        )
    return resp


def build_schedule_lookup(today_period, base_date, num_days, debug=False):
    """
    Fetch the MLB game schedule (with probable pitchers) from the public MLB Stats API
    for [base_date, base_date + num_days - 1] and return:

        schedule          — {scoring_period_id: set of ESPN proTeamIds playing that day}
                            Used to determine whether any team has a game (e.g. for RPs).
        probable_starters — {scoring_period_id: set of lowercased probable starter names}
                            Used to determine whether a specific SP is actually scheduled
                            to start that day.

    Uses statsapi.mlb.com — no authentication required.
    """
    end_date = base_date + datetime.timedelta(days=num_days - 1)
    resp = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId":   1,
            "gameType":  "R",            # regular season only — excludes spring training
            "startDate": base_date.strftime("%Y-%m-%d"),
            "endDate":   end_date.strftime("%Y-%m-%d"),
            "hydrate":   "probablePitcher",
        },
        timeout=30,
    )
    resp.raise_for_status()

    schedule          = {}   # scoring_period_id -> set of ESPN proTeamIds
    probable_starters = {}   # scoring_period_id -> set of lowercased pitcher names

    for game_date in resp.json().get("dates", []):
        d      = datetime.datetime.strptime(game_date["date"], "%Y-%m-%d").date()
        period = today_period + (d - base_date).days
        playing  = set()
        starters = set()

        for game in game_date.get("games", []):
            for side in ("home", "away"):
                team_info = game.get("teams", {}).get(side, {})
                mlb_id    = team_info.get("team", {}).get("id")
                espn_id   = MLB_TO_ESPN_TEAM.get(mlb_id)
                if espn_id:
                    playing.add(espn_id)
                pitcher = team_info.get("probablePitcher", {})
                name    = pitcher.get("fullName", "")
                if name:
                    starters.add(name.lower())

        schedule[period]          = playing
        probable_starters[period] = starters

    if debug:
        print(f"  DEBUG: MLB schedule loaded for {len(schedule)} days")
        for period in sorted(schedule):
            offset = period - today_period
            d      = base_date + datetime.timedelta(days=offset)
            print(f"    Period {period} ({d}): {len(schedule[period])} teams playing, "
                  f"probable starters: {sorted(probable_starters.get(period, set()))}")

    return schedule, probable_starters


# ── Roster helpers ────────────────────────────────────────────────────────────

def player_name(entry):
    return entry.get("playerPoolEntry", {}).get("player", {}).get("fullName", "Unknown")

def player_id(entry):
    return entry.get("playerPoolEntry", {}).get("player", {}).get("id")

def eligible_slots(entry):
    return entry.get("playerPoolEntry", {}).get("player", {}).get("eligibleSlots", [])

def current_slot(entry):
    return entry.get("lineupSlotId")

def is_sp(entry):
    """
    True starting pitcher.
    In ESPN fantasy baseball, SPs are eligible for both the SP slot (13) AND
    the RP slot (14).  Relief pitchers only get SP + P eligibility, not RP.
    """
    return SLOT_RP in eligible_slots(entry)

def is_rp(entry):
    """
    True relief pitcher.
    In ESPN fantasy baseball, RPs are eligible for the SP slot (13) and the
    generic P slot (15), but NOT the RP slot (14).
    """
    slots = eligible_slots(entry)
    return SLOT_SP in slots and SLOT_RP not in slots

def pro_team_id(entry):
    return entry.get("playerPoolEntry", {}).get("player", {}).get("proTeamId")

def has_game(entry, scoring_period_id, schedule=None):
    """
    True if this player's MLB team has a game in the given scoring period.
    schedule: {scoring_period_id (int): set of ESPN proTeamIds playing that day}
    Falls back to the (rarely populated) embedded player field if not supplied.
    """
    if schedule is not None:
        return pro_team_id(entry) in schedule.get(scoring_period_id, set())

    # Fallback: embedded player field (not returned by mRoster view)
    player = entry.get("playerPoolEntry", {}).get("player", {})
    games  = player.get("proGamesByScoringPeriod", {})
    return str(scoring_period_id) in games and len(games[str(scoring_period_id)]) > 0


def has_start(entry, scoring_period_id, probable_starters):
    """
    True if this player is the probable starting pitcher for a game in the given
    scoring period.  probable_starters: {scoring_period_id: set of lowercased names}.
    Falls back to False (never a false positive) if probable_starters is None/empty.
    """
    if not probable_starters:
        return False
    name = player_name(entry).lower()
    return name in probable_starters.get(scoring_period_id, set())


# ── Optimizer ─────────────────────────────────────────────────────────────────

def optimize_pitchers(entries, scoring_period_id, schedule=None, probable_starters=None,
                      slot_counts=None):
    """
    Compute the minimal set of lineup moves to satisfy all priority rules.

    slot_counts: dict mapping ESPN slot ID → total slots of that type in the league
                 (from mSettings).  If None, falls back to counting current occupancy.

    Returns:
        moves        — list of move dicts {playerId, playerName,
                       fromLineupSlotId, toLineupSlotId}
        skipped_sps  — SPs benched because the SP_START_THRESHOLD was reached
        no_slot      — active pitchers who couldn't be placed (all slots full);
                       these are benched and logged as warnings
    """
    # IL players are never touched
    non_il = [e for e in entries if current_slot(e) != SLOT_IL]

    rps          = [e for e in non_il if is_rp(e)]
    sps_starting = [e for e in non_il if is_sp(e) and has_start(e, scoring_period_id, probable_starters)]
    sps_resting  = [e for e in non_il if is_sp(e) and not has_start(e, scoring_period_id, probable_starters)]

    # Slot capacity: use league config when available; fall back to current occupancy
    if slot_counts:
        num_sp_slots = slot_counts.get(SLOT_SP, 0)
        num_rp_slots = slot_counts.get(SLOT_RP, 0)
        num_p_slots  = slot_counts.get(SLOT_P,  0)
    else:
        num_sp_slots = sum(1 for e in entries if current_slot(e) == SLOT_SP)
        num_rp_slots = sum(1 for e in entries if current_slot(e) == SLOT_RP)
        num_p_slots  = sum(1 for e in entries if current_slot(e) == SLOT_P)

    # Apply SP threshold — bench the tail end if too many SPs are starting
    skipped_sps = []
    if len(sps_starting) >= SP_START_THRESHOLD:
        skipped_sps  = sps_starting[SP_START_THRESHOLD:]
        sps_starting = sps_starting[:SP_START_THRESHOLD]

    desired = {}  # player_id -> target slot

    # Mutable slot capacities — consumed as players are assigned
    cap = {SLOT_RP: num_rp_slots, SLOT_SP: num_sp_slots, SLOT_P: num_p_slots}

    def assign_active(p, preferred_order):
        """
        Try to place player p in the first slot type from preferred_order that
        (a) has remaining capacity and (b) the player is eligible for.
        Returns the assigned slot, or None if no slot is available.
        """
        slots = eligible_slots(p)
        for slot in preferred_order:
            if cap[slot] > 0 and slot in slots:
                cap[slot] -= 1
                desired[player_id(p)] = slot
                return slot
        return None

    no_slot = []

    # ── Priority 1: RPs — prefer RP slot, then P, then SP ────────────────────
    # In leagues with no dedicated RP slot, spill directly into SP slots.
    for p in rps:
        if assign_active(p, [SLOT_RP, SLOT_P, SLOT_SP]) is None:
            no_slot.append(p)

    # ── Priority 2: Starting SPs — prefer SP slot, then P, then RP ───────────
    for p in sps_starting:
        if assign_active(p, [SLOT_SP, SLOT_P, SLOT_RP]) is None:
            no_slot.append(p)

    # ── Resting SPs: stay put unless their slot was consumed above ────────────
    # Only bench a resting SP if a higher-priority player displaced them.
    # Resting SPs already on the bench stay benched.
    for e in sps_resting:
        slot = current_slot(e)
        if slot in cap and cap[slot] > 0:
            cap[slot] -= 1
            desired[player_id(e)] = slot   # keep — slot not needed by anyone higher-priority
        else:
            desired[player_id(e)] = SLOT_BE   # displaced by an RP or starting SP

    # Skipped SPs (threshold exceeded) → bench
    for e in skipped_sps:
        desired[player_id(e)] = SLOT_BE

    # Players who couldn't fit in any active slot → bench
    for e in no_slot:
        desired[player_id(e)] = SLOT_BE

    all_pitchers = rps + sps_starting + sps_resting + skipped_sps

    # ── Generate move list ────────────────────────────────────────────────────
    moves = []
    for e in all_pitchers:
        pid  = player_id(e)
        want = desired.get(pid)
        have = current_slot(e)
        if want is not None and want != have:
            moves.append({
                "playerId":         pid,
                "playerName":       player_name(e),
                "fromLineupSlotId": have,
                "toLineupSlotId":   want,
            })

    return moves, skipped_sps, no_slot


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Optimize ESPN Fantasy Baseball pitcher lineup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python espn_lineup.py                  # today only, live\n"
            "  python espn_lineup.py --dry-run        # today only, preview\n"
            "  python espn_lineup.py --days 3         # today + 2 more days, live\n"
            "  python espn_lineup.py --days 3 --dry-run\n"
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        metavar="N",
        help="Total days to process starting from today (default: 1 = today only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned moves without submitting any changes to ESPN",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Dump raw roster JSON and print per-player field values to diagnose issues",
    )
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")

    if args.dry_run:
        print("DRY RUN — no changes will be submitted.\n")

    session = get_session()

    print("Fetching league info...")
    try:
        today_period, latest_period, slot_counts = get_league_info(session)
    except Exception as e:
        print(f"ERROR fetching league info: {e}")
        sys.exit(1)
    num_sp = slot_counts.get(SLOT_SP, 0)
    num_rp = slot_counts.get(SLOT_RP, 0)
    num_p  = slot_counts.get(SLOT_P,  0)
    print(f"  Today = scoring period {today_period}  (submittable up to period {latest_period})")
    if slot_counts:
        print(f"  Active pitcher slots: {num_sp} SP, {num_rp} RP, {num_p} P")
    else:
        print("  WARNING: Could not read slot config; falling back to current occupancy.")

    base_date = datetime.date.today()
    print("Fetching MLB game schedule and probable starters...")
    try:
        schedule, probable_starters = build_schedule_lookup(
            today_period, base_date, args.days, debug=args.debug
        )
        print(f"  Loaded schedule for {len(schedule)} days.\n")
    except Exception as e:
        print(f"  WARNING: Could not fetch MLB schedule ({e}). "
              f"Start detection will be disabled.\n")
        schedule          = None
        probable_starters = None

    for day_offset in range(args.days):
        scoring_period = today_period + day_offset
        date_label     = (base_date + datetime.timedelta(days=day_offset)).strftime("%Y-%m-%d")
        label = "Today" if day_offset == 0 else f"Day +{day_offset}"

        print(f"{'─' * 60}")
        print(f"  {label}  (scoring period {scoring_period}, {date_label})")
        print(f"{'─' * 60}")

        # Fetch roster
        try:
            entries = get_roster(session, scoring_period, debug=args.debug)
        except Exception as e:
            print(f"  ERROR fetching roster: {e}")
            print("  Skipping this day.\n")
            continue

        # Log pitcher inventory for this day
        non_il       = [e for e in entries if current_slot(e) != SLOT_IL]
        rps          = [e for e in non_il if is_rp(e)]
        sps_starting = [e for e in non_il if is_sp(e) and has_start(e, scoring_period, probable_starters)]
        sps_resting  = [e for e in non_il if is_sp(e) and not has_start(e, scoring_period, probable_starters)]

        print(f"  SPs with start ({len(sps_starting)}): "
              f"{[player_name(e) for e in sps_starting]}")
        print(f"  SPs resting   ({len(sps_resting)}): "
              f"{[player_name(e) for e in sps_resting]}")
        print(f"  RPs           ({len(rps)}): "
              f"{[player_name(e) for e in rps]}")

        # Compute moves
        try:
            moves, skipped_sps, no_slot = optimize_pitchers(
                entries, scoring_period, schedule, probable_starters, slot_counts
            )
        except Exception as e:
            print(f"  ERROR computing lineup: {e}")
            print()
            continue

        # Threshold warning
        if skipped_sps:
            total = len(sps_starting) + len(skipped_sps)
            print(
                f"\n  WARNING: {total} SPs scheduled today — "
                f"threshold is {SP_START_THRESHOLD}. "
                f"Benching lower-priority SPs:"
            )
            for e in skipped_sps:
                print(f"    • {player_name(e)}")

        # No-active-slot warning
        if no_slot:
            print("\n  WARNING: No active slot available for the following pitchers "
                  "(benching):")
            for e in no_slot:
                print(f"    • {player_name(e)}")

        # Move summary
        if not moves:
            print("\n  No lineup changes needed.")
        else:
            print(f"\n  Planned moves ({len(moves)}):")
            for m in moves:
                frm = SLOT_NAMES.get(m["fromLineupSlotId"], str(m["fromLineupSlotId"]))
                to  = SLOT_NAMES.get(m["toLineupSlotId"],   str(m["toLineupSlotId"]))
                print(f"    {m['playerName']:30s}  {frm:4s} → {to}")

            if args.dry_run:
                print("\n  (Dry run — not submitted)")
            else:
                try:
                    submit_lineup(session, moves, scoring_period, today_period, debug=args.debug)
                    print(f"\n  ✓ Lineup submitted for scoring period {scoring_period}.")
                except requests.HTTPError as e:
                    print(f"\n  ERROR submitting lineup: {e}")
                    if e.response is not None:
                        print(f"  Response: {e.response.text[:300]}")
                except Exception as e:
                    print(f"\n  ERROR submitting lineup: {e}")

        print()

        if day_offset < args.days - 1:
            time.sleep(0.5)


if __name__ == "__main__":
    main()
