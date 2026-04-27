#!/usr/bin/env python3
"""
FastAPI server for VCK Online - Development/testing server
Simple REST API to replace the socket-based protocol
"""

import time
import uuid
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import shortuuid

from game import Game, LobbyMember, GameMember, load_game_data, GameObjectEncoder
import json

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


class ResourcePayment(BaseModel):
    """How much gold / strength / magic the client spends on an action (validated server-side)."""
    gold: int = 0
    strength: int = 0
    magic: int = 0


class GameActionRequest(BaseModel):
    player_id: str
    action_type: str  # "hire_citizen", "buy_domain", "slay_monster", "take_resource", "act_on_required_action", "submit_concurrent_action"
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
    if req.action_type == "buy_domain":
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
                
                # Remove ready players from lobby
                for p in players_to_remove:
                    lobby.remove(p)
                
                # Create game
                try:
                    # Get only the gamers for this new game
                    game_gamers = [g for g in gamers if g.game_id == new_game_id]
                    game_state = load_game_data(new_game_id, "base1", game_gamers)
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
            "is_ready": member.is_ready
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
    """Perform a game action (hire citizen, buy domain, slay monster, etc.)"""
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
        
        elif request.action_type == "buy_domain":
            if request.domain_id is None:
                raise HTTPException(status_code=400, detail="domain_id required")
            if request.payment is None and request.gold_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or gold_cost/magic_cost required")
            if not game.consume_player_action(request.player_id):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            try:
                game.buy_domain(request.player_id, request.domain_id, g, m, s)
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


@app.get("/", response_class=HTMLResponse)
async def root():
    """Simple HTML client for testing"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>VCK Online - Dev Client</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
            .section { border: 1px solid #ccc; padding: 15px; margin: 10px 0; }
            button { padding: 8px 15px; margin: 5px; cursor: pointer; }
            input { padding: 5px; margin: 5px; }
            .lobby-player { padding: 5px; margin: 2px; background: #f0f0f0; }
            .ready { background: #90EE90; }
            pre { background: #f5f5f5; padding: 10px; overflow-x: auto; }
            details { margin-top: 10px; }
            details > summary { cursor: pointer; font-weight: 700; user-select: none; }
            .dice-row { display: flex; align-items: center; gap: 12px; margin: 10px 0; }
            .dice { display: flex; gap: 10px; align-items: center; }
            .dice-rig {
                margin-top: 8px;
                padding: 8px 10px;
                border: 1px solid #ddd;
                border-radius: 10px;
                background: #fff;
            }
            .dice-rig label { font-size: 13px; }
            .dice-rig-fields { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; align-items: center; }
            .dice-rig-fields input[type="number"] { width: 70px; }
            .dice-rig-hint { margin-top: 6px; font-size: 12px; color: #444; }
            .die {
                width: 44px; height: 44px;
                border: 2px solid #222;
                border-radius: 10px;
                background: #fff;
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                grid-template-rows: repeat(3, 1fr);
                padding: 6px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.08);
            }
            .pip { width: 8px; height: 8px; border-radius: 50%; background: #111; justify-self: center; align-self: center; }
            .pip.off { opacity: 0; }
            .dice-meta { color: #333; font-size: 14px; }
            .delta-wrap { display: flex; flex-wrap: wrap; gap: 10px; }
            .delta-card {
                border: 1px solid #ddd;
                background: #fafafa;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
                color: #222;
            }
            .delta-grid {
                display: grid;
                grid-template-columns: minmax(110px, 1fr) repeat(4, 64px);
                column-gap: 10px;
                row-gap: 2px;
                align-items: baseline;
            }
            .delta-name { font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            .delta-cell { display: grid; grid-template-columns: auto 1fr; column-gap: 6px; }
            .delta-label { color: #666; font-weight: 700; }
            .delta-value { text-align: right; font-variant-numeric: tabular-nums; font-feature-settings: "tnum" 1; }
            .delta-pos { color: #0a6; font-weight: 700; }
            .delta-neg { color: #b00; font-weight: 700; }
            .delta-zero { color: #666; font-weight: 700; }
            .delta-totals { color: #111; font-weight: 700; }
            .delta-muted { color: #666; font-weight: 600; }

            /* Tableau modal (dev UI) */
            .modal-backdrop {
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.45);
                display: none;
                z-index: 9999;
                padding: 30px;
            }
            .modal-backdrop.open { display: block; }
            .modal-panel {
                background: #fff;
                border-radius: 12px;
                max-width: 980px;
                margin: 0 auto;
                max-height: calc(100vh - 60px);
                overflow: auto;
                border: 1px solid rgba(0,0,0,0.15);
                box-shadow: 0 18px 60px rgba(0,0,0,0.35);
            }
            .modal-header {
                position: sticky;
                top: 0;
                background: #fff;
                border-bottom: 1px solid #eee;
                padding: 12px 14px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            }
            .modal-title { font-weight: 800; }
            .modal-close {
                border: 1px solid #ddd;
                background: #fafafa;
                border-radius: 10px;
                padding: 6px 10px;
                cursor: pointer;
                font-weight: 700;
            }
            .modal-body { padding: 14px; }
            .kv { display: flex; gap: 8px; flex-wrap: wrap; margin: 6px 0 12px; }
            .pill {
                border: 1px solid #e2e2e2;
                background: #f8f8f8;
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 13px;
                color: #222;
            }
            .tableau-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
            @media (max-width: 860px) { .tableau-grid { grid-template-columns: 1fr; } }
            .tableau-card {
                border: 1px solid #e6e6e6;
                border-radius: 10px;
                background: #fff;
                padding: 10px;
            }
            .tableau-card h3 { margin: 0 0 8px 0; font-size: 16px; }
            .mini { font-size: 13px; color: #444; }
            .list { display: flex; flex-direction: column; gap: 6px; }
            .item {
                border: 1px solid #eee;
                background: #fafafa;
                border-radius: 8px;
                padding: 8px 10px;
            }
            .item-title { font-weight: 800; }
            .item-sub { color: #555; font-size: 13px; margin-top: 3px; }

            /* Tableau seat buttons (around Board) */
            .tableau-actions { margin-top: 10px; }
            .tableau-seat-layout {
                position: relative;
                width: 100%;
                max-width: 760px;
                height: 220px;
                margin-top: 8px;
                border: 1px solid #e6e6e6;
                border-radius: 12px;
                background: #fff;
            }
            @media (max-width: 560px) { .tableau-seat-layout { height: 260px; } }
            .tableau-seat-btn {
                position: absolute;
                transform: translate(-50%, -50%);
                white-space: nowrap;
                border: 1px solid #ddd;
                background: #fafafa;
                border-radius: 10px;
                padding: 6px 10px;
                cursor: pointer;
                font-weight: 700;
            }
            .tableau-seat-btn.first-seat {
                border-color: #b7a200;
                background: #fff8cc;
            }
            .tableau-seat-btn.board-seat {
                background: #111;
                border-color: #111;
                color: #fff;
            }

            /* Payment editor (hire / buy / slay) */
            .pay-row { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
            .cost-line { flex: 1; min-width: 200px; }
            .pay-controls { display: none; margin-top: 4px; }
            .pay-controls.open { display: block; }
            .pay-controls input[type="number"] { width: 58px; }

            .game-log-wrap {
                margin-top: 14px;
                border: 1px solid #ccc;
                border-radius: 8px;
                background: #fafafa;
                overflow: hidden;
            }
            .game-log-wrap h3 {
                margin: 0;
                padding: 8px 10px;
                font-size: 14px;
                background: #eee;
                border-bottom: 1px solid #ddd;
            }
            #gameLog {
                max-height: 220px;
                overflow-y: auto;
                padding: 8px 10px;
                font-size: 12px;
                line-height: 1.45;
                font-family: ui-monospace, Menlo, Monaco, "Courier New", monospace;
                color: #222;
            }
            .game-log-line { margin: 2px 0; }
            .game-log-tick { color: #666; margin-right: 6px; user-select: none; }
        </style>
    </head>
    <body>
        <h1>VCK Online - Development Client</h1>
        
        <div class="section">
            <h2>Lobby</h2>
            <div>
                <input type="text" id="playerName" placeholder="Enter your name">
                <button onclick="joinLobby()">Join Lobby</button>
                <button onclick="getLobbyStatus()">Refresh</button>
            </div>
            <div id="lobbyStatus"></div>
            <div id="playerId" style="margin-top: 10px; font-weight: bold;"></div>
        </div>
        
        <div class="section">
            <h2>Game</h2>
            <div id="gameStatus"></div>
            <div class="dice-row">
                <div class="dice" id="dice"></div>
                <div>
                    <div class="dice-meta" id="diceMeta"></div>
                    <div class="dice-rig" id="diceRig">
                        <label>
                            <input type="checkbox" id="rigEnabled">
                            Use rigged dice (dev)
                        </label>
                        <div class="dice-rig-fields">
                            <label>Die 1
                                <input type="number" id="rigDie1" min="1" max="6" step="1">
                            </label>
                            <label>Die 2
                                <input type="number" id="rigDie2" min="1" max="6" step="1">
                            </label>
                        </div>
                        <div class="dice-rig-hint" id="rigHint"></div>
                    </div>
                    <div class="delta-wrap" id="harvestDeltas" style="margin-top: 6px;"></div>
                    <div id="choicePanel" style="margin-top: 8px;"></div>
                </div>
            </div>
            <div class="game-log-wrap">
                <h3>Game log</h3>
                <div id="gameLog" aria-live="polite"></div>
            </div>
            <button onclick="getGameState()">Refresh Game State</button>
            <div class="tableau-actions">
                <div class="mini"><strong>Tableau seats:</strong> buttons are arranged in turn order around the Board.</div>
                <div id="tableauSeatLayout" class="tableau-seat-layout" aria-label="Tableau seats"></div>
            </div>
            <details>
                <summary>Game state JSON</summary>
                <pre id="gameState"></pre>
            </details>
        </div>

        <div id="tableauModal" class="modal-backdrop" onclick="onTableauBackdropClick(event)">
            <div class="modal-panel" onclick="event.stopPropagation()">
                <div class="modal-header">
                    <div class="modal-title" id="tableauTitle">My Tableau</div>
                    <button class="modal-close" onclick="closeTableau()">Close</button>
                </div>
                <div class="modal-body" id="tableauBody"></div>
            </div>
        </div>
        
        <script>
            let playerId = localStorage.getItem('playerId') || '';
            let currentGameId = localStorage.getItem('gameId') || '';
            let lastGameState = null;
            let finalizeRollInFlight = false;

            function clampDie(n) {
                const x = Number(n);
                if (!Number.isFinite(x)) return 1;
                return Math.max(1, Math.min(6, Math.trunc(x)));
            }

            function getDiceRigSettings() {
                const enabled = localStorage.getItem('diceRigEnabled') === 'true';
                const d1 = clampDie(localStorage.getItem('diceRigDie1') || 1);
                const d2 = clampDie(localStorage.getItem('diceRigDie2') || 1);
                return { enabled, d1, d2 };
            }

            function setDiceRigSettings(next) {
                localStorage.setItem('diceRigEnabled', String(!!next.enabled));
                localStorage.setItem('diceRigDie1', String(clampDie(next.d1)));
                localStorage.setItem('diceRigDie2', String(clampDie(next.d2)));
            }

            function syncDiceRigUiFromStorage() {
                const enabledEl = document.getElementById('rigEnabled');
                const d1El = document.getElementById('rigDie1');
                const d2El = document.getElementById('rigDie2');
                if (!enabledEl || !d1El || !d2El) return;
                const s = getDiceRigSettings();
                enabledEl.checked = !!s.enabled;
                d1El.value = String(s.d1);
                d2El.value = String(s.d2);
                d1El.disabled = !s.enabled;
                d2El.disabled = !s.enabled;
            }

            function wireDiceRigUi() {
                const enabledEl = document.getElementById('rigEnabled');
                const d1El = document.getElementById('rigDie1');
                const d2El = document.getElementById('rigDie2');
                if (!enabledEl || !d1El || !d2El) return;

                const onChange = () => {
                    setDiceRigSettings({
                        enabled: enabledEl.checked,
                        d1: d1El.value,
                        d2: d2El.value,
                    });
                    syncDiceRigUiFromStorage();
                    // If we're currently waiting on a pending roll, apply immediately.
                    if (lastGameState) maybeFinalizePendingRoll(lastGameState);
                };

                enabledEl.addEventListener('change', onChange);
                d1El.addEventListener('change', onChange);
                d2El.addEventListener('change', onChange);
                d1El.addEventListener('input', onChange);
                d2El.addEventListener('input', onChange);

                syncDiceRigUiFromStorage();
            }
            // Poll handle used while a concurrent (non-ordered) prompt is active so
            // every browser session sees other players' progress in near-real-time.
            // Intentionally NOT an unconditional global poll: the standard-action panel
            // rebuilds payment inputs from gameState, and polling would wipe in-progress edits.
            // We do poll when waiting on others (passive) or during concurrent_action (below).
            let concurrentPollHandle = null;
            let passiveGamePollHandle = null;
            if (playerId) {
                document.getElementById('playerId').textContent = 'Player ID: ' + playerId;
            }
            wireDiceRigUi();
            
            async function joinLobby() {
                const name = document.getElementById('playerName').value;
                if (!name) {
                    alert('Please enter a name');
                    return;
                }
                try {
                    const response = await fetch('/api/lobby/join', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: name})
                    });
                    const data = await response.json();
                    playerId = data.player_id;
                    localStorage.setItem('playerId', playerId);
                    document.getElementById('playerId').textContent = 'Player ID: ' + playerId;
                    getLobbyStatus();
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }
            
            async function getLobbyStatus() {
                if (!playerId) return;
                try {
                    const response = await fetch(`/api/lobby/status?player_id=${playerId}`);
                    const data = await response.json();
                    
                    let html = '<h3>Players in Lobby:</h3>';
                    data.lobby.forEach(p => {
                        html += `<div class="lobby-player ${p.is_ready ? 'ready' : ''}">
                            ${p.name} - ${p.is_ready ? 'Ready' : 'Not Ready'}
                            ${p.player_id === playerId ? '<button onclick="toggleReady()">Toggle Ready</button>' : ''}
                        </div>`;
                    });
                    html += `<p>Active games: ${data.game_count}</p>`;
                    if (data.in_game) {
                        html += `<p><strong>You are in game: ${data.game_id}</strong></p>`;
                        if (data.game_id && data.game_id !== currentGameId) {
                            currentGameId = data.game_id;
                            localStorage.setItem('gameId', currentGameId);
                            // Fetch immediately when we first learn the game id
                            getGameState(false);
                        }
                    } else {
                        // If server says we're not in a game, clear any stale id
                        if (currentGameId) {
                            currentGameId = '';
                            localStorage.removeItem('gameId');
                            stopGamePollingIntervals();
                        }
                    }
                    document.getElementById('lobbyStatus').innerHTML = html;
                } catch (error) {
                    console.error('Error:', error);
                }
            }
            
            async function toggleReady() {
                if (!playerId) return;
                try {
                    const response = await fetch('/api/lobby/ready', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({player_id: playerId})
                    });
                    const data = await response.json();
                    if (data.game_id) {
                        currentGameId = data.game_id;
                        localStorage.setItem('gameId', currentGameId);
                        alert('Game started! Game ID: ' + data.game_id);
                        // Immediately fetch state so the Game section fills in
                        getGameState(false);
                    }
                    getLobbyStatus();
                } catch (error) {
                    console.error('Error:', error);
                }
            }
            
            function applyGameStateClientUpdate(data) {
                lastGameState = data;
                renderDice(data);
                syncDiceRigUiFromStorage();
                maybeFinalizePendingRoll(data);
                const pre = document.getElementById('gameState');
                if (pre) pre.textContent = JSON.stringify(data, null, 2);
                updateConcurrentPolling(data);
                updatePassiveGamePolling(data);
                refreshTableauActionButtons(data);
            }

            async function maybeFinalizePendingRoll(gameState) {
                if (!playerId || !currentGameId) return;
                if (!gameState) return;
                if (finalizeRollInFlight) return;
                const phase = (gameState.phase || '').toString();
                if (phase !== 'roll_pending') return;

                const req = gameState.action_required || {};
                const reqId = (req.id || '').toString();
                const reqAction = (req.action || '').toString();
                if (reqAction !== 'finalize_roll') return;
                if (reqId !== playerId) return;

                const rolled1 = clampDie(gameState.rolled_die_one ?? gameState.die_one ?? 1);
                const rolled2 = clampDie(gameState.rolled_die_two ?? gameState.die_two ?? 1);
                const s = getDiceRigSettings();
                const final1 = s.enabled ? clampDie(s.d1) : rolled1;
                const final2 = s.enabled ? clampDie(s.d2) : rolled2;

                finalizeRollInFlight = true;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'finalize_roll',
                            die_one: final1,
                            die_two: final2
                        })
                    });
                    const payload = await res.json();
                    if (!res.ok) {
                        console.error(payload);
                        return;
                    }
                    if (payload && payload.game_state) {
                        applyGameStateClientUpdate(payload.game_state);
                    } else {
                        getGameState(false);
                    }
                } catch (e) {
                    console.error(e);
                } finally {
                    finalizeRollInFlight = false;
                }
            }

            function refreshTableauActionButtons(gameState) {
                const wrap = document.getElementById('tableauSeatLayout');
                if (!wrap) return;
                wrap.innerHTML = '';
                const players = gameState && Array.isArray(gameState.player_list) ? gameState.player_list : [];
                const possessive = (name) => {
                    const s = (name ?? '').toString().trim();
                    if (!s) return 'Player';
                    const lower = s.toLowerCase();
                    if (lower.endsWith('s')) return `${s}'`;
                    return `${s}'s`;
                };

                // Board button (center)
                const boardBtn = document.createElement('button');
                boardBtn.type = 'button';
                boardBtn.className = 'tableau-seat-btn board-seat';
                boardBtn.textContent = 'Board';
                boardBtn.style.left = '50%';
                boardBtn.style.top = '50%';
                boardBtn.onclick = () => { openBoardTableau(); };
                wrap.appendChild(boardBtn);

                const cleanPlayers = players.filter(p => p && p.player_id);
                const n = cleanPlayers.length;
                if (!n) return;

                const seatAnglesDeg = (count) => {
                    if (count === 1) return [-90];
                    if (count === 2) return [180, 0];            // left / right
                    if (count === 3) return [-90, 150, 30];      // triangle around board
                    if (count === 4) return [-90, 0, 90, 180];   // top / right / bottom / left
                    // 5+ evenly spaced circle, starting at top, clockwise
                    const out = [];
                    for (let i = 0; i < count; i++) out.push(-90 + (360 * i) / count);
                    return out;
                };

                const angles = seatAnglesDeg(n);
                const w = wrap.clientWidth || 760;
                const h = wrap.clientHeight || 220;
                const radius = Math.max(70, Math.min(w, h) * 0.42);
                const firstPid = cleanPlayers[0]?.player_id || '';

                cleanPlayers.forEach((p, idx) => {
                    const pid = p.player_id;
                    const nm = ((p.name ?? '').toString().trim() || pid);
                    const isSelf = pid === playerId;
                    const isFirst = pid === firstPid;
                    const label = isSelf ? 'My Tableau' : `${possessive(nm)} Tableau`;

                    const deg = angles[idx % angles.length];
                    const rad = (deg * Math.PI) / 180;
                    const x = (w / 2) + radius * Math.cos(rad);
                    const y = (h / 2) + radius * Math.sin(rad);

                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'tableau-seat-btn' + (isFirst ? ' first-seat' : '');
                    btn.textContent = isFirst ? `${label} (First)` : label;
                    btn.style.left = `${x}px`;
                    btn.style.top = `${y}px`;
                    btn.onclick = () => { openSeatTableau(pid); };
                    wrap.appendChild(btn);
                });
            }

            async function getGameState(forcePrompt = true) {
                let gameId = currentGameId;
                if (!gameId && forcePrompt) {
                    gameId = prompt('Enter game ID:');
                }
                if (!gameId) return;
                currentGameId = gameId;
                localStorage.setItem('gameId', currentGameId);
                try {
                    const qs = playerId ? `?player_id=${encodeURIComponent(playerId)}` : '';
                    const response = await fetch(`/api/game/${gameId}/state${qs}`);
                    const data = await response.json();
                    applyGameStateClientUpdate(data);
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }

            async function ensureGameStateForTableau() {
                if (!currentGameId) {
                    alert('No game id yet. Start a game or refresh lobby status first.');
                    return false;
                }
                if (lastGameState && lastGameState.game_id === currentGameId) return true;
                try {
                    const qs = playerId ? `?player_id=${encodeURIComponent(playerId)}` : '';
                    const response = await fetch(`/api/game/${currentGameId}/state${qs}`);
                    const data = await response.json();
                    applyGameStateClientUpdate(data);
                    return true;
                } catch (e) {
                    alert('Error: ' + e.message);
                    return false;
                }
            }

            function stopGamePollingIntervals() {
                if (concurrentPollHandle) {
                    clearInterval(concurrentPollHandle);
                    concurrentPollHandle = null;
                }
                if (passiveGamePollHandle) {
                    clearInterval(passiveGamePollHandle);
                    passiveGamePollHandle = null;
                }
            }

            function updateConcurrentPolling(gameState) {
                // Only poll while a concurrent action is active. This keeps
                // non-pending players' UI honest as others submit, without
                // disturbing the rest of the in-game UI (which rebuilds inputs
                // on every render).
                const ca = gameState?.concurrent_action || null;
                const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
                const shouldPoll = pend.length > 0;
                if (shouldPoll && !concurrentPollHandle) {
                    concurrentPollHandle = setInterval(() => {
                        if (!currentGameId) return;
                        getGameState(false);
                    }, 1500);
                } else if (!shouldPoll && concurrentPollHandle) {
                    clearInterval(concurrentPollHandle);
                    concurrentPollHandle = null;
                }
            }

            function localGameUiIsFragile(gameState) {
                if (!playerId || !gameState) return false;
                const ca = gameState.concurrent_action || null;
                const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
                if (pend.length && pend.includes(playerId)) return true;
                const req = gameState.action_required || {};
                const reqId = req.id || '';
                const reqAction = (req.action || '').toString();
                if (!reqId || reqId === gameState.game_id) return false;
                if (reqId !== playerId) return false;
                if (reqAction === 'manual_harvest') return true;
                if (reqAction === 'bonus_resource_choice') return true;
                const trimmed = reqAction.trim();
                if (trimmed.startsWith('choose ')) return true;
                if (reqAction === 'standard_action' && (gameState.phase || '') === 'action') return true;
                return false;
            }

            function updatePassiveGamePolling(gameState) {
                if (!currentGameId) {
                    if (passiveGamePollHandle) {
                        clearInterval(passiveGamePollHandle);
                        passiveGamePollHandle = null;
                    }
                    return;
                }
                const ca = gameState?.concurrent_action || null;
                const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
                const concurrentBlocking = pend.length > 0;
                const fragile = localGameUiIsFragile(gameState);
                const shouldPoll = !concurrentBlocking && !fragile;

                if (shouldPoll && !passiveGamePollHandle) {
                    passiveGamePollHandle = setInterval(() => {
                        if (!currentGameId) {
                            clearInterval(passiveGamePollHandle);
                            passiveGamePollHandle = null;
                            return;
                        }
                        getGameState(false);
                    }, 2000);
                } else if (!shouldPoll && passiveGamePollHandle) {
                    clearInterval(passiveGamePollHandle);
                    passiveGamePollHandle = null;
                }
            }

            function escapeHtml(s) {
                return (s ?? '').toString()
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#039;');
            }

            function openModal() {
                const m = document.getElementById('tableauModal');
                if (m) m.classList.add('open');
            }

            function closeTableau() {
                const m = document.getElementById('tableauModal');
                if (m) m.classList.remove('open');
            }

            function onTableauBackdropClick(e) {
                // Click-out closes (panel stops propagation)
                closeTableau();
            }

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') closeTableau();
            });

            function pill(label, value) {
                return `<span class="pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
            }

            function citizenRoleCounts(card) {
                const r = card && card.roles;
                if (r && typeof r === 'object') {
                    return {
                        sn: Number(r.shadow) || 0,
                        hn: Number(r.holy) || 0,
                        son: Number(r.soldier) || 0,
                        wn: Number(r.worker) || 0,
                    };
                }
                return {
                    sn: Number(card.shadow_count) || 0,
                    hn: Number(card.holy_count) || 0,
                    son: Number(card.soldier_count) || 0,
                    wn: Number(card.worker_count) || 0,
                };
            }

            function formatHarvestGSM(card, onTurn) {
                const g = onTurn ? 'gold_payout_on_turn' : 'gold_payout_off_turn';
                const s = onTurn ? 'strength_payout_on_turn' : 'strength_payout_off_turn';
                const m = onTurn ? 'magic_payout_on_turn' : 'magic_payout_off_turn';
                const gv = Number(card[g]) || 0;
                const sv = Number(card[s]) || 0;
                const mv = Number(card[m]) || 0;
                return `G ${gv}, S ${sv}, M ${mv}`;
            }

            function pushHarvestHints(hints, card) {
                const hasOn = card.gold_payout_on_turn !== undefined || card.strength_payout_on_turn !== undefined || card.magic_payout_on_turn !== undefined;
                const hasOff = card.gold_payout_off_turn !== undefined || card.strength_payout_off_turn !== undefined || card.magic_payout_off_turn !== undefined;
                if (!hasOn && !hasOff) return;
                const onStr = formatHarvestGSM(card, true);
                const offStr = formatHarvestGSM(card, false);
                if (onStr === offStr) {
                    hints.push(`Harvest: ${onStr} (on & off turn)`);
                } else {
                    hints.push(`Harvest (on turn): ${onStr}`);
                    hints.push(`Harvest (off turn): ${offStr}`);
                }
            }

            function renderCardItem(card, count = 1) {
                if (!card || typeof card !== 'object') {
                    return `<div class="item"><div class="item-title">${escapeHtml(String(card))}</div></div>`;
                }
                const name = card.name || card.title || '(unnamed)';
                const id = card.starter_id || card.citizen_id || card.monster_id || card.domain_id || card.duke_id || card.id || '';

                const hints = [];
                if (card.roll_match1 !== undefined || card.roll_match2 !== undefined) {
                    const rm1 = card.roll_match1 ?? '';
                    const rm2 = card.roll_match2 ?? '';
                    hints.push(`Roll: ${rm1}${rm2 !== '' ? '/' + rm2 : ''}`);
                }
                if (card.gold_cost !== undefined) hints.push(`Gold cost: ${card.gold_cost}`);
                if (card.strength_cost !== undefined) hints.push(`Strength cost: ${card.strength_cost}`);
                if (card.magic_cost !== undefined) hints.push(`Magic cost: ${card.magic_cost}`);
                pushHarvestHints(hints, card);

                const { sn, hn, son, wn } = citizenRoleCounts(card);
                const roleParts = [];
                if (sn > 0) roleParts.push(`Shadow +${sn}`);
                if (hn > 0) roleParts.push(`Holy +${hn}`);
                if (son > 0) roleParts.push(`Soldier +${son}`);
                if (wn > 0) roleParts.push(`Worker +${wn}`);
                const isCitizen = card.citizen_id !== undefined && card.citizen_id !== null;
                const isDomain = card.domain_id !== undefined && card.domain_id !== null;
                const showRoleRow = (isCitizen || isDomain) && roleParts.length;
                const roleBlock = showRoleRow
                    ? `<div class="item-sub" style="margin-top:4px;"><strong>Roles:</strong> ${escapeHtml(roleParts.join(' · '))}</div>`
                    : '';

                const subtitle = hints.length ? `<div class="item-sub">${escapeHtml(hints.join(' · '))}</div>` : '';
                const fullText = cardFullText(card);
                const rulesText = fullText
                    ? `<div class="item-sub" style="margin-top:6px;white-space:pre-wrap;color:#333;">${escapeHtml(fullText)}</div>`
                    : '';
                const idText = id !== '' ? ` <span class="mini">(#${escapeHtml(id)})</span>` : '';
                const qty = Number(count) || 1;
                const qtyText = qty > 1 ? ` <span class="mini">x${qty}</span>` : '';
                return `<div class="item"><div class="item-title">${escapeHtml(name)}${qtyText}${idText}</div>${subtitle}${roleBlock}${rulesText}</div>`;
            }

            function groupCardsForTableau(cards) {
                const arr = Array.isArray(cards) ? cards : [];
                const map = new Map();
                arr.forEach((c) => {
                    if (!c || typeof c !== 'object') return;
                    const name = (c.name || c.title || '').toString().trim();
                    const id = c.starter_id || c.citizen_id || c.monster_id || c.domain_id || c.duke_id || c.id || '';
                    const key = `${name}||${id}`;
                    const cur = map.get(key);
                    if (cur) cur.count += 1;
                    else map.set(key, { card: c, count: 1, sortName: name.toLowerCase(), sortId: String(id) });
                });
                // If we saw non-objects in the list, just fall back to rendering raw items.
                if (map.size === 0 && arr.length) return null;
                return Array.from(map.values()).sort((a, b) => {
                    if (a.sortName < b.sortName) return -1;
                    if (a.sortName > b.sortName) return 1;
                    if (a.sortId < b.sortId) return -1;
                    if (a.sortId > b.sortId) return 1;
                    return 0;
                });
            }

            function renderCardList(title, cards) {
                const arr = Array.isArray(cards) ? cards : [];
                if (!arr.length) {
                    return `<div class="tableau-card"><h3>${escapeHtml(title)}</h3><div class="mini">none</div></div>`;
                }
                const grouped = groupCardsForTableau(arr);
                // If grouping failed (unexpected contents), keep the original behavior.
                if (!grouped) {
                    return `<div class="tableau-card">
                        <h3>${escapeHtml(title)} <span class="mini">(${arr.length})</span></h3>
                        <div class="list">${arr.map(renderCardItem).join('')}</div>
                    </div>`;
                }
                return `<div class="tableau-card">
                    <h3>${escapeHtml(title)} <span class="mini">(${arr.length} total, ${grouped.length} types)</span></h3>
                    <div class="list">${grouped.map(x => renderCardItem(x.card, x.count)).join('')}</div>
                </div>`;
            }

            function cardFullText(card) {
                if (!card || typeof card !== 'object') return '';

                // Prefer an explicit "text" field (Domains have this).
                const rawText = (card.text ?? '').toString().trim();
                if (rawText) return rawText;

                // Otherwise synthesize from other special/effect fields we already serialize.
                const parts = [];

                const passive = (card.passive_effect ?? '').toString().trim();
                const activation = (card.activation_effect ?? '').toString().trim();
                if (passive) parts.push(`Passive: ${passive}`);
                if (activation) parts.push(`Activation: ${activation}`);

                const spOn = (card.special_payout_on_turn ?? '').toString().trim();
                const spOff = (card.special_payout_off_turn ?? '').toString().trim();
                if (spOn) parts.push(`Special (on turn): ${spOn}`);
                if (spOff) parts.push(`Special (off turn): ${spOff}`);

                const specialReward = (card.special_reward ?? '').toString().trim();
                const specialCost = (card.special_cost ?? '').toString().trim();
                if (specialReward) parts.push(`Special reward: ${specialReward}`);
                if (specialCost) parts.push(`Special cost: ${specialCost}`);

                // Dukes don't currently have rules text in data, so show their multipliers as the "text".
                if (card.duke_id !== undefined) {
                    const mults = [];
                    const add = (label, val) => {
                        if (val === undefined || val === null) return;
                        const n = Number(val);
                        if (!Number.isFinite(n) || n === 0) return;
                        mults.push(`${label}×${n}`);
                    };
                    const addResource = (label, val) => {
                        if (val === undefined || val === null) return;
                        const n = Number(val);
                        if (!Number.isFinite(n) || n === 0) return;
                        // Duke resource scaling is "per N resources" (reciprocal display).
                        mults.push(`${label}×1/${n}`);
                    };
                    addResource('Gold', card.gold_multiplier);
                    addResource('Strength', card.strength_multiplier);
                    addResource('Magic', card.magic_multiplier);
                    add('Shadow', card.shadow_multiplier);
                    add('Holy', card.holy_multiplier);
                    add('Soldier', card.soldier_multiplier);
                    add('Worker', card.worker_multiplier);
                    add('Monster', card.monster_multiplier);
                    add('Citizen', card.citizen_multiplier);
                    add('Domain', card.domain_multiplier);
                    add('Boss', card.boss_multiplier);
                    add('Minion', card.minion_multiplier);
                    add('Beast', card.beast_multiplier);
                    add('Titan', card.titan_multiplier);
                    if (mults.length) parts.unshift(mults.join(' · '));
                }

                // NOTE: this HTML is embedded in a Python triple-quoted string, so we must escape backslashes
                // so the browser receives a literal "\\n" here (not an actual newline).
                return parts.join('\\n').trim();
            }

            function renderPlayerTableau(gameState, targetPlayerId, isSelfView) {
                const titleEl = document.getElementById('tableauTitle');
                const bodyEl = document.getElementById('tableauBody');
                if (!bodyEl) return;

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const subject = players.find(p => p?.player_id === targetPlayerId) || null;

                if (isSelfView) {
                    if (!playerId) {
                        if (titleEl) titleEl.textContent = 'My Tableau';
                        bodyEl.innerHTML = `<div class="tableau-card"><h3>Not joined</h3><div class="mini">Join the lobby first so we know your player id.</div></div>`;
                        return;
                    }
                    if (!subject) {
                        if (titleEl) titleEl.textContent = 'My Tableau';
                        bodyEl.innerHTML = `<div class="tableau-card"><h3>Player not in game</h3><div class="mini">No player with id <code>${escapeHtml(playerId)}</code> found in this game state.</div></div>`;
                        return;
                    }
                } else if (!subject) {
                    if (titleEl) titleEl.textContent = 'Tableau';
                    bodyEl.innerHTML = `<div class="tableau-card"><h3>Player not in game</h3><div class="mini">No player with id <code>${escapeHtml(targetPlayerId)}</code> in this game state.</div></div>`;
                    return;
                }

                const displayName = ((subject.name ?? '').toString().trim() || subject.player_id || 'Player');
                if (titleEl) {
                    const possessive = (name) => {
                        const s = (name ?? '').toString().trim();
                        if (!s) return 'Player';
                        const lower = s.toLowerCase();
                        if (lower.endsWith('s')) return `${s}'`;
                        return `${s}'s`;
                    };
                    titleEl.textContent = isSelfView ? 'My Tableau' : `${possessive(displayName)} Tableau`;
                }

                const resourceRow = `
                    <div class="kv">
                        ${pill('Gold', subject.gold_score ?? 0)}
                        ${pill('Strength', subject.strength_score ?? 0)}
                        ${pill('Magic', subject.magic_score ?? 0)}
                        ${pill('Victory', subject.victory_score ?? 0)}
                        ${pill('Shadow', subject.shadow_count ?? 0)}
                        ${pill('Holy', subject.holy_count ?? 0)}
                        ${pill('Soldier', subject.soldier_count ?? 0)}
                        ${pill('Worker', subject.worker_count ?? 0)}
                    </div>
                `;

                const dukes = Array.isArray(subject.owned_dukes) ? subject.owned_dukes : [];
                const duke = dukes.length ? dukes[0] : null;
                const dukeName = duke ? (duke?.name || 'Duke') : 'None';
                const dukeText = duke ? cardFullText(duke) : '';
                const dukeLine = `<div class="mini" style="margin-bottom:12px;">
                    <strong>Duke:</strong> ${escapeHtml(dukeName)}
                    ${dukeText ? `<div style="margin-top:6px;white-space:pre-wrap;color:#333;">${escapeHtml(dukeText)}</div>` : ''}
                </div>`;

                bodyEl.innerHTML = `
                    ${resourceRow}
                    ${dukeLine}
                    <div class="tableau-grid">
                        ${renderCardList('Starters', subject.owned_starters)}
                        ${renderCardList('Citizens', subject.owned_citizens)}
                        ${renderCardList('Monsters', subject.owned_monsters)}
                        ${renderCardList('Domains', subject.owned_domains)}
                    </div>
                `;
            }

            function boardStackMeta(kind, top, depth) {
                const bits = [];
                bits.push(depth + ' card' + (depth === 1 ? '' : 's'));
                if (kind === 'citizen' || kind === 'monster') {
                    bits.push(top.is_accessible ? 'top accessible' : 'top not accessible');
                }
                if (kind === 'domain') {
                    bits.push(top.is_visible ? 'top visible' : 'top hidden');
                    bits.push(top.is_accessible ? 'top accessible' : 'top not accessible');
                }
                return bits.join(' · ');
            }

            function renderBoardStackSection(title, grid, kind) {
                const g = Array.isArray(grid) ? grid : [];
                const blocks = g.map((stack, idx) => {
                    const depth = Array.isArray(stack) ? stack.length : 0;
                    if (!depth) {
                        return `<div class="item"><div class="item-title">Stack ${idx + 1}</div><div class="mini">empty</div></div>`;
                    }
                    const top = topOfStack(stack);
                    if (!top) {
                        return `<div class="item"><div class="item-title">Stack ${idx + 1}</div><div class="mini">empty</div></div>`;
                    }
                    const meta = boardStackMeta(kind, top, depth);
                    return `<div class="item" style="margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #eee;">
                        <div class="item-title">Stack ${idx + 1}</div>
                        <div class="mini" style="margin-bottom:6px;">${escapeHtml(meta)}</div>
                        ${renderCardItem(top)}
                    </div>`;
                });
                return `<div class="tableau-card"><h3>${escapeHtml(title)}</h3><div class="list">${blocks.join('')}</div></div>`;
            }

            function renderBoardTableau(gameState) {
                const titleEl = document.getElementById('tableauTitle');
                const bodyEl = document.getElementById('tableauBody');
                if (!bodyEl) return;
                if (titleEl) titleEl.textContent = 'Board (stacks)';
                const citizenGrid = Array.isArray(gameState?.citizen_grid) ? gameState.citizen_grid : [];
                const domainGrid = Array.isArray(gameState?.domain_grid) ? gameState.domain_grid : [];
                const monsterGrid = Array.isArray(gameState?.monster_grid) ? gameState.monster_grid : [];
                bodyEl.innerHTML = `
                    <div class="mini" style="margin-bottom:12px;">Top of each stack is the play surface; buried cards are not shown.</div>
                    <div class="tableau-grid">
                        ${renderBoardStackSection('Citizens (market)', citizenGrid, 'citizen')}
                        ${renderBoardStackSection('Domains', domainGrid, 'domain')}
                        ${renderBoardStackSection('Monsters', monsterGrid, 'monster')}
                    </div>
                `;
            }

            async function openMyTableau() {
                if (!(await ensureGameStateForTableau())) return;
                renderPlayerTableau(lastGameState, playerId, true);
                openModal();
            }

            async function openPlayerTableau(targetPlayerId) {
                if (!targetPlayerId) return;
                if (!(await ensureGameStateForTableau())) return;
                renderPlayerTableau(lastGameState, targetPlayerId, false);
                openModal();
            }

            async function openSeatTableau(targetPlayerId) {
                if (!targetPlayerId) return;
                if (!(await ensureGameStateForTableau())) return;
                const isSelf = targetPlayerId === playerId;
                renderPlayerTableau(lastGameState, targetPlayerId, isSelf);
                openModal();
            }

            async function openBoardTableau() {
                if (!(await ensureGameStateForTableau())) return;
                renderBoardTableau(lastGameState);
                openModal();
            }

            function diePipMask(value) {
                // grid indices: 0 1 2 / 3 4 5 / 6 7 8
                // positions: TL, TC, TR, ML, MC, MR, BL, BC, BR
                const masks = {
                    1: [4],
                    2: [0, 8],
                    3: [0, 4, 8],
                    4: [0, 2, 6, 8],
                    5: [0, 2, 4, 6, 8],
                    6: [0, 2, 3, 5, 6, 8]
                };
                return masks[value] || [];
            }

            function buildDie(value) {
                const die = document.createElement('div');
                die.className = 'die';
                const on = new Set(diePipMask(value));
                for (let i = 0; i < 9; i++) {
                    const pip = document.createElement('div');
                    pip.className = 'pip' + (on.has(i) ? '' : ' off');
                    die.appendChild(pip);
                }
                die.title = `d${value || 0}`;
                return die;
            }

            function renderGameLog(gameState) {
                const el = document.getElementById('gameLog');
                if (!el) return;
                const entries = Array.isArray(gameState?.game_log) ? gameState.game_log : [];
                if (!entries.length) {
                    el.textContent = '(No events yet.)';
                    return;
                }
                el.innerHTML = entries.map(e => {
                    const tick = e && e.tick !== undefined && e.tick !== null ? e.tick : '';
                    const msg = escapeHtml(String((e && e.msg) || (e && e.message) || ''));
                    return `<div class="game-log-line"><span class="game-log-tick">[${tick}]</span>${msg}</div>`;
                }).join('');
                el.scrollTop = el.scrollHeight;
            }

            function renderDice(gameState) {
                const rolled1 = Number(gameState?.rolled_die_one ?? gameState?.die_one ?? 0);
                const rolled2 = Number(gameState?.rolled_die_two ?? gameState?.die_two ?? 0);
                const rolledSum = Number(gameState?.rolled_die_sum ?? ((rolled1 || 0) + (rolled2 || 0)) ?? 0);
                const final1 = Number(gameState?.die_one || 0);
                const final2 = Number(gameState?.die_two || 0);
                const finalSum = Number(gameState?.die_sum || 0);

                const diceEl = document.getElementById('dice');
                const metaEl = document.getElementById('diceMeta');
                const deltaEl = document.getElementById('harvestDeltas');
                if (!diceEl || !metaEl) return;

                diceEl.innerHTML = '';
                diceEl.appendChild(buildDie(rolled1));
                diceEl.appendChild(buildDie(rolled2));

                const turn = gameState?.turn_number;
                const phase = gameState?.phase;
                const active = gameState?.active_player_id;
                const actionsRemaining = gameState?.actions_remaining;

                const parts = [];
                if (rolled1 && rolled2) parts.push(`<strong>${rolled1}</strong> + <strong>${rolled2}</strong> = <strong>${rolledSum}</strong>`);
                else parts.push(`<strong>Dice</strong>: not rolled`);
                if (rolled1 && rolled2 && final1 && final2 && (rolled1 !== final1 || rolled2 !== final2)) {
                    parts.push(`Final <strong>${final1}</strong> + <strong>${final2}</strong> = <strong>${finalSum}</strong>`);
                }
                if ((gameState?.phase || '') === 'roll_pending') {
                    parts.push(`<span style="display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #d6b26c;background:#fff6d8;color:#5b420a;font-weight:800;font-size:12px;">Awaiting finalize</span>`);
                }
                if (turn !== undefined) parts.push(`Turn <strong>${turn}</strong>`);
                if (phase) parts.push(`Phase <strong>${phase}</strong>`);
                if (actionsRemaining !== undefined) parts.push(`Actions remaining <strong>${actionsRemaining}</strong>`);
                if (active) parts.push(`Active <code>${active}</code>`);
                metaEl.innerHTML = parts.join(' · ');

                renderGameLog(gameState);

                // Update rig hint text.
                const hintEl = document.getElementById('rigHint');
                if (hintEl) {
                    const s = getDiceRigSettings();
                    const msg = s.enabled
                        ? `Enabled: will finalize as ${clampDie(s.d1)} + ${clampDie(s.d2)} (dice graphic still shows the real roll).`
                        : `Disabled: roll will be finalized as the real roll.`;
                    hintEl.textContent = msg;
                }

                if (!deltaEl) return;
                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                deltaEl.innerHTML = '';
                players.forEach(p => {
                    const d = p?.harvest_delta || {};
                    const g = Number(d.gold || 0);
                    const s = Number(d.strength || 0);
                    const m = Number(d.magic || 0);
                    const v = Number(d.victory || 0);
                    const G = Number(p?.gold_score || 0);
                    const S = Number(p?.strength_score || 0);
                    const M = Number(p?.magic_score || 0);
                    const V = Number(p?.victory_score || 0);

                    const card = document.createElement('div');
                    card.className = 'delta-card';
                    const name = p?.name || (p?.player_id ? p.player_id.slice(0, 6) : 'Player');

                    const fmt = (n) => (n > 0 ? `+${n}` : `${n}`);
                    const cls = (n) => (n > 0 ? 'delta-pos' : (n < 0 ? 'delta-neg' : 'delta-zero'));

                    card.innerHTML = `
                        <div class="delta-grid">
                            <span class="delta-name">${name}</span>
                            <span class="delta-cell"><span class="delta-label">ΔG</span><span class="delta-value ${cls(g)}">${fmt(g)}</span></span>
                            <span class="delta-cell"><span class="delta-label">ΔS</span><span class="delta-value ${cls(s)}">${fmt(s)}</span></span>
                            <span class="delta-cell"><span class="delta-label">ΔM</span><span class="delta-value ${cls(m)}">${fmt(m)}</span></span>
                            <span class="delta-cell"><span class="delta-label">ΔVP</span><span class="delta-value ${cls(v)}">${fmt(v)}</span></span>

                            <span class="delta-muted">Totals</span>
                            <span class="delta-cell"><span class="delta-label">G</span><span class="delta-value delta-totals">${G}</span></span>
                            <span class="delta-cell"><span class="delta-label">S</span><span class="delta-value delta-totals">${S}</span></span>
                            <span class="delta-cell"><span class="delta-label">M</span><span class="delta-value delta-totals">${M}</span></span>
                            <span class="delta-cell"><span class="delta-label">VP</span><span class="delta-value delta-totals">${V}</span></span>
                        </div>
                    `;
                    deltaEl.appendChild(card);
                });

                renderChoicePanel(gameState);
            }

            function renderChoicePanel(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                // Concurrent (non-ordered) prompts always take precedence over
                // turn-based action_required: while one is active the engine
                // will not advance and no per-player turn prompts are valid.
                const concurrent = gameState?.concurrent_action || null;
                if (concurrent && Array.isArray(concurrent.pending)) {
                    return renderConcurrentActionPanel(gameState, concurrent);
                }

                const req = gameState?.action_required || {};
                const reqId = req?.id || '';
                const reqAction = req?.action || '';
                const activePlayerId = gameState?.active_player_id || '';

                function harvestTurnBadge(forPlayerId) {
                    const pid = (forPlayerId || '').toString();
                    if (!pid || !activePlayerId) return '';
                    const onTurn = (pid === activePlayerId);
                    const bg = onTurn ? '#e8f7ee' : '#f1f1f1';
                    const border = onTurn ? '#8ad0a4' : '#cfcfcf';
                    const fg = onTurn ? '#1f6a3a' : '#444';
                    const label = onTurn ? 'On-turn harvest' : 'Off-turn harvest';
                    return `<span style="display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid ${border};background:${bg};color:${fg};font-size:12px;font-weight:700;">${label}</span>`;
                }

                if (!reqId || reqId === gameState?.game_id) {
                    panel.innerHTML = '';
                    return;
                }

                // Generic "choose ..." prompt from special payouts (e.g. "choose g 1 m 1")
                // Engine expects the response to be "choose 1"/"choose 2"/"choose 3".
                if (typeof reqAction === 'string' && reqAction.trim().startsWith('choose ')) {
                    return renderChoosePrompt(gameState, reqAction);
                }

                if (reqAction === 'manual_harvest') {
                    const slots = Array.isArray(gameState?.harvest_prompt_slots) ? gameState.harvest_prompt_slots : [];
                    const isYou = (playerId && reqId === playerId);
                    if (!isYou) {
                        const badge = harvestTurnBadge(reqId);
                        panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                                <div>Manual harvest in progress for <code>${escapeHtml(reqId)}</code> (${slots.length} card(s)).</div>
                                ${badge}
                            </div>
                        </div>`;
                        return;
                    }
                    if (!slots.length) {
                        const badge = harvestTurnBadge(reqId);
                        panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                                <div>Harvest: no slots (try Refresh).</div>
                                ${badge}
                            </div>
                        </div>`;
                        return;
                    }
                    const thiefNote = slots.some(s => s.kind === 'citizen' && s.is_thief)
                        ? '<div class="mini" style="margin-bottom:8px;">If you have the Thief, harvest that citizen before other citizens.</div>'
                        : '';
                    const badge = harvestTurnBadge(reqId);
                    const btns = slots.map(s => {
                        const ai = Number(s.activation_index);
                        const dup = Number.isFinite(ai) && ai > 0 ? ` · #${ai + 1}` : '';
                        const ci = Number(s.card_idx);
                        const copy = Number.isFinite(ci) ? ` · copy ${ci + 1}` : '';
                        const label = `${escapeHtml(s.name || '')} (${escapeHtml(s.kind)} #${escapeHtml(String(s.card_id))}${copy}${dup})`;
                        const sk = escapeHtml(s.slot_key || '');
                        return `<button type="button" onclick="sendHarvestCard('${sk}')">Harvest: ${label}</button>`;
                    }).join(' ');
                    panel.innerHTML = `
                        <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
                                <div style="font-weight:700;">Harvest (choose order)</div>
                                ${badge}
                            </div>
                            ${thiefNote}
                            <div style="display:flex;gap:8px;flex-wrap:wrap;">${btns}</div>
                        </div>`;
                    return;
                }

                if (reqAction !== 'bonus_resource_choice') {
                    if (reqAction === 'standard_action') {
                        return renderStandardActionPanel(gameState);
                    }

                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${reqId}</code>: <strong>${reqAction}</strong>
                    </div>`;
                    return;
                }

                const isYou = (playerId && reqId === playerId);
                if (!isYou) {
                    const badge = harvestTurnBadge(reqId);
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                            <div>Harvest bonus choice pending for <code>${reqId}</code>.</div>
                            ${badge}
                        </div>
                    </div>`;
                    return;
                }

                const badge = harvestTurnBadge(reqId);
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
                            <div style="font-weight:700;">Harvest bonus: choose +1 resource</div>
                            ${badge}
                        </div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            <button onclick="sendBonusChoice('gold')">+1 Gold</button>
                            <button onclick="sendBonusChoice('strength')">+1 Strength</button>
                            <button onclick="sendBonusChoice('magic')">+1 Magic</button>
                        </div>
                    </div>
                `;
            }

            function labelForChoiceToken(tok) {
                const t = (tok || '').toString().trim().toLowerCase();
                if (t === 'g') return 'Gold';
                if (t === 's') return 'Strength';
                if (t === 'm') return 'Magic';
                if (t === 'v') return 'Victory';
                return tok;
            }

            function parseChooseCommand(cmd) {
                // Expected formats:
                // - "choose g 1 m 1" (two options)
                // - "choose g 1 s 1 m 1" (three options)
                const parts = (cmd || '').toString().trim().split(/\\s+/);
                if (!parts.length || parts[0] !== 'choose') return [];
                const options = [];
                // pairs start at index 1: [token, amount]
                for (let i = 1; i + 1 < parts.length; i += 2) {
                    const token = parts[i];
                    const amount = parts[i + 1];
                    const tl = (token || '').toString().trim().toLowerCase();
                    if (!(tl === 'g' || tl === 's' || tl === 'm' || tl === 'v')) continue;
                    options.push({ token, amount });
                    if (options.length >= 3) break;
                }
                return options;
            }

            function renderChoosePrompt(gameState, chooseCmd) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const req = gameState?.action_required || {};
                const reqId = req?.id || '';
                const isYou = (playerId && reqId === playerId);

                const options = parseChooseCommand(chooseCmd);
                if (!options.length) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${reqId}</code>: <strong>${escapeHtml(chooseCmd)}</strong>
                    </div>`;
                    return;
                }

                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${reqId}</code>: <strong>${escapeHtml(chooseCmd)}</strong>
                    </div>`;
                    return;
                }

                const buttons = options.map((opt, idx) => {
                    const label = labelForChoiceToken(opt.token);
                    const amt = Number(opt.amount);
                    const prettyAmt = Number.isFinite(amt) ? amt : opt.amount;
                    return `<button onclick="sendChooseIndex(${idx + 1})">+${escapeHtml(prettyAmt)} ${escapeHtml(label)}</button>`;
                }).join('');

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">Choose one</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            ${buttons}
                        </div>
                    </div>
                `;
            }

            async function sendChooseIndex(n) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `choose ${Number(n)}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            // Concurrent (non-ordered) prompt rendering.
            //
            // The server exposes `concurrent_action = { kind, pending, completed, ... }`.
            // Every participant sees this state at the same time; players in `pending`
            // can submit a response in any order, and the game only advances once
            // `pending` is empty. To add a new kind, register a renderer in
            // CONCURRENT_RENDERERS keyed on the same `kind` used server-side.
            const CONCURRENT_RENDERERS = {
                choose_duke: renderChooseDukeConcurrent,
            };

            function renderConcurrentActionPanel(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const renderer = CONCURRENT_RENDERERS[concurrent.kind];
                if (renderer) {
                    return renderer(gameState, concurrent);
                }

                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                    Waiting on concurrent action <strong>${escapeHtml(concurrent.kind || 'unknown')}</strong>
                    (${pending.length} player(s) still need to respond).
                </div>`;
            }

            function pendingPlayerLabels(gameState, pending) {
                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                return (pending || []).map(pid => {
                    const p = players.find(x => x?.player_id === pid);
                    return p?.name ? `${p.name}` : pid;
                });
            }

            function renderChooseDukeConcurrent(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
                const isPending = !!(playerId && pending.includes(playerId));
                const totalParticipants = pending.length + completed.length;

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const you = players.find(p => p?.player_id === playerId) || null;
                const waitingLabels = pendingPlayerLabels(gameState, pending);

                const statusLine = `<div class="mini" style="margin-bottom:8px;">
                    Starting setup: ${completed.length}/${totalParticipants} duke choice(s) submitted.
                    ${pending.length ? `Waiting on: <strong>${escapeHtml(waitingLabels.join(', '))}</strong>.` : ''}
                </div>`;

                if (!isPending) {
                    const youDone = !!(playerId && completed.includes(playerId));
                    const yourLine = youDone
                        ? `<div>You have already chosen your duke. Waiting on the other player(s).</div>`
                        : `<div>Starting setup is in progress.</div>`;
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}${yourLine}
                    </div>`;
                    return;
                }

                const dukes = Array.isArray(you?.owned_dukes) ? you.owned_dukes : [];
                if (!dukes.length) {
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}<div>No dukes found to choose from.</div>
                    </div>`;
                    return;
                }

                const buttons = dukes.map(d => {
                    const id = d?.duke_id;
                    const name = d?.name || `Duke #${id}`;
                    const fullText = cardFullText(d);
                    const sub = fullText ? `<div style="color:#333;font-size:13px;margin-top:6px;white-space:pre-wrap;">${escapeHtml(fullText)}</div>` : '';
                    return `<div style="border:1px solid #e6e6e6;background:#fff;border-radius:10px;padding:10px;">
                        <div style="font-weight:800;">${escapeHtml(name)} <span style="color:#666;font-weight:600;">(#${escapeHtml(id)})</span></div>
                        ${sub}
                        <div style="margin-top:8px;">
                            <button onclick="submitConcurrentAction('choose_duke', ${Number(id)})">Keep this duke</button>
                        </div>
                    </div>`;
                }).join('');

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${statusLine}
                        <div style="font-weight:800;margin-bottom:8px;">Choose 1 duke to keep</div>
                        <div style="display:flex;flex-direction:column;gap:8px;">${buttons}</div>
                    </div>
                `;
            }

            async function submitConcurrentAction(kind, response) {
                if (!playerId || !currentGameId) return;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'submit_concurrent_action',
                            kind: String(kind),
                            response: String(response)
                        })
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        alert(err.detail || res.statusText || 'Submit failed');
                        return;
                    }
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            function canAffordCost(player, cost) {
                const G = Number(player?.gold_score || 0);
                const S = Number(player?.strength_score || 0);
                const M = Number(player?.magic_score || 0);
                const goldCost = Number(cost?.gold || 0);
                const strengthCost = Number(cost?.strength || 0);
                const magicMin = Number(cost?.magicMin || 0);

                const remainingMagic = M - magicMin;
                if (remainingMagic < 0) return { ok: false };

                const deficitGold = Math.max(0, goldCost - G);
                const deficitStrength = Math.max(0, strengthCost - S);

                // Rule: you must contribute at least 1 of a required color to use magic as wild.
                // Example: cost S8 cannot be paid with M8 alone; you need at least S1, then M can cover the rest.
                if (goldCost > 0 && deficitGold > 0 && G <= 0) return { ok: false };
                if (strengthCost > 0 && deficitStrength > 0 && S <= 0) return { ok: false };

                const ok = (deficitGold + deficitStrength) <= remainingMagic;

                // Payment split used for sending action requests (avoid going negative server-side).
                const payGold = Math.min(G, goldCost);
                const payStrength = Math.min(S, strengthCost);
                const payMagic = magicMin + deficitGold + deficitStrength;
                return { ok, payGold, payStrength, payMagic, deficitGold, deficitStrength, remainingMagic };
            }

            function topOfStack(stack) {
                if (!Array.isArray(stack) || stack.length === 0) return null;
                return stack[stack.length - 1];
            }

            function ownedNameCount(player, name) {
                const target = (name ?? '').toString();
                if (!target) return 0;
                const starters = Array.isArray(player?.owned_starters) ? player.owned_starters : [];
                const citizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
                let n = 0;
                starters.forEach(c => { if ((c?.name ?? '').toString() === target) n += 1; });
                citizens.forEach(c => { if ((c?.name ?? '').toString() === target) n += 1; });
                return n;
            }

            function clampPayInt(value, minV, maxV) {
                let n = Math.floor(Number(value));
                if (!Number.isFinite(n)) n = 0;
                const lo = Math.floor(Number(minV) || 0);
                const hiRaw = maxV === '' || maxV === undefined || maxV === null ? null : Number(maxV);
                const hi = hiRaw === null || !Number.isFinite(hiRaw) ? null : Math.floor(hiRaw);
                n = Math.max(lo, n);
                if (hi !== null) n = Math.min(hi, n);
                return n;
            }

            function readPayRow(row) {
                const gEl = row.querySelector('.pay-g');
                const sEl = row.querySelector('.pay-s');
                const mEl = row.querySelector('.pay-m');
                const g = (!gEl || gEl.disabled) ? 0 : clampPayInt(gEl.value, gEl.min, gEl.max);
                const s = (!sEl || sEl.disabled) ? 0 : clampPayInt(sEl.value, sEl.min, sEl.max);
                const m = (!mEl || mEl.disabled) ? 0 : clampPayInt(mEl.value, mEl.min, mEl.max);
                return { gold: g, strength: s, magic: m };
            }

            function bindPayCostToggles(panel) {
                if (!panel) return;
                panel.querySelectorAll('.pay-cost-toggle').forEach((el) => {
                    el.onclick = function (e) {
                        e.preventDefault();
                        const key = el.getAttribute('data-pay-key');
                        if (!key) return;
                        const box = document.getElementById('pay-editor-' + key);
                        if (!box) return;
                        box.classList.toggle('open');
                    };
                });
            }

            async function hireCitizenFromRow(btn) {
                const row = btn.closest('.pay-row');
                if (!row || !playerId || !currentGameId) return;
                const p = readPayRow(row);
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'hire_citizen',
                        citizen_id: Number(row.dataset.citizenId),
                        payment: { gold: p.gold, strength: p.strength, magic: p.magic }
                    })
                });
                getGameState(false);
            }

            async function buyDomainFromRow(btn) {
                const row = btn.closest('.pay-row');
                if (!row || !playerId || !currentGameId) return;
                const p = readPayRow(row);
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'buy_domain',
                        domain_id: Number(row.dataset.domainId),
                        payment: { gold: p.gold, strength: p.strength, magic: p.magic }
                    })
                });
                getGameState(false);
            }

            async function slayMonsterFromRow(btn) {
                const row = btn.closest('.pay-row');
                if (!row || !playerId || !currentGameId) return;
                const p = readPayRow(row);
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'slay_monster',
                        monster_id: Number(row.dataset.monsterId),
                        payment: { gold: p.gold, strength: p.strength, magic: p.magic }
                    })
                });
                getGameState(false);
            }

            function renderStandardActionPanel(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const req = gameState?.action_required || {};
                const reqId = req?.id || '';
                const isYou = (playerId && reqId === playerId);
                const phase = (gameState?.phase || '').toString();
                const actionsRemaining = Number(gameState?.actions_remaining || 0);

                if (!reqId || reqId === gameState?.game_id || phase !== 'action') {
                    panel.innerHTML = '';
                    return;
                }

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const you = players.find(p => p?.player_id === playerId) || null;
                const active = players.find(p => p?.player_id === reqId) || null;

                const p = (isYou ? you : active);
                const G = Number(p?.gold_score || 0);
                const S = Number(p?.strength_score || 0);
                const M = Number(p?.magic_score || 0);
                const V = Number(p?.victory_score || 0);

                const affordCitizens = [];
                const affordDomains = [];
                const affordMonsters = [];

                // Evaluate citizens (top of each stack, accessible only)
                const citizenGrid = Array.isArray(gameState?.citizen_grid) ? gameState.citizen_grid : [];
                citizenGrid.forEach((stack, idx) => {
                    const top = topOfStack(stack);
                    if (!top) return;
                    const baseCost = Number(top.gold_cost || 0);
                    const surcharge = ownedNameCount(p, top.name);
                    const scaledCost = baseCost + surcharge;
                    const evalRes = canAffordCost(p, { gold: scaledCost, strength: 0, magicMin: 0 });
                    console.log('[AFFORD_CHECK] citizen', { stackIndex: idx, stackSize: stack?.length || 0, card: top, player: { G, S, M, V }, eval: evalRes });
                    if (top.is_accessible && evalRes.ok) {
                        affordCitizens.push({ card: top, stackIndex: idx, stackSize: stack.length, pay: evalRes, scaledCost, surcharge, baseCost });
                    }
                });

                // Evaluate domains (top visible & accessible)
                const domainGrid = Array.isArray(gameState?.domain_grid) ? gameState.domain_grid : [];
                domainGrid.forEach((stack, idx) => {
                    const top = topOfStack(stack);
                    if (!top) return;
                    const evalRes = canAffordCost(p, { gold: Number(top.gold_cost || 0), strength: 0, magicMin: 0 });
                    console.log('[AFFORD_CHECK] domain', { stackIndex: idx, stackSize: stack?.length || 0, card: top, player: { G, S, M, V }, eval: evalRes });
                    if (top.is_visible && top.is_accessible && evalRes.ok) {
                        affordDomains.push({ card: top, stackIndex: idx, stackSize: stack.length, pay: evalRes });
                    }
                });

                // Evaluate monsters (top of each stack, accessible only; magic has minimum requirement)
                const monsterGrid = Array.isArray(gameState?.monster_grid) ? gameState.monster_grid : [];
                monsterGrid.forEach((stack, idx) => {
                    const top = topOfStack(stack);
                    if (!top) return;
                    const evalRes = canAffordCost(p, { gold: 0, strength: Number(top.strength_cost || 0), magicMin: Number(top.magic_cost || 0) });
                    console.log('[AFFORD_CHECK] monster', { stackIndex: idx, stackSize: stack?.length || 0, card: top, player: { G, S, M, V }, eval: evalRes });
                    if (top.is_accessible && evalRes.ok) {
                        affordMonsters.push({ card: top, stackIndex: idx, stackSize: stack.length, pay: evalRes });
                    }
                });

                const header = isYou
                    ? `<div style="font-weight:700;margin-bottom:6px;">Your action (${actionsRemaining} remaining)</div>`
                    : `<div style="font-weight:700;margin-bottom:6px;">Waiting on ${active?.name || reqId} to act (${actionsRemaining} remaining)</div>`;

                const resourcesLine = `<div style="margin-bottom:8px;">
                    Resources: <strong>G ${G}</strong> · <strong>S ${S}</strong> · <strong>M ${M}</strong> · <strong>VP ${V}</strong>
                </div>`;

                const takeResourceRow = isYou
                    ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid #ccc;">
                        <strong>Take resource</strong> (uses 1 action, gain +1):
                        <button type="button" style="margin-left:6px;" onclick="takeResourceFromChoice('gold')">+1 Gold</button>
                        <button type="button" style="margin-left:4px;" onclick="takeResourceFromChoice('strength')">+1 Strength</button>
                        <button type="button" style="margin-left:4px;" onclick="takeResourceFromChoice('magic')">+1 Magic</button>
                    </div>`
                    : '';

                const listSection = (title, items, renderItem) => {
                    if (!items.length) return `<div style="margin-top:8px;"><strong>${title}:</strong> <span style="color:#666;">none affordable</span></div>`;
                    const rows = items.map(renderItem).join('');
                    return `<div style="margin-top:8px;"><strong>${title}:</strong><div style="display:flex;flex-direction:column;gap:6px;margin-top:6px;">${rows}</div></div>`;
                };

                const citizenHtml = listSection('Citizens', affordCitizens, (it) => {
                    const c = it.card;
                    const key = 'c-' + c.citizen_id;
                    const cost = Number(it.scaledCost ?? c.gold_cost ?? 0);
                    const pay = it.pay;
                    const rc = citizenRoleCounts(c);
                    const rbits = [];
                    if (rc.sn) rbits.push('Shadow+' + rc.sn);
                    if (rc.hn) rbits.push('Holy+' + rc.hn);
                    if (rc.son) rbits.push('Soldier+' + rc.son);
                    if (rc.wn) rbits.push('Worker+' + rc.wn);
                    const roleHint = rbits.length ? ' <span style="color:#555;">Roles: ' + rbits.join(', ') + '</span>' : '';
                    const dupHint = Number(it.surcharge || 0)
                        ? ' <span style="color:#666;">(base ' + Number(it.baseCost || 0) + ' + ' + Number(it.surcharge || 0) + ' dupes)</span>'
                        : '';
                    const costSummary = 'Cost: G ' + cost + ' · pay G' + pay.payGold + (pay.payMagic ? ', M' + pay.payMagic : '') + dupHint + ' · Stack ' + it.stackSize;
                    const btn = isYou ? '<button type="button" onclick="hireCitizenFromRow(this)">Hire</button>' : '';
                    return '<div class="pay-row" data-citizen-id="' + c.citizen_id + '">' +
                        btn +
                        ' <span><strong>' + escapeHtml(c.name) + '</strong> (#' + c.citizen_id + ')' + roleHint + '</span>' +
                        ' <span class="cost-line" style="color:#555;">' +
                        '<span class="pay-cost-toggle" data-pay-key="' + key + '" style="cursor:pointer;text-decoration:underline;">' + costSummary + '</span>' +
                        '<div id="pay-editor-' + key + '" class="pay-controls">' +
                        '<span style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
                        '<label>G <input type="number" class="pay-g" min="0" max="' + G + '" value="' + pay.payGold + '"></label>' +
                        '<label>S <input type="number" class="pay-s" min="0" max="0" value="0" title="Citizens use gold and magic only"></label>' +
                        '<label>M <input type="number" class="pay-m" min="0" max="' + M + '" value="' + pay.payMagic + '"></label>' +
                        '</span></div></span></div>';
                });

                const domainHtml = listSection('Domains (visible tops)', affordDomains, (it) => {
                    const d = it.card;
                    const key = 'd-' + d.domain_id;
                    const cost = Number(d.gold_cost || 0);
                    const pay = it.pay;
                    const costSummary = 'Cost: G ' + cost + ' · pay G' + pay.payGold + (pay.payMagic ? ', M' + pay.payMagic : '') + ' · Stack ' + it.stackSize;
                    const btn = isYou ? '<button type="button" onclick="buyDomainFromRow(this)">Buy</button>' : '';
                    return '<div class="pay-row" data-domain-id="' + d.domain_id + '">' +
                        btn +
                        ' <span><strong>' + escapeHtml(d.name) + '</strong> (#' + d.domain_id + ')</span>' +
                        ' <span class="cost-line" style="color:#555;">' +
                        '<span class="pay-cost-toggle" data-pay-key="' + key + '" style="cursor:pointer;text-decoration:underline;">' + costSummary + '</span>' +
                        '<div id="pay-editor-' + key + '" class="pay-controls">' +
                        '<span style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
                        '<label>G <input type="number" class="pay-g" min="0" max="' + G + '" value="' + pay.payGold + '"></label>' +
                        '<label>S <input type="number" class="pay-s" min="0" max="0" value="0" title="Domains use gold and magic only"></label>' +
                        '<label>M <input type="number" class="pay-m" min="0" max="' + M + '" value="' + pay.payMagic + '"></label>' +
                        '</span></div></span></div>';
                });

                const monsterHtml = listSection('Monsters (top of each stack)', affordMonsters, (it) => {
                    const mcard = it.card;
                    const key = 'm-' + mcard.monster_id;
                    const sCost = Number(mcard.strength_cost || 0);
                    const mMin = Number(mcard.magic_cost || 0);
                    const pay = it.pay;
                    const costSummary = 'Cost: S ' + sCost + ' + M ' + mMin + ' min · pay S' + pay.payStrength + ', M' + pay.payMagic + ' · Stack ' + it.stackSize;
                    const btn = isYou ? '<button type="button" onclick="slayMonsterFromRow(this)">Slay</button>' : '';
                    return '<div class="pay-row" data-monster-id="' + mcard.monster_id + '">' +
                        btn +
                        ' <span><strong>' + escapeHtml(mcard.name) + '</strong> (#' + mcard.monster_id + ')</span>' +
                        ' <span class="cost-line" style="color:#555;">' +
                        '<span class="pay-cost-toggle" data-pay-key="' + key + '" style="cursor:pointer;text-decoration:underline;">' + costSummary + '</span>' +
                        '<div id="pay-editor-' + key + '" class="pay-controls">' +
                        '<span style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
                        '<label>G <input type="number" class="pay-g" min="0" max="0" value="0" title="Monsters use strength and magic only"></label>' +
                        '<label>S <input type="number" class="pay-s" min="0" max="' + S + '" value="' + pay.payStrength + '"></label>' +
                        '<label>M <input type="number" class="pay-m" min="0" max="' + M + '" value="' + pay.payMagic + '"></label>' +
                        '</span></div></span></div>';
                });

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${header}
                        ${resourcesLine}
                        ${takeResourceRow}
                        ${citizenHtml}
                        ${domainHtml}
                        ${monsterHtml}
                    </div>
                `;
                bindPayCostToggles(panel);
            }

            async function takeResourceFromChoice(resource) {
                if (!playerId || !currentGameId) return;
                const r = (resource || '').toString().trim().toLowerCase();
                if (!['gold', 'strength', 'magic'].includes(r)) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'take_resource',
                        resource: r
                    })
                });
                getGameState(false);
            }

            async function sendBonusChoice(resource) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: resource
                        })
                    });
                    // Refresh state so UI updates immediately
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendHarvestCard(slotKey) {
                if (!playerId || !currentGameId) return;
                const sk = (slotKey || '').toString().trim();
                if (!sk) return;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'harvest_card',
                            harvest_slot_key: sk
                        })
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        alert(err.detail || res.statusText || 'Harvest failed');
                        return;
                    }
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                    alert(e.message || 'Harvest failed');
                }
            }

            async function hireCitizen(citizenId, goldCost, magicCost) {
                if (!playerId || !currentGameId) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'hire_citizen',
                        citizen_id: citizenId,
                        payment: {
                            gold: Number(goldCost || 0),
                            strength: 0,
                            magic: Number(magicCost || 0)
                        }
                    })
                });
                getGameState(false);
            }

            async function buyDomain(domainId, goldCost, magicCost) {
                if (!playerId || !currentGameId) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'buy_domain',
                        domain_id: domainId,
                        payment: {
                            gold: Number(goldCost || 0),
                            strength: 0,
                            magic: Number(magicCost || 0)
                        }
                    })
                });
                getGameState(false);
            }

            async function slayMonster(monsterId, strengthCost, magicCost) {
                if (!playerId || !currentGameId) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'slay_monster',
                        monster_id: monsterId,
                        payment: {
                            gold: 0,
                            strength: Number(strengthCost || 0),
                            magic: Number(magicCost || 0)
                        }
                    })
                });
                getGameState(false);
            }
            
            // Auto-refresh lobby status
            setInterval(getLobbyStatus, 2000);
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

