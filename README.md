# ESPN Fantasy Baseball Automation

Python scripts to automate ESPN Fantasy Baseball lineup management and player data pulls.

## Scripts

| Script | Description |
|---|---|
| `espn_lineup.py` | Automatically optimizes your pitcher lineup for today and future days. Uses MLB Stats API for probable starters, with ESPN PP badge data as a fallback for days further out. |
| `espn_players.py` | Pulls all player stats and ownership data to a JSON file |
| `test_espn_lineup.py` | Unit tests for the lineup optimizer logic |
| `test_espn_lineup_integration.py` | Integration tests — hit the real ESPN/MLB APIs (require credentials) |

## Setup

### 1. Install dependencies

```bash
pip install requests python-dotenv
```

### 2. Get your ESPN credentials

1. Log into ESPN Fantasy Baseball in Chrome
2. Open DevTools (F12) → Application → Cookies → `espn.com`
3. Copy the values for `espn_s2` and `SWID`

### 3. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```
ESPN_S2=your_espn_s2_value
SWID={your-swid-guid}
```

## Usage

### Lineup Optimizer

```bash
python espn_lineup.py                   # optimize today's lineup
python espn_lineup.py --dry-run         # preview changes without submitting
python espn_lineup.py --days 3          # optimize today + next 2 days
python espn_lineup.py --days 3 --dry-run
python espn_lineup.py --debug           # dump raw API responses for troubleshooting
```

### Player Data Export

```bash
python espn_players.py
```

Outputs `players_YYYY-MM-DD.json` with stats, ownership %, and roster status for all players.

### Tests

```bash
python -m pytest test_espn_lineup.py -v                  # unit tests (no network)
python -m pytest test_espn_lineup_integration.py -v      # integration tests (requires credentials)
```

## Configuration

Edit the top of each script to set your league:

```python
LEAGUE_ID  = "your_league_id"   # from your league's URL
SEASON     = 2026
MY_TEAM_ID = 5                  # your ESPN team ID
```

## How probable starter detection works

`espn_lineup.py` uses two data sources in priority order:

1. **MLB Stats API** — primary source; provides confirmed probable pitchers ~1–2 days out
2. **ESPN PP badge** — fallback for days beyond the MLB window; reads `starterStatusByProGame` from the roster API and cross-references it against ESPN's public MLB scoreboard to confirm which day each flagged game falls on
