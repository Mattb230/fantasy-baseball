# ESPN Fantasy Baseball Automation

Python scripts to automate ESPN Fantasy Baseball lineup management and player data pulls.

## Scripts

| Script | Description |
|---|---|
| `espn_lineup.py` | Automatically optimizes your pitcher lineup for today and future days |
| `espn_players.py` | Pulls all player stats and ownership data to a JSON file |

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

## Configuration

Edit the top of each script to set your league:

```python
LEAGUE_ID  = "your_league_id"   # from your league's URL
SEASON     = 2026
MY_TEAM_ID = 5                  # your ESPN team ID
```
