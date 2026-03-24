"""
ESPN Fantasy Baseball - Pull All Players & Stats to JSON
=========================================================
Usage (Option 1 - set cookies directly in this file):
    Uncomment ESPN_S2 and SWID under "Option 1" below and paste your values.

Usage (Option 2 - environment variables):
    set ESPN_S2=AEB...
    set SWID={XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
    python espn_players.py

    Environment variables take priority over values set in this file.

Output:
    players_YYYY-MM-DD.json  — all players with stats, ownership %, and roster status
"""

import json
import os
import sys
import time
from urllib.parse import unquote
import requests
from datetime import date

# ── CONFIGURE THESE ─────────────────────────────────────────────────────────
# Get your League ID from your leagues URL
LEAGUE_ID = ""
SEASON    = 2026

# Option 1: Set cookies directly in this file (uncomment and paste your values)
# Get the cookies by using Dev Tools in Chrome (F12) and Selecting Application -> Cookies
ESPN_S2 = ""
SWID    = ""

# Option 2: Read credentials from environment variables (takes priority over Option 1)
ESPN_S2 = os.environ.get("ESPN_S2", locals().get("ESPN_S2", ""))
SWID    = os.environ.get("SWID",    locals().get("SWID",    ""))

# Decode URL-encoding if the value was copied from a URL/network request (%2F → /, etc.)
ESPN_S2 = unquote(ESPN_S2)
SWID    = unquote(SWID)

if not ESPN_S2 or not SWID:
    print("ERROR: Credentials not found. Choose one of:")
    print("  Option 1 — uncomment ESPN_S2/SWID lines in this file and paste your values")
    print("  Option 2 — set env vars:  set ESPN_S2=AEB...  &&  set SWID={XXXX...}")
    sys.exit(1)
# ────────────────────────────────────────────────────────────────────────────

BASE_URL = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{SEASON}"

# Stat ID → human-readable name mapping for MLB
# Batting (IDs verified against known player data)
STAT_MAP = {
    "0":  "atBats",
    "1":  "hits",
    "2":  "avg",
    "3":  "doubles",
    "4":  "triples",
    "5":  "homeRuns",
    "6":  "rbi",            # stat_6 in raw
    "7":  "runs",           # stat_7 in raw — verify if needed
    "8":  "totalBases",
    "9":  "slugging",
    "10": "strikeouts_batting",
    "11": "intentionalWalks",
    "12": "gidp",
    "13": "stolenBases",
    "15": "caughtStealing",
    "16": "plateAppearances",
    "17": "obp",
    "18": "ops",
    "20": "runs",
    "21": "strikeouts_batting2",
    "23": "stolenBases2",
    "24": "caughtStealing2",
    "25": "hitByPitch",
    "26": "sacrifices",
    "27": "walks_batting",
    "81": "gamesPlayed",
    # Pitching
    "32": "wins",
    "33": "losses",
    "34": "gamesStarted",
    "35": "gamesAppeared",
    "36": "saves",
    "37": "blownSaves",
    "38": "holds",
    "39": "inningsPitched",
    "40": "hits_allowed",
    "41": "earnedRuns",
    "42": "homeRuns_allowed",
    "43": "walks_pitching",
    "44": "strikeouts_pitching",
    "45": "era",
    "46": "whip",
    "48": "qualityStarts",
    "53": "saves_plus_holds",
}

POSITION_MAP = {
    0:  "C",
    1:  "1B",
    2:  "2B",
    3:  "3B",
    4:  "SS",
    5:  "OF",
    6:  "2B/SS",
    7:  "1B/3B",
    8:  "LF",
    9:  "CF",
    10: "RF",
    11: "DH",
    12: "UTIL",
    13: "SP",
    14: "RP",
    15: "P",
    16: "BE",
    17: "IL",
    18: "NA",
}

STATUS_MAP = {
    "FREEAGENT": "Free Agent",
    "WAIVERS":   "Waivers",
    "ONTEAM":    "On Roster",
}

# ESPN MLB pro team IDs → full team name
# proTeamId=10 = New York Yankees is confirmed; others are best-effort — spot-check known players to verify
PRO_TEAM_MAP = {
    0:  "Free Agent",
    1:  "Baltimore Orioles",
    2:  "Boston Red Sox",
    3:  "Los Angeles Angels",
    4:  "Chicago White Sox",
    5:  "Cleveland Guardians",
    6:  "Detroit Tigers",
    7:  "Kansas City Royals",
    8:  "Milwaukee Brewers",
    9:  "Minnesota Twins",
    10: "New York Yankees",
    11: "Oakland Athletics",
    12: "Seattle Mariners",
    13: "Texas Rangers",
    14: "Toronto Blue Jays",
    15: "Atlanta Braves",
    16: "Chicago Cubs",
    17: "Cincinnati Reds",
    18: "Houston Astros",
    19: "Los Angeles Dodgers",
    20: "Washington Nationals",
    21: "New York Mets",
    22: "Philadelphia Phillies",
    23: "Pittsburgh Pirates",
    24: "St. Louis Cardinals",
    25: "San Diego Padres",
    26: "San Francisco Giants",
    27: "Colorado Rockies",
    28: "Miami Marlins",
    29: "Arizona Diamondbacks",
    30: "Tampa Bay Rays",
}


def get_session():
    s = requests.Session()
    s.headers.update({
        "Accept":          "application/json",
        "User-Agent":      "Mozilla/5.0",
        "X-Fantasy-Source": "kona",
        "X-Fantasy-Platform": "kona-PROD-1.4.4-branch-24-01-01",
    })
    return s


def fetch_fantasy_teams(session):
    """Fetch fantasy team names, abbreviations, and owner names from the league."""
    url = f"{BASE_URL}/segments/0/leagues/{LEAGUE_ID}/"
    resp = session.get(
        url,
        params={"view": "mTeam"},
        cookies={"espn_s2": ESPN_S2, "SWID": SWID},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    # Build member GUID → {firstName, lastName} lookup
    # Use firstName + lastName (not displayName, which is an ESPN username)
    members = {
        m["id"]: {
            "firstName": m.get("firstName", ""),
            "lastName":  m.get("lastName", ""),
        }
        for m in data.get("members", [])
    }

    # Build team ID → team info lookup
    team_map = {}
    for team in data.get("teams", []):
        team_id        = team["id"]
        name           = team.get("name", "")   # full team name is in "name" directly
        abbrev         = team.get("abbrev", "")
        primary_owner  = team.get("primaryOwner", "")
        member         = members.get(primary_owner, {})
        owner_name     = f"{member.get('firstName', '')} {member.get('lastName', '')}".strip()
        team_map[team_id] = {
            "name":           name,
            "abbrev":         abbrev,
            "ownerName":      owner_name,
            "ownerFirstName": member.get("firstName", ""),
            "ownerLastName":  member.get("lastName", ""),
        }

    return team_map


def fetch_players_page(session, offset, limit=100):
    """Fetch one page of players using the kona_player_info view."""
    url = f"{BASE_URL}/segments/0/leagues/{LEAGUE_ID}/"

    fantasy_filter = {
        "players": {
            "filterStatus": {
                "value": ["FREEAGENT", "WAIVERS", "ONTEAM"]
            },
            "limit":  limit,
            "offset": offset,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "filterStatsForTopScoringPeriodIds": {
                "value": 5,
                "additionalValue": [
                    f"00{SEASON}",   # full season
                    f"10{SEASON}",   # last 30 days
                    f"11{SEASON}",   # last 15 days
                    f"12{SEASON}",   # last 7 days
                    f"0{SEASON-1}",  # previous season
                ]
            }
        }
    }

    # Pass cookies directly in the request to avoid session jar domain-matching issues
    resp = session.get(
        url,
        params={"view": "kona_player_info"},
        headers={"X-Fantasy-Filter": json.dumps(fantasy_filter)},
        cookies={"espn_s2": ESPN_S2, "SWID": SWID},
        timeout=30,
    )
    resp.raise_for_status()
    if not resp.text.strip():
        raise ValueError("ESPN returned an empty response. Check your cookies.")
    if resp.text.strip()[0] != "{":
        print(f"\nDEBUG - Final URL (after redirects): {resp.url}")
        print(f"DEBUG - Status: {resp.status_code}")
        print(f"DEBUG - Response headers: {dict(resp.headers)}")
        print(f"DEBUG - Response (first 500 chars):\n{resp.text[:500]}")
        raise ValueError("ESPN returned non-JSON. See DEBUG output above.")
    data = resp.json()
    # Dump raw structure of first player entry on first call to help debug parsing
    if offset == 0:
        players_raw = data.get("players", [])
        if players_raw:
            with open("debug_raw_player.json", "w") as f:
                json.dump(players_raw[0], f, indent=2)
            print("\nDEBUG: Raw structure of first player written to debug_raw_player.json")
    return data


def parse_stats(raw_stats):
    """Convert raw ESPN stat arrays into a dict keyed by period label.
    Matches on the entry's 'id' field (e.g. '002026', '102026')."""
    period_ids = {
        f"00{SEASON}":   "season_total",
        f"10{SEASON}":   "projected",
        f"11{SEASON}":   "last_15_days",
        f"12{SEASON}":   "last_7_days",
        f"0{SEASON-1}":  "prev_season",
    }
    result = {}
    for entry in raw_stats:
        stat_id = entry.get("id", "")
        if stat_id not in period_ids:
            continue   # skip per-game entries
        label     = period_ids[stat_id]
        stats_raw = entry.get("stats", {})
        result[label] = {
            STAT_MAP.get(k, f"stat_{k}"): v
            for k, v in stats_raw.items()
        }
    return result


def parse_player(entry, fantasy_team_map):
    """Extract relevant fields from a raw player entry."""
    player    = entry.get("player", {})
    ownership = player.get("ownership", {})

    eligible_slots = [
        POSITION_MAP.get(s, str(s))
        for s in player.get("eligibleSlots", [])
        if s not in (16, 17, 18)   # skip BE / IL / NA
    ]

    pro_team_id  = player.get("proTeamId")
    on_team_id   = entry.get("onTeamId")
    fantasy_team = fantasy_team_map.get(on_team_id, {})

    return {
        "id":                   entry.get("id"),
        "fullName":             player.get("fullName"),
        "firstName":            player.get("firstName"),
        "lastName":             player.get("lastName"),
        "proTeam":              pro_team_id,
        "proTeamStr":           PRO_TEAM_MAP.get(pro_team_id, f"proTeam_{pro_team_id}"),
        "defaultPosition":      POSITION_MAP.get(player.get("defaultPositionId"), "?"),
        "eligiblePositions":    eligible_slots,
        "status":               STATUS_MAP.get(entry.get("status"), entry.get("status")),
        "onTeamId":             on_team_id,
        "onTeamIdStr":          fantasy_team.get("name"),
        "onTeamAbbr":           fantasy_team.get("abbrev"),
        "onTeamOwnerName":      fantasy_team.get("ownerName"),
        "onTeamOwnerFirstName": fantasy_team.get("ownerFirstName"),
        "onTeamOwnerLastName":  fantasy_team.get("ownerLastName"),
        "injured":              player.get("injured", False),
        "injuryStatus":         player.get("injuryStatus"),
        "percentOwned":         ownership.get("percentOwned"),
        "percentChange":        ownership.get("percentChange"),
        "percentStarted":       ownership.get("percentStarted"),
        "averageDraftPosition": ownership.get("averageDraftPosition"),
        "draftRanks":           player.get("draftRanksByRankType", {}),
        "seasonOutlook":        player.get("seasonOutlook"),
        "stats":                parse_stats(player.get("stats", [])),
    }


def main():
    while True:
        raw = input("Minimum % owned to include (e.g. 0.5), or press Enter for all players: ").strip()
        if raw == "":
            min_owned = 0.0
            break
        try:
            min_owned = float(raw)
            break
        except ValueError:
            print("  Please enter a number (e.g. 0.5 or 50).")

    if LEAGUE_ID == "YOUR_LEAGUE_ID":
        print("ERROR: Set your LEAGUE_ID at the top of the script.")
        return

    print(f"ESPN_S2 loaded: {'YES (' + ESPN_S2[:6] + '...) len=' + str(len(ESPN_S2)) if ESPN_S2 else 'NO'}")
    print(f"SWID loaded:    {'YES (' + SWID[:8] + '...) len=' + str(len(SWID)) if SWID else 'NO'}")

    session   = get_session()

    # Auth test: hit bare league endpoint before attempting paginated fetch
    print("Testing authentication...")
    test_url = f"{BASE_URL}/segments/0/leagues/{LEAGUE_ID}/"
    test_resp = session.get(test_url, cookies={"espn_s2": ESPN_S2, "SWID": SWID}, timeout=30)
    print(f"  Auth test URL:    {test_resp.url}")
    print(f"  Auth test status: {test_resp.status_code}")
    print(f"  Auth test is JSON: {test_resp.text.strip().startswith('{')}")
    if not test_resp.text.strip().startswith("{"):
        print(f"  Auth test response (first 200 chars): {test_resp.text[:200]}")
        print("\nAuthentication failed. The cookies may be expired or belong to a different ESPN account.")
        return

    print("Fetching fantasy team data...")
    fantasy_team_map = fetch_fantasy_teams(session)
    print(f"  Found {len(fantasy_team_map)} fantasy teams.")

    # Prompt: all players or a specific team?
    print("\nScope:")
    print("  0 - All players")
    sorted_teams = sorted(fantasy_team_map.items(), key=lambda x: x[1]["name"])
    for i, (tid, t) in enumerate(sorted_teams, start=1):
        print(f"  {i} - {t['name']} ({t['abbrev']}) — {t['ownerName']}")

    team_filter_id = None
    while True:
        choice = input("Enter 0 for all players, or a team number: ").strip()
        if choice == "0":
            break
        try:
            idx = int(choice)
            if 1 <= idx <= len(sorted_teams):
                team_filter_id = sorted_teams[idx - 1][0]
                print(f"  Filtering to: {fantasy_team_map[team_filter_id]['name']}")
                break
            else:
                print(f"  Please enter a number between 0 and {len(sorted_teams)}.")
        except ValueError:
            print("  Please enter a number.")

    all_players = []
    offset    = 0
    limit     = 100

    print(f"\nFetching players for league {LEAGUE_ID}, season {SEASON}...")

    while True:
        print(f"  offset={offset}...", end=" ", flush=True)
        try:
            data = fetch_players_page(session, offset, limit)
        except requests.HTTPError as e:
            print(f"\nHTTP error: {e}")
            print("  If your league is private, make sure ESPN_S2 and SWID are set.")
            break

        players_raw = data.get("players", [])
        if not players_raw:
            print("done.")
            break

        for entry in players_raw:
            player = parse_player(entry, fantasy_team_map)
            if team_filter_id is not None and player["onTeamId"] != team_filter_id:
                continue
            if (player["percentOwned"] or 0) >= min_owned:
                all_players.append(player)

        print(f"{len(players_raw)} players fetched (total kept: {len(all_players)})")

        if len(players_raw) < limit:
            break

        offset += limit
        time.sleep(0.3)   # be polite to ESPN's servers

    filtered_team = fantasy_team_map.get(team_filter_id, {}) if team_filter_id else None
    output = {
        "meta": {
            "leagueId":     LEAGUE_ID,
            "season":       SEASON,
            "fetchedOn":    str(date.today()),
            "minOwned":     min_owned,
            "teamFilter":   filtered_team.get("name") if filtered_team else "All",
            "totalPlayers": len(all_players),
        },
        "players": all_players,
    }

    filename = f"players_{date.today()}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved {len(all_players)} players to {filename}")


if __name__ == "__main__":
    main()
