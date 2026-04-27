# VCK Online FastAPI Server

Simple REST API server for developing and testing the Valeria Card Kingdoms Online game.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Make sure database is accessible (SSH tunnel if needed):
   ```bash
   ssh -L 3306:localhost:3306 lukesau.com
   ```

## Running the Server

```bash
python3 server.py
```

Or with uvicorn directly:
```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

The server will start on `http://localhost:8000`

## API Endpoints

### Lobby

- `POST /api/lobby/join` - Join lobby with name
  ```json
  {"name": "Player Name"}
  ```
  Returns: `{"player_id": "...", "message": "Joined lobby"}`

- `POST /api/lobby/ready` - Mark player as ready
  ```json
  {"player_id": "..."}
  ```
  Returns game info if all players ready

- `POST /api/lobby/unready` - Mark player as not ready
- `POST /api/lobby/leave?player_id=...` - Leave lobby
- `GET /api/lobby/status?player_id=...` - Get lobby status

### Game

- `GET /api/game/{game_id}/state` - Get current game state
- `POST /api/game/{game_id}/action` - Perform game action
  ```json
  {
    "player_id": "...",
    "action_type": "hire_citizen|buy_domain|slay_monster|act_on_required_action|roll_phase|harvest_phase|play_turn",
    "citizen_id": 123,  // for hire_citizen
    "domain_id": 456,   // for buy_domain
    "monster_id": 789,   // for slay_monster
    "gold_cost": 5,     // for hire_citizen/buy_domain
    "strength_cost": 3,  // for slay_monster
    "magic_cost": 0,    // optional
    "action": "choose 1" // for act_on_required_action
  }
  ```

## Web Client

Visit `http://localhost:8000` for a simple HTML client to test the API.

## Development Notes

- Games are stored in-memory (will be lost on server restart)
- Inactive games are cleaned up after 3 minutes of no activity
- Inactive lobby players are removed after 60 seconds
- This is a development/testing server, not production-ready


