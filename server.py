#!/usr/bin/env python3
"""
FastAPI server for VCK Online - Development/testing server
Simple REST API to replace the socket-based protocol
"""

import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import shortuuid

from game import Game, LobbyMember, GameMember, load_game_data, GameObjectEncoder
import json

_REPO_ROOT = Path(__file__).resolve().parent
_DEV_CLIENT_INDEX = _REPO_ROOT / "static" / "dev-client" / "index.html"

app = FastAPI(title="VCK Online API", description="Development server for Valeria Card Kingdoms Online")

# CORS middleware for web client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (simple for dev)
lobby: List[LobbyMember] = []
games: Dict[str, Game] = {}
gamers: List[GameMember] = []


# Request/Response models
class JoinLobbyRequest(BaseModel):
    name: str


class RenameRequest(BaseModel):
    player_id: str
    name: str


class ReadyRequest(BaseModel):
    player_id: str
    debug_starting_resources: bool = False


class ResourcePayment(BaseModel):
    """How much gold / strength / magic the client spends on an action (validated server-side)."""
    gold: int = 0
    strength: int = 0
    magic: int = 0


class GameActionRequest(BaseModel):
    player_id: str
    action_type: str  # "hire_citizen", "build_domain", "slay_monster", "take_resource", "act_on_required_action", "submit_concurrent_action"
    # Action parameters (varies by action type)
    citizen_id: Optional[int] = None
    domain_id: Optional[int] = None
    monster_id: Optional[int] = None
    # take_resource: "gold" | "strength" | "magic"
    resource: Optional[str] = None
    gold_cost: Optional[int] = None
    strength_cost: Optional[int] = None
    magic_cost: Optional[int] = None
    # Preferred: explicit payment split (gold/strength/magic). If set, overrides legacy *_cost fields for that action.
    payment: Optional[ResourcePayment] = None
    action: Optional[str] = None  # For act_on_required_action
    harvest_slot_key: Optional[str] = None  # harvest_card: e.g. "citizen:3:0"
    # submit_concurrent_action: which non-ordered prompt this responds to,
    # plus the opaque per-player payload (string; handler decides how to parse).
    kind: Optional[str] = None
    response: Optional[str] = None
    # finalize_roll: optional override dice values (1-6). If omitted, server finalizes using the rolled dice.
    die_one: Optional[int] = None
    die_two: Optional[int] = None


def _rollback_consumed_action(game):
    game.actions_remaining = int(getattr(game, "actions_remaining", 0)) + 1
    game.tick_id = int(getattr(game, "tick_id", 0)) - 1


def resolve_action_payment(req: GameActionRequest):
    if req.payment is not None:
        return int(req.payment.gold or 0), int(req.payment.strength or 0), int(req.payment.magic or 0)
    if req.action_type == "slay_monster":
        return 0, int(req.strength_cost or 0), int(req.magic_cost or 0)
    if req.action_type == "hire_citizen":
        return int(req.gold_cost or 0), 0, int(req.magic_cost or 0)
    if req.action_type == "build_domain":
        return int(req.gold_cost or 0), 0, int(req.magic_cost or 0)
    return int(req.gold_cost or 0), int(req.strength_cost or 0), int(req.magic_cost or 0)


# Lobby endpoints
@app.post("/api/lobby/join")
async def join_lobby(request: JoinLobbyRequest):
    """Join the lobby with a player name"""
    player_id = str(shortuuid.uuid())
    player = LobbyMember(request.name, player_id)
    player.last_active_time = time.time()
    lobby.append(player)
    return {"player_id": player_id, "message": "Joined lobby"}


@app.post("/api/lobby/rename")
async def rename_player(request: RenameRequest):
    """Rename a player in the lobby"""
    for player in lobby:
        if player.player_id == request.player_id:
            player.name = request.name
            player.last_active_time = time.time()
            return {"message": "Player renamed"}
    raise HTTPException(status_code=404, detail="Player not found in lobby")


@app.post("/api/lobby/leave")
async def leave_lobby(player_id: str):
    """Leave the lobby"""
    global lobby
    lobby = [p for p in lobby if p.player_id != player_id]
    return {"message": "Left lobby"}


@app.post("/api/lobby/ready")
async def set_ready(request: ReadyRequest):
    """Mark player as ready"""
    for player in lobby:
        if player.player_id == request.player_id:
            player.is_ready = True
            player.debug_starting_resources = bool(request.debug_starting_resources)
            player.last_active_time = time.time()
            
            # Check if all players are ready
            ready_count = sum(1 for p in lobby if p.is_ready)
            if ready_count == len(lobby) and len(lobby) >= 2:
                # Start game
                new_game_id = str(uuid.uuid4())
                players_to_remove = []
                
                for p in lobby:
                    if p.is_ready:
                        gamer = GameMember(p.player_id, p.name, new_game_id)
                        gamers.append(gamer)
                        players_to_remove.append(p)
                debug_starting_resources = any(bool(getattr(p, "debug_starting_resources", False)) for p in players_to_remove)
                
                # Remove ready players from lobby
                for p in players_to_remove:
                    lobby.remove(p)
                
                # Create game
                try:
                    # Get only the gamers for this new game
                    game_gamers = [g for g in gamers if g.game_id == new_game_id]
                    game_state = load_game_data(
                        new_game_id,
                        "base1",
                        game_gamers,
                        debug_starting_resources=debug_starting_resources,
                    )
                    new_game = Game(game_state)
                    new_game.last_active_time = time.time()
                    # Auto-run the start-of-game roll/harvest so the first state is actionable.
                    while new_game.advance_tick():
                        if getattr(new_game, "phase", None) == "action":
                            break
                    games[new_game_id] = new_game
                    return {
                        "message": "Game started",
                        "game_id": new_game_id,
                        "players": [{"player_id": g.player_id, "name": g.name} for g in game_gamers]
                    }
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to create game: {str(e)}")
            
            return {"message": "Player ready", "all_ready": ready_count == len(lobby)}
    
    raise HTTPException(status_code=404, detail="Player not found in lobby")


@app.post("/api/lobby/unready")
async def set_unready(request: ReadyRequest):
    """Mark player as not ready"""
    for player in lobby:
        if player.player_id == request.player_id:
            player.is_ready = False
            player.last_active_time = time.time()
            return {"message": "Player unready"}
    raise HTTPException(status_code=404, detail="Player not found in lobby")


@app.get("/api/lobby/status")
async def get_lobby_status(player_id: Optional[str] = None):
    """Get lobby status. If player_id provided, also check if player is in a game."""
    # Clean up inactive players (60 seconds)
    current_time = time.time()
    global lobby
    lobby = [p for p in lobby if current_time - p.last_active_time <= 60]
    
    lobby_data = []
    for member in lobby:
        lobby_data.append({
            "player_id": member.player_id,
            "name": member.name,
            "is_ready": member.is_ready,
            "debug_starting_resources": bool(getattr(member, "debug_starting_resources", False)),
        })
    
    response = {
        "lobby": lobby_data,
        "game_count": len(games)
    }
    
    # Check if player is in a game
    if player_id:
        for gamer in gamers:
            if gamer.player_id == player_id:
                response["in_game"] = True
                response["game_id"] = gamer.game_id
                return response
    
    response["in_game"] = False
    return response


# Game endpoints
def _serialize_game_for_player(game, viewer_player_id: Optional[str]):
    """
    Serialize the game state for a given viewer.

    Security/hidden-info rule:
    - Dukes are hidden information. Only the viewing player should see their own duke.
    """
    game_json = json.dumps(game, cls=GameObjectEncoder, indent=2)
    state = json.loads(game_json)

    players = state.get("player_list") or []
    if not isinstance(players, list):
        return state

    for p in players:
        if not isinstance(p, dict):
            continue
        pid = p.get("player_id")
        if not viewer_player_id or pid != viewer_player_id:
            # Hide opponent (and spectator) dukes.
            p["owned_dukes"] = []

    return state


@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str, player_id: Optional[str] = None):
    """Get the current game state"""
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game.last_active_time = time.time()
    # Ensure the beginning-of-turn roll/harvest are automatic (including the very first fetch).
    while getattr(game, "phase", None) in ("roll", "harvest"):
        if not game.advance_tick():
            break
        if getattr(game, "phase", None) == "action":
            break
    return _serialize_game_for_player(game, player_id)


@app.post("/api/game/{game_id}/action")
async def perform_game_action(game_id: str, request: GameActionRequest):
    """Perform a game action (hire citizen, build domain, slay monster, etc.)"""
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    
    game.last_active_time = time.time()
    
    try:
        if request.action_type == "hire_citizen":
            if request.citizen_id is None:
                raise HTTPException(status_code=400, detail="citizen_id required")
            if request.payment is None and request.gold_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or gold_cost/magic_cost required")
            if not game.consume_player_action(request.player_id):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            try:
                game.hire_citizen(request.player_id, request.citizen_id, g, m, s)
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()

        elif request.action_type == "build_domain":
            if request.domain_id is None:
                raise HTTPException(status_code=400, detail="domain_id required")
            if request.payment is None and request.gold_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or gold_cost/magic_cost required")
            if not game.consume_player_action(request.player_id):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            try:
                game.build_domain(request.player_id, request.domain_id, g, m, s)
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()
        
        elif request.action_type == "slay_monster":
            if request.monster_id is None:
                raise HTTPException(status_code=400, detail="monster_id required")
            if request.payment is None and request.strength_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or strength_cost/magic_cost required")
            if not game.consume_player_action(request.player_id):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            try:
                game.slay_monster(request.player_id, request.monster_id, s, m, g)
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()
        
        elif request.action_type == "take_resource":
            if request.resource is None or not str(request.resource).strip():
                raise HTTPException(status_code=400, detail='resource required ("gold", "strength", or "magic")')
            r = str(request.resource).strip().lower()
            if r not in ("gold", "strength", "magic"):
                raise HTTPException(status_code=400, detail='resource must be "gold", "strength", or "magic"')
            if not game.consume_player_action(request.player_id):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            try:
                game.take_resource(request.player_id, r)
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()
        
        elif request.action_type == "act_on_required_action":
            if request.action is None:
                raise HTTPException(status_code=400, detail="action required")
            game.act_on_required_action(request.player_id, request.action)
            # resolving a required action may unblock the engine
            game.advance_tick()

        elif request.action_type == "submit_concurrent_action":
            if request.response is None:
                raise HTTPException(status_code=400, detail="response required")
            try:
                game.submit_concurrent_action(
                    request.player_id,
                    request.response,
                    kind=request.kind,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        elif request.action_type == "finalize_roll":
            try:
                game.finalize_roll(request.player_id, die_one=request.die_one, die_two=request.die_two)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            # After finalizing, auto-advance harvest as far as possible.
            while getattr(game, "phase", None) == "harvest":
                if not game.advance_tick():
                    break
                if getattr(game, "phase", None) == "action":
                    break
        
        elif request.action_type == "roll_phase":
            raise HTTPException(status_code=400, detail="roll_phase is automatic; reserved for future reroll effects")
        
        elif request.action_type == "harvest_phase":
            raise HTTPException(status_code=400, detail="harvest_phase is automatic")
        
        elif request.action_type == "harvest_card":
            if not request.harvest_slot_key or not str(request.harvest_slot_key).strip():
                raise HTTPException(status_code=400, detail="harvest_slot_key required")
            try:
                game.harvest_card(request.player_id, str(request.harvest_slot_key).strip())
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        elif request.action_type == "play_turn":
            # Advance through roll+harvest, then leave at action phase
            # (player actions will drive action ticks)
            while game.advance_tick():
                if game.phase == "action":
                    break
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action type: {request.action_type}")
        
        # Return updated game state
        return {"message": "Action performed", "game_state": _serialize_game_for_player(game, request.player_id)}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Action failed: {str(e)}")


# Cleanup inactive games (runs periodically)
@app.on_event("startup")
async def startup_event():
    """Cleanup task for inactive games"""
    import asyncio
    
    async def cleanup():
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            current_time = time.time()
            inactive_games = [
                game_id for game_id, game in games.items()
                if current_time - game.last_active_time > 180
            ]
            for game_id in inactive_games:
                del games[game_id]
                # Remove gamers from this game
                global gamers
                gamers = [g for g in gamers if g.game_id != game_id]
    
    asyncio.create_task(cleanup())


# Serve static files and simple HTML client
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    pass  # static directory might not exist


@app.get("/")
async def root():
    """Simple HTML client for testing"""
    return FileResponse(_DEV_CLIENT_INDEX, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
