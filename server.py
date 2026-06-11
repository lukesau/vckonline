#!/usr/bin/env python3
"""
FastAPI server for VCK Online - Development/testing server
Simple REST API to replace the socket-based protocol
"""

import re
import random
import time
import uuid
import asyncio
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import shortuuid

from game import Game, Lobby, LobbyMember, GameMember, load_game_data, GameObjectEncoder
from game_serialization import (
    deserialize_save_dict_to_game,
    serialize_game_to_save_dict,
)
import json

import build_game_js

_REPO_ROOT = Path(__file__).resolve().parent

try:
    build_game_js.build()
except Exception as exc:
    print(f"[server] WARNING: failed to rebuild static/game/game.js bundle: {exc}")
_DEV_CLIENT_INDEX = _REPO_ROOT / "static" / "dev-client" / "index.html"
_GAME_CLIENT_INDEX = _REPO_ROOT / "static" / "game" / "index.html"
_COUNTER_INDEX = _REPO_ROOT / "static" / "counter" / "index.html"
_WIKI_INDEX = _REPO_ROOT / "static" / "wiki" / "index.html"
_RULEBOOKS_DIR = _REPO_ROOT / "static" / "rulebooks"
# Standalone "rule card" images (not DB cards) live alongside the PDFs in
# static/rulebooks/. Files are named rule_card_<front|back>_<slug>.<ext> and are
# grouped into a front/back pair per slug.
_RULE_CARD_RE = re.compile(r"^rule_card_(front|back)_(.+)\.(?:png|jpg|jpeg)$", re.IGNORECASE)

# Cached wiki payload. Card data is static between server restarts; lazy-load on
# first request and reuse forever (override with ?refresh=1).
_wiki_cards_cache = None

# Card image directories — keyed by the singular type name used in filenames
_CARD_IMAGE_DIRS: Dict[str, Path] = {
    "monster": _REPO_ROOT / "images" / "monsters",
    "citizen": _REPO_ROOT / "images" / "citizens",
    "domain":  _REPO_ROOT / "images" / "domains",
    "duke":    _REPO_ROOT / "images" / "dukes",
    "starter": _REPO_ROOT / "images" / "starters",
    "event":   _REPO_ROOT / "images" / "exhausted",
    "noble":   _REPO_ROOT / "images" / "nobles",
}
# Single 400x570 back for all Exhausted tokens; generate with scripts/card_image_utils.py from images/exhausted_back.jpg
_EXHAUSTED_CARD_JPEG = _REPO_ROOT / "images" / "exhausted" / "exhausted_card.jpg"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Lobby background: card faces are drawn at random from these inclusive id
# ranges per card type and resolved through `/card-image/{type}/{id}`. Each
# type maps to a list of `[lo, hi]` sub-ranges so disjoint id blocks (e.g. the
# dukes) can be expressed without dragging in the empty ids between them. Widen
# a range here when new art lands; ids inside a range that have no file on disk
# simply 404 and are skipped client-side (the canvas preloads each card before
# showing it), so the ranges only need to bound each type.
_LOBBY_BG_CARD_RANGES = {
    "citizen": [[1, 49]],
    "domain": [[1, 80]],
    "monster": [[1, 189]],
    "duke": [[1, 21], [99, 102]],
    "event": [[1, 36]],
    "noble": [[1, 16]],
}


app = FastAPI(title="VCK Online API", description="Development server for Valeria Card Kingdoms Online")


class ConnectionManager:
    def __init__(self):
        self._conns: Dict[str, List[tuple]] = {}  # game_id -> [(ws, player_id)]

    async def connect(self, game_id: str, websocket: WebSocket, player_id: Optional[str] = None):
        await websocket.accept()
        self._conns.setdefault(game_id, []).append((websocket, player_id))

    def disconnect(self, game_id: str, websocket: WebSocket):
        self._conns[game_id] = [
            (ws, pid) for ws, pid in self._conns.get(game_id, []) if ws is not websocket
        ]

    async def broadcast(self, game_id: str, game):
        conns = list(self._conns.get(game_id, []))
        dead = []
        for ws, pid in conns:
            try:
                await ws.send_json({"type": "state", "state": _serialize_game_for_player(game, pid)})
            except Exception:
                dead.append(ws)
        if dead:
            self._conns[game_id] = [(ws, pid) for ws, pid in conns if ws not in dead]


manager = ConnectionManager()


# ── Lobby model ─────────────────────────────────────────────────────────────
#
# The server hosts many concurrent named lobbies; each lobby has an owner
# (initially the creator), a preset that determines how the board is dealt
# when the game starts, and a list of members. Members can move between
# lobbies only by leaving + (re)joining. Inactive members and empty lobbies
# are pruned by `_prune_stale_lobbies` after `_LOBBY_MEMBER_TIMEOUT_S`.

# Allowed presets the owner may choose. `current` is the live "Rotating
# Preset" alias and presently points at the `june2026` rotating deal in
# `game_setup.py`; rotating it to a future month is a one-line change there.
# `base` is the canonical Base Set deal exposed as a stable preset. The dated
# rotating presets (e.g. `june2026`) are valid but intentionally not surfaced
# as their own dropdown option — players reach the live one via `current`.
# `random` deals from every implemented card across all expansions (see
# `card_filters.keep_for_random`).
_VALID_LOBBY_PRESETS = ("current", "june2026", "base", "flamesandfrost", "shadowvale", "crimsonseas", "random", "draft")

# Lobby min-players bounds. The lower bound matches the historical default
# (the game has always required 2 players); the upper bound matches the
# engine cap (5-player decks add is_extra monsters and a 6th citizen copy).
_MIN_PLAYERS_FLOOR = 2
_MIN_PLAYERS_CEIL = 5

# Member idle timeout. The lobby is considered alive as long as it has at
# least one member whose `last_active_time` is within this window.
_LOBBY_MEMBER_TIMEOUT_S = 600

# Display-name limits (defensive; the client also enforces shorter caps).
_MAX_DISPLAY_NAME_LEN = 40


class LobbyWsManager:
    """Push lobby snapshots to subscribed browsers (personalized by optional player_id)."""

    def __init__(self):
        self._connections = {}  # WebSocket -> Optional[player_id]

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections[websocket] = None

    def disconnect(self, websocket: WebSocket):
        self._connections.pop(websocket, None)

    def identify(self, websocket: WebSocket, player_id: Optional[str]):
        if websocket in self._connections:
            pid = (player_id or "").strip() or None
            self._connections[websocket] = pid
            if pid:
                _, member = _find_member(pid)
                if member:
                    member.last_active_time = time.time()

    async def send_snapshot(self, websocket: WebSocket):
        pid = self._connections.get(websocket)
        try:
            payload = build_lobby_status_dict(pid)
            await websocket.send_json({"type": "lobby_status", **payload})
        except Exception:
            self.disconnect(websocket)

    async def broadcast_lobby(self):
        dead = []
        for ws in list(self._connections.keys()):
            pid = self._connections.get(ws)
            try:
                payload = build_lobby_status_dict(pid)
                await ws.send_json({"type": "lobby_status", **payload})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_game_started(self, game_id: str, player_ids: List[str]):
        dead = []
        msg = {"type": "game_started", "game_id": game_id, "player_ids": list(player_ids)}
        for ws in list(self._connections.keys()):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


lobby_ws_manager = LobbyWsManager()


def _validate_preset(preset: Optional[str]) -> str:
    p = (preset or "").strip().lower()
    if p not in _VALID_LOBBY_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset '{preset}'. Allowed: {', '.join(_VALID_LOBBY_PRESETS)}",
        )
    return p


def _validate_expansion_only(value, default=False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    return bool(value)


def _validate_duke_select_count(duke_select_count, default=2) -> int:
    if duke_select_count is None or (
        isinstance(duke_select_count, str) and not str(duke_select_count).strip()
    ):
        return int(default)
    try:
        n = int(duke_select_count)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="duke_select_count must be 2 or 3",
        )
    if n not in (2, 3):
        raise HTTPException(
            status_code=400,
            detail="duke_select_count must be 2 or 3",
        )
    return n


_PRESETS_WITH_EXPANSION_ONLY = frozenset({"base", "flamesandfrost", "shadowvale"})


def _validate_min_players(min_players, default=_MIN_PLAYERS_FLOOR) -> int:
    if min_players is None or (isinstance(min_players, str) and not min_players.strip()):
        return int(default)
    try:
        n = int(min_players)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"min_players must be an integer between {_MIN_PLAYERS_FLOOR} and {_MIN_PLAYERS_CEIL}",
        )
    if n < _MIN_PLAYERS_FLOOR or n > _MIN_PLAYERS_CEIL:
        raise HTTPException(
            status_code=400,
            detail=f"min_players must be between {_MIN_PLAYERS_FLOOR} and {_MIN_PLAYERS_CEIL}",
        )
    return n


def _normalize_display_name(name: Optional[str]) -> str:
    s = (name or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="Display name required.")
    return s[:_MAX_DISPLAY_NAME_LEN]


def _find_member(player_id: str):
    """Return (lobby, member) for `player_id`, or (None, None) if not found."""
    pid = (player_id or "").strip()
    if not pid:
        return None, None
    for lb in lobbies.values():
        for m in lb.members:
            if m.player_id == pid:
                return lb, m
    return None, None


def _remove_member_from_lobby(lb: Lobby, member: LobbyMember):
    """Detach `member` from `lb`, transferring ownership to the next member,
    closing the lobby when it empties, and cancelling any in-progress draft.

    Shared by self-leave and owner-kick so both paths behave identically.
    Does NOT broadcast; the caller is responsible for that. Returns True if
    the lobby still exists afterward, False if it was removed.
    """
    lb.members = [m for m in lb.members if m.player_id != member.player_id]
    if lb.owner_id == member.player_id:
        lb.owner_id = lb.members[0].player_id if lb.members else ""
    if not lb.members:
        lobbies.pop(lb.lobby_id, None)
        return False
    if lb.lobby_id in _draft_states:
        _cancel_draft(lb.lobby_id)
        for m in lb.members:
            m.is_ready = False
    return True


def _prune_stale_lobbies():
    """Remove inactive members; delete empty lobbies. Transfer ownership if needed."""
    cutoff = time.time() - _LOBBY_MEMBER_TIMEOUT_S
    for lb in list(lobbies.values()):
        kept = [m for m in lb.members if m.last_active_time >= cutoff]
        if len(kept) != len(lb.members):
            lb.members = kept
            if not any(m.player_id == lb.owner_id for m in kept):
                lb.owner_id = kept[0].player_id if kept else ""
        if not lb.members:
            _cancel_draft(lb.lobby_id)
            lobbies.pop(lb.lobby_id, None)


def _serialize_member(member: LobbyMember):
    return {
        "player_id": member.player_id,
        "name": member.name,
        "is_ready": bool(member.is_ready),
        "debug_mode": bool(getattr(member, "debug_mode", False)),
    }


def _serialize_lobby(lb: Lobby):
    return {
        "lobby_id": lb.lobby_id,
        "owner_id": lb.owner_id,
        "preset": lb.preset,
        "min_players": int(getattr(lb, "min_players", _MIN_PLAYERS_FLOOR)),
        "expansion_only": bool(getattr(lb, "expansion_only", False)),
        "duke_select_count": int(getattr(lb, "duke_select_count", 2)),
        "members": [_serialize_member(m) for m in lb.members],
    }


def _maybe_start_lobby_game(lb: Lobby):
    """If every member of `lb` is ready and the floor is met, start a game.

    The floor is `max(_MIN_PLAYERS_FLOOR, lb.min_players)` to defend against
    older lobbies created before `min_players` existed. Returns the new
    game_id if a game was started, `"draft_starting"` if the draft preset
    triggered a draft launch, or None if conditions aren't met. On a normal
    game start the lobby is removed from the lobbies dict.
    """
    floor = max(_MIN_PLAYERS_FLOOR, int(getattr(lb, "min_players", _MIN_PLAYERS_FLOOR)))
    if len(lb.members) < floor:
        return None
    if not all(m.is_ready for m in lb.members):
        return None

    if lb.preset == "draft":
        if lb.lobby_id not in _draft_states:
            asyncio.create_task(_start_draft(lb))
        return "draft_starting"

    new_game_id = str(uuid.uuid4())
    debug_mode = any(bool(getattr(m, "debug_mode", False)) for m in lb.members)

    game_gamers = []
    for m in lb.members:
        gm = GameMember(m.player_id, m.name, new_game_id)
        gamers.append(gm)
        game_gamers.append(gm)

    game_state = load_game_data(
        new_game_id,
        lb.preset,
        game_gamers,
        debug_mode=debug_mode,
        expansion_only=bool(getattr(lb, "expansion_only", False)),
        duke_select_count=int(getattr(lb, "duke_select_count", 2)),
    )
    new_game = Game(game_state)
    new_game.last_active_time = time.time()
    while new_game.advance_tick():
        if getattr(new_game, "phase", None) == "action":
            break
    games[new_game_id] = new_game
    _record_snapshot(new_game_id, new_game)

    lobbies.pop(lb.lobby_id, None)
    return new_game_id


def build_lobby_status_dict(player_id: Optional[str] = None):
    """Lobby list + active game count + optional in_game/game_id/lobby_id for this player."""
    _prune_stale_lobbies()

    response = {
        "lobbies": [_serialize_lobby(lb) for lb in lobbies.values()],
        "game_count": sum(1 for g in games.values() if getattr(g, "phase", None) != "game_over"),
        "valid_presets": list(_VALID_LOBBY_PRESETS),
        "min_players_range": [_MIN_PLAYERS_FLOOR, _MIN_PLAYERS_CEIL],
        "in_game": False,
        "game_id": None,
        "lobby_id": None,
    }

    pid = (player_id or "").strip()
    if pid:
        for gamer in gamers:
            if gamer.player_id == pid:
                response["in_game"] = True
                response["game_id"] = gamer.game_id
                return response
        lb, _ = _find_member(pid)
        if lb:
            response["lobby_id"] = lb.lobby_id
            draft = _draft_states.get(lb.lobby_id)
            if draft:
                response["draft"] = _serialize_draft_state_for_player(draft, pid)

    return response


# CORS middleware for web client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (simple for dev)
# Multiple concurrent lobbies; see _serialize_lobby / _prune_stale_lobbies.
lobbies: Dict[str, Lobby] = {}
games: Dict[str, Game] = {}
gamers: List[GameMember] = []

# Per-game ring buffer of save-dict snapshots taken right after each
# "real" player action (game boot baseline + each successful take_resource /
# hire_citizen / build_domain / slay_monster). Powers the dev client's "Back
# one step" button. Bounded so a long-running debug game doesn't grow without
# limit; each snapshot is ~tens of KB. Eventually this will be the unit of
# disk persistence (see docs/game.md "save/load").
#
# Why this is gated: harvest decisions, required-action prompt resolutions,
# concurrent-action submissions, rolls / rerolls, and engine-driven phase
# advances are NOT snapshotable. Otherwise "Back one step" would either land
# you in the middle of a multi-step prompt or undo only a fragment of a
# harvest, neither of which is useful. The action-phase player actions are the
# natural undo boundaries.
_GAME_HISTORY_MAX_LEN = 200
game_histories: Dict[str, deque] = {}


def _record_snapshot(game_id: str, game: Game) -> None:
    """Append the current game state to its history ring buffer.

    Called only after the "real" player actions (take_resource, hire_citizen,
    build_domain, slay_monster) and once at game boot to seed the baseline.
    Failures here must NEVER abort the action — log and continue.
    """
    if not game_id or not game:
        return
    try:
        snap = serialize_game_to_save_dict(game)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[server] WARNING: failed to snapshot game {game_id}: {exc}")
        return
    history = game_histories.get(game_id)
    if history is None:
        history = deque(maxlen=_GAME_HISTORY_MAX_LEN)
        game_histories[game_id] = history
    history.append(snap)


def _history_breadcrumb(snap: dict) -> dict:
    """Lightweight per-snapshot label for the history endpoint."""
    return {
        "turn_number": snap.get("turn_number"),
        "phase": snap.get("phase"),
        "active_player_id": snap.get("active_player_id"),
        "tick_id": snap.get("tick_id"),
        "action_required": (snap.get("action_required") or {}).get("action") or None,
        "concurrent_action_kind": (snap.get("concurrent_action") or {}).get("kind") if snap.get("concurrent_action") else None,
    }

_GAME_SHUTDOWN_DELAY_S = 30

# ── Hurry-up timer ───────────────────────────────────────────────────────────
#
# Per-action shot clock. While the game is waiting on the active player to
# pick their next standard action (phase=='action' + action_required.action
# == 'standard_action'), an asyncio task sleeps until `game.hurry_up_deadline`
# and then auto-takes +1 of the active player's lowest resource (random
# tie-break among tied lowest), consuming a single standard action so the
# turn continues as if they had clicked the button themselves.
#
# This replaces the older "game has been idle for 3 minutes" countdown that
# used to share the same UI slot. The state-poll safety net (see PASSIVE_GAME_POLL_MS
# in static/game/src/01-core.js) reset that older timer on every poll, so it
# no longer measured real player inactivity. The hurry-up clock is reset only
# when an action genuinely changes the game's state (see `_hurry_up_reset`
# call sites), so polls do not extend it.
#
# Idle-game cleanup (the 180s sweep in `startup_event`'s cleanup loop) is
# still useful for closed-browser games and is intentionally left alone.
HURRY_UP_SECONDS = 180.0
_hurry_up_tasks: Dict[str, asyncio.Task] = {}


def _hurry_up_should_run(game) -> bool:
    """True iff the game is waiting on the active player's next standard action."""
    if not game:
        return False
    if getattr(game, "shutdown", None):
        return False
    if getattr(game, "phase", None) != "action":
        return False
    ca = getattr(game, "concurrent_action", None) or None
    if ca and (ca.get("pending") or []):
        return False
    ar = getattr(game, "action_required", None) or {}
    aid = ar.get("id")
    aact = str(ar.get("action", "") or "").strip()
    if not aid or aid == getattr(game, "game_id", None):
        return False
    if aact != "standard_action":
        return False
    if int(getattr(game, "actions_remaining", 0) or 0) <= 0:
        return False
    return True


def _hurry_up_cancel(game_id: str) -> None:
    task = _hurry_up_tasks.pop(game_id, None)
    if task and not task.done():
        task.cancel()


def _hurry_up_reset(game_id: str) -> None:
    """(Re)arm the hurry-up clock for `game_id`, or clear it if no action is awaited.

    Called from every endpoint that mutates game state. Cancels any in-flight
    timer task and either reschedules a fresh `HURRY_UP_SECONDS` window
    (when the game is waiting on the active player) or clears the deadline.
    """
    _hurry_up_cancel(game_id)
    game = games.get(game_id)
    if not game:
        return
    if _hurry_up_should_run(game):
        deadline = time.time() + HURRY_UP_SECONDS
        game.hurry_up_deadline = deadline
        task = asyncio.create_task(_hurry_up_run(game_id, deadline))
        _hurry_up_tasks[game_id] = task
    else:
        game.hurry_up_deadline = 0.0


def _hurry_up_ensure(game_id: str) -> None:
    """Arm the hurry-up clock only if one isn't already armed for this game.

    Used by read-only endpoints (`GET /state`) where engine-driven
    auto-advances may have entered a new "waiting for active player"
    window without a real player action. Unlike `_hurry_up_reset` this
    leaves any existing deadline alone, so the state-poll safety net in
    the client cannot extend the timer.
    """
    game = games.get(game_id)
    if not game:
        return
    if not _hurry_up_should_run(game):
        _hurry_up_cancel(game_id)
        game.hurry_up_deadline = 0.0
        return
    existing = float(getattr(game, "hurry_up_deadline", 0.0) or 0.0)
    existing_task = _hurry_up_tasks.get(game_id)
    if existing > time.time() and existing_task and not existing_task.done():
        return
    _hurry_up_reset(game_id)


async def _hurry_up_run(game_id: str, deadline: float) -> None:
    try:
        delay = max(0.0, deadline - time.time())
        await asyncio.sleep(delay)
        await _hurry_up_apply(game_id, deadline)
    except asyncio.CancelledError:
        return
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[server] WARNING: hurry-up task for game {game_id} crashed: {exc}")


def _pick_lowest_resource(player) -> str:
    """Pick the resource with the lowest score, breaking ties randomly."""
    resources = {
        "gold": int(getattr(player, "gold_score", 0) or 0),
        "strength": int(getattr(player, "strength_score", 0) or 0),
        "magic": int(getattr(player, "magic_score", 0) or 0),
    }
    min_val = min(resources.values())
    tied = [k for k, v in resources.items() if v == min_val]
    return random.choice(tied)


async def _hurry_up_apply(game_id: str, deadline: float) -> None:
    game = games.get(game_id)
    if not game:
        return
    # Guard against late firing of a cancelled / superseded task.
    if not _hurry_up_should_run(game):
        _hurry_up_reset(game_id)
        return
    if abs(float(getattr(game, "hurry_up_deadline", 0) or 0) - deadline) > 0.5:
        return

    pid = game.current_player_id()
    player = game._player_by_id(pid)
    if not player:
        return

    chosen = _pick_lowest_resource(player)
    if not game.consume_player_action(pid, action_type="take_resource"):
        return
    try:
        game.take_resource(pid, chosen)
    except Exception:
        try:
            game.lifecycle.rollback_last_consumed_action()
        except Exception:
            pass
        return
    game._log_game_event(
        f"Hurry-up timer expired; auto-took +1 {chosen} for {game._player_label(pid)}."
    )
    game.finish_turn_if_no_actions_remaining()
    game.last_active_time = time.time()
    try:
        _record_snapshot(game_id, game)
    except Exception:
        pass
    await manager.broadcast(game_id, game)
    if getattr(game, "phase", None) == "game_over" and not getattr(game, "shutdown", None):
        await _initiate_game_shutdown(game_id, reason="game_over", initiated_by_player_id=None)
    _hurry_up_reset(game_id)


# ── Draft mode ───────────────────────────────────────────────────────────────
#
# When the "draft" preset is selected, all players readying up triggers a
# pre-game draft phase instead of an immediate game start. Monsters are voted
# on first (players pick top 5 stacks), then citizens one roll-slot at a time.
# Dukes and domains remain randomised. Each phase has a 30-second timer; the
# server advances immediately if all players vote before time runs out.

_DRAFT_MONSTER_VOTE_SECONDS = 120
_DRAFT_STARTER_VOTE_SECONDS = 30
_DRAFT_CITIZEN_VOTE_SECONDS = 30
_draft_states: Dict[str, dict] = {}
_draft_timer_tasks: Dict[str, asyncio.Task] = {}


def _serialize_monster_area_for_draft(area: str, rows: list, vote_count: int) -> dict:
    if not rows:
        return {"area": area, "front_card": None, "stack_cards": [], "vote_count": vote_count}
    sorted_rows = sorted(rows, key=lambda r: int(r.get("monster_order", 0)))
    front = sorted_rows[0]
    def _card_dict(r):
        return {
            "id": int(r["id_monsters"]),
            "name": r["name"],
            "strength_cost": int(r.get("strength_cost", 0)),
            "magic_cost": int(r.get("magic_cost", 0)),
            "vp_reward": int(r.get("vp_reward", 0)),
            "gold_reward": int(r.get("gold_reward", 0)),
            "strength_reward": int(r.get("strength_reward", 0)),
            "magic_reward": int(r.get("magic_reward", 0)),
            "has_special_reward": bool(r.get("has_special_reward", 0)),
            "special_reward": r.get("special_reward"),
            "has_special_cost": bool(r.get("has_special_cost", 0)),
            "special_cost": r.get("special_cost"),
            "monster_type": r.get("monster_type"),
            "expansion": r.get("expansion"),
        }
    return {
        "area": area,
        "front_card": _card_dict(front),
        "stack_cards": [_card_dict(r) for r in sorted_rows],
        "vote_count": vote_count,
    }


def _serialize_starter_for_draft(row: dict, vote_count: int) -> dict:
    return {
        "id": int(row["id_starters"]),
        "name": row["name"],
        "activation_trigger": row.get("activation_trigger") or "",
        "gold_payout_on_turn": int(row.get("gold_payout_on_turn", 0)),
        "gold_payout_off_turn": int(row.get("gold_payout_off_turn", 0)),
        "strength_payout_on_turn": int(row.get("strength_payout_on_turn", 0)),
        "strength_payout_off_turn": int(row.get("strength_payout_off_turn", 0)),
        "magic_payout_on_turn": int(row.get("magic_payout_on_turn", 0)),
        "magic_payout_off_turn": int(row.get("magic_payout_off_turn", 0)),
        "has_special_payout_on_turn": bool(row.get("has_special_payout_on_turn", 0)),
        "has_special_payout_off_turn": bool(row.get("has_special_payout_off_turn", 0)),
        "special_payout_on_turn": row.get("special_payout_on_turn"),
        "special_payout_off_turn": row.get("special_payout_off_turn"),
        "expansion": row.get("expansion"),
        "vote_count": vote_count,
    }


def _serialize_citizen_for_draft(row: dict, vote_count: int) -> dict:
    return {
        "id": int(row["id_citizens"]),
        "name": row["name"],
        "roll_match1": int(row["roll_match1"]),
        "roll_match2": int(row.get("roll_match2") or 0),
        "gold_cost": int(row.get("gold_cost", 0)),
        "gold_payout_on_turn": int(row.get("gold_payout_on_turn", 0)),
        "gold_payout_off_turn": int(row.get("gold_payout_off_turn", 0)),
        "strength_payout_on_turn": int(row.get("strength_payout_on_turn", 0)),
        "strength_payout_off_turn": int(row.get("strength_payout_off_turn", 0)),
        "magic_payout_on_turn": int(row.get("magic_payout_on_turn", 0)),
        "magic_payout_off_turn": int(row.get("magic_payout_off_turn", 0)),
        "has_special_payout_on_turn": bool(row.get("has_special_payout_on_turn", 0)),
        "has_special_payout_off_turn": bool(row.get("has_special_payout_off_turn", 0)),
        "special_payout_on_turn": row.get("special_payout_on_turn"),
        "special_payout_off_turn": row.get("special_payout_off_turn"),
        "expansion": row.get("expansion"),
        "vote_count": vote_count,
    }


def _serialize_draft_state_for_player(state: dict, player_id: Optional[str]) -> dict:
    pid = (player_id or "").strip()
    phase = state["phase"]

    monster_vote_counts: Dict[str, int] = {}
    for choices in state["votes_monsters"].values():
        for area in choices[:5]:
            monster_vote_counts[area] = monster_vote_counts.get(area, 0) + 1

    citizen_vote_counts: Dict[int, int] = {}
    for cid in state["votes_citizens"].values():
        citizen_vote_counts[int(cid)] = citizen_vote_counts.get(int(cid), 0) + 1

    starter_vote_counts: Dict[int, int] = {}
    for sid in state.get("votes_starters", {}).values():
        starter_vote_counts[int(sid)] = starter_vote_counts.get(int(sid), 0) + 1

    available_monsters = []
    available_citizens = []
    available_starters = []

    if phase == "monsters":
        for area, rows in state["monster_areas"].items():
            available_monsters.append(
                _serialize_monster_area_for_draft(area, rows, monster_vote_counts.get(area, 0))
            )
    elif phase == "starters":
        for row in state.get("starter_candidates", []):
            sid = int(row["id_starters"])
            available_starters.append(
                _serialize_starter_for_draft(row, starter_vote_counts.get(sid, 0))
            )
    elif phase == "citizens":
        current_roll = state.get("current_roll")
        if current_roll is not None:
            for row in state["citizens_by_roll"].get(current_roll, []):
                cid = int(row["id_citizens"])
                available_citizens.append(
                    _serialize_citizen_for_draft(row, citizen_vote_counts.get(cid, 0))
                )

    return {
        "phase": phase,
        "current_roll": state.get("current_roll"),
        "timer_end": state.get("timer_end", 0),
        "available_monsters": available_monsters,
        "available_citizens": available_citizens,
        "available_starters": available_starters,
        "my_monster_votes": list(state["votes_monsters"].get(pid, [])),
        "my_citizen_vote": state["votes_citizens"].get(pid),
        "my_starter_vote": state.get("votes_starters", {}).get(pid),
        "selected_monster_areas": list(state.get("selected_monster_areas", [])),
        "selected_citizens": {str(k): v for k, v in state.get("selected_citizens", {}).items()},
        "citizen_draft_round": len(state.get("selected_citizens", {})) + (1 if phase == "citizens" else 0),
        "citizen_draft_total": len(state.get("citizen_rolls_all", [])),
        "votes_submitted_count": (
            len(state["votes_monsters"]) if phase == "monsters"
            else len(state.get("votes_starters", {})) if phase == "starters"
            else len(state["votes_citizens"])
        ),
        "total_players": len(state["player_ids"]),
        "am_participant": pid in state["player_ids"],
        "last_result": state.get("last_result"),
    }


def _tally_monster_votes(state: dict) -> list:
    import random as _r
    vote_counts: Dict[str, int] = {}
    for choices in state["votes_monsters"].values():
        for area in choices[:5]:
            vote_counts[area] = vote_counts.get(area, 0) + 1
    areas_scored = [(area, vote_counts.get(area, 0)) for area in state["monster_areas"]]
    _r.shuffle(areas_scored)
    areas_scored.sort(key=lambda x: x[1], reverse=True)
    return [a[0] for a in areas_scored[:5]]


def _tally_starter_votes(state: dict) -> Optional[int]:
    import random as _r
    vote_counts: Dict[int, int] = {}
    for sid in state.get("votes_starters", {}).values():
        vote_counts[int(sid)] = vote_counts.get(int(sid), 0) + 1
    available = state.get("starter_candidates") or []
    if not available:
        return None
    if not vote_counts:
        return int(_r.choice(available)["id_starters"])
    max_votes = max(vote_counts.values())
    winners = [sid for sid, cnt in vote_counts.items() if cnt == max_votes]
    return _r.choice(winners)


def _tally_citizen_votes(state: dict) -> Optional[int]:
    import random as _r
    vote_counts: Dict[int, int] = {}
    for cid in state["votes_citizens"].values():
        vote_counts[int(cid)] = vote_counts.get(int(cid), 0) + 1
    current_roll = state.get("current_roll")
    if not current_roll:
        return None
    available = state["citizens_by_roll"].get(current_roll, [])
    if not available:
        return None
    if not vote_counts:
        return int(_r.choice(available)["id_citizens"])
    max_votes = max(vote_counts.values())
    winners = [cid for cid, cnt in vote_counts.items() if cnt == max_votes]
    return _r.choice(winners)


async def _run_draft_timer(lobby_id: str, timer_end: float):
    delay = max(0.0, timer_end - time.time())
    await asyncio.sleep(delay)
    await _advance_draft(lobby_id)


async def _start_draft(lb: "Lobby"):
    from game_setup import load_draft_card_pool
    lobby_id = lb.lobby_id
    n_players = len(lb.members)
    debug_mode = any(bool(getattr(m, "debug_mode", False)) for m in lb.members)

    try:
        monsters_by_area, citizens_by_roll, starter_candidates = load_draft_card_pool(n_players)
    except Exception as e:
        print(f"[draft] Failed to load card pool for lobby {lobby_id}: {e}")
        for m in lb.members:
            m.is_ready = False
        await lobby_ws_manager.broadcast_lobby()
        return

    expected_rolls = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]
    available_rolls = [r for r in expected_rolls if citizens_by_roll.get(r)]

    if len(monsters_by_area) < 5:
        print(f"[draft] Not enough monster areas ({len(monsters_by_area)} < 5) for lobby {lobby_id}")
        for m in lb.members:
            m.is_ready = False
        await lobby_ws_manager.broadcast_lobby()
        return

    if len(available_rolls) < 10:
        print(f"[draft] Not all 10 citizen rolls covered for lobby {lobby_id}: {available_rolls}")
        for m in lb.members:
            m.is_ready = False
        await lobby_ws_manager.broadcast_lobby()
        return

    if len(starter_candidates) < 1:
        print(f"[draft] No optional -1/-1 starter candidates for lobby {lobby_id}")
        for m in lb.members:
            m.is_ready = False
        await lobby_ws_manager.broadcast_lobby()
        return

    timer_end = time.time() + _DRAFT_MONSTER_VOTE_SECONDS
    _draft_states[lobby_id] = {
        "lobby_id": lobby_id,
        "n_players": n_players,
        "debug_mode": debug_mode,
        "phase": "monsters",
        "monster_areas": monsters_by_area,
        "votes_monsters": {},
        "selected_monster_areas": [],
        "citizen_rolls_all": list(available_rolls),
        "citizen_rolls": list(available_rolls),
        "current_roll": None,
        "citizens_by_roll": citizens_by_roll,
        "votes_citizens": {},
        "selected_citizens": {},
        "starter_candidates": starter_candidates,
        "votes_starters": {},
        "selected_starter_id": None,
        "timer_end": timer_end,
        "player_ids": [m.player_id for m in lb.members],
        "last_result": None,
    }

    await lobby_ws_manager.broadcast_lobby()
    task = asyncio.create_task(_run_draft_timer(lobby_id, timer_end))
    _draft_timer_tasks[lobby_id] = task


async def _advance_draft(lobby_id: str):
    state = _draft_states.get(lobby_id)
    if not state:
        return

    task = _draft_timer_tasks.pop(lobby_id, None)
    if task and not task.done():
        task.cancel()

    phase = state["phase"]

    if phase == "monsters":
        selected = _tally_monster_votes(state)
        state["selected_monster_areas"] = selected
        state["last_result"] = {"phase": "monsters", "selected": selected}
        state["phase"] = "starters"
        state["votes_starters"] = {}

    elif phase == "starters":
        winner_id = _tally_starter_votes(state)
        state["selected_starter_id"] = winner_id
        state["last_result"] = {"phase": "starters", "winner_id": winner_id}
        rolls = state["citizen_rolls"]
        if not rolls:
            await _finish_draft(lobby_id)
            return
        state["current_roll"] = rolls[0]
        state["citizen_rolls"] = rolls[1:]
        state["phase"] = "citizens"
        state["votes_citizens"] = {}

    elif phase == "citizens":
        winner_id = _tally_citizen_votes(state)
        current_roll = state["current_roll"]
        if winner_id is not None:
            state["selected_citizens"][current_roll] = winner_id
        state["last_result"] = {"phase": "citizens", "roll": current_roll, "winner_id": winner_id}
        rolls = state["citizen_rolls"]
        if not rolls:
            await _finish_draft(lobby_id)
            return
        state["current_roll"] = rolls[0]
        state["citizen_rolls"] = rolls[1:]
        state["votes_citizens"] = {}
    else:
        return

    if state["phase"] == "starters":
        timer_secs = _DRAFT_STARTER_VOTE_SECONDS
    elif state["phase"] == "citizens":
        timer_secs = _DRAFT_CITIZEN_VOTE_SECONDS
    else:
        timer_secs = _DRAFT_CITIZEN_VOTE_SECONDS
    timer_end = time.time() + timer_secs
    state["timer_end"] = timer_end
    await lobby_ws_manager.broadcast_lobby()
    task = asyncio.create_task(_run_draft_timer(lobby_id, timer_end))
    _draft_timer_tasks[lobby_id] = task


async def _finish_draft(lobby_id: str):
    state = _draft_states.pop(lobby_id, None)
    if not state:
        return
    lb = lobbies.get(lobby_id)
    if not lb:
        return

    draft_selections = {
        "monster_areas": state["selected_monster_areas"],
        "citizens": state["selected_citizens"],
    }
    if state.get("selected_starter_id") is not None:
        draft_selections["starter_id"] = state["selected_starter_id"]
    debug_mode = state["debug_mode"]
    new_game_id = str(uuid.uuid4())

    game_gamers_list = []
    for m in lb.members:
        gm = GameMember(m.player_id, m.name, new_game_id)
        gamers.append(gm)
        game_gamers_list.append(gm)

    try:
        game_state = load_game_data(
            new_game_id,
            "draft",
            game_gamers_list,
            debug_mode=debug_mode,
            draft_selections=draft_selections,
            expansion_only=bool(getattr(lb, "expansion_only", False)),
            duke_select_count=int(getattr(lb, "duke_select_count", 2)),
        )
        new_game = Game(game_state)
        new_game.last_active_time = time.time()
        while new_game.advance_tick():
            if getattr(new_game, "phase", None) == "action":
                break
        games[new_game_id] = new_game
        _record_snapshot(new_game_id, new_game)
        _hurry_up_reset(new_game_id)
        lobbies.pop(lobby_id, None)
        pid_list = [g.player_id for g in gamers if g.game_id == new_game_id]
        await lobby_ws_manager.broadcast_game_started(new_game_id, pid_list)
        await lobby_ws_manager.broadcast_lobby()
    except Exception as e:
        print(f"[draft] Failed to start game for lobby {lobby_id}: {e}")
        gamers[:] = [g for g in gamers if g.game_id != new_game_id]
        for m in lb.members:
            m.is_ready = False
        await lobby_ws_manager.broadcast_lobby()


def _cancel_draft(lobby_id: str):
    task = _draft_timer_tasks.pop(lobby_id, None)
    if task and not task.done():
        task.cancel()
    _draft_states.pop(lobby_id, None)


# Request/Response models
class CreateLobbyRequest(BaseModel):
    name: str
    preset: Optional[str] = "current"
    min_players: Optional[int] = None
    expansion_only: Optional[bool] = False
    duke_select_count: Optional[int] = 2


class JoinLobbyRequest(BaseModel):
    name: str
    lobby_id: str
    # Persistent client id (from vck_client). When supplied and already a
    # member of the target lobby, the join is treated as a rejoin/rename
    # instead of spawning a duplicate member.
    player_id: Optional[str] = None


class KickRequest(BaseModel):
    # Requester must be the lobby owner; `target_player_id` is the member to remove.
    player_id: str
    target_player_id: str


class RenameRequest(BaseModel):
    player_id: str
    name: str


class ReadyRequest(BaseModel):
    player_id: str
    debug_mode: bool = False


class SetPresetRequest(BaseModel):
    player_id: str
    preset: str


class SetMinPlayersRequest(BaseModel):
    player_id: str
    min_players: int


class SetExpansionOnlyRequest(BaseModel):
    player_id: str
    expansion_only: bool


class SetDukeSelectCountRequest(BaseModel):
    player_id: str
    duke_select_count: int


class AbandonGameRequest(BaseModel):
    player_id: str


class ResourcePayment(BaseModel):
    """How much gold / strength / magic the client spends on an action (validated server-side)."""
    gold: int = 0
    strength: int = 0
    magic: int = 0


class TomePayment(BaseModel):
    """How many face-up Tome tokens (per resource type) the client flips to help
    pay an action (Crimson Seas). Counts are validated server-side against the
    player's available face-up tomes; the flipped tomes refresh at end of turn."""
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
    event_id: Optional[int] = None  # For slaying Event cards on the board
    # take_resource: "gold" | "strength" | "magic" | "map"
    resource: Optional[str] = None
    # buy_goods: which Araby goods slots (0-based) to buy in one Sail action.
    slot_indices: Optional[List[int]] = None
    # rescue_noble: which Amarynth noble slot (0-based) to rescue.
    slot_index: Optional[int] = None
    gold_cost: Optional[int] = None
    strength_cost: Optional[int] = None
    magic_cost: Optional[int] = None
    # Preferred: explicit payment split (gold/strength/magic). If set, overrides legacy *_cost fields for that action.
    payment: Optional[ResourcePayment] = None
    # Optional Crimson Seas tome contribution (per-type counts) toward the cost.
    tome_payment: Optional[TomePayment] = None
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
    rollback = getattr(game, "rollback_last_consumed_action", None)
    if callable(rollback):
        rollback()
        return
    game.actions_remaining = int(getattr(game, "actions_remaining", 0)) + 1
    game.tick_id = int(getattr(game, "tick_id", 0)) - 1


def resolve_tome_payment(req: GameActionRequest):
    if req.tome_payment is None:
        return None
    return {
        "gold": int(req.tome_payment.gold or 0),
        "strength": int(req.tome_payment.strength or 0),
        "magic": int(req.tome_payment.magic or 0),
    }


def _redeem_payment_tomes(game, req: GameActionRequest, g, s, m):
    """For hire/build/slay: convert the requested face-up Tomes into treasury
    resources up front so the normal payment path spends them. `g/s/m` is the
    TOTAL payment (treasury + tomes), so each tome count must not exceed its
    matching total (otherwise the leftover credit would be free resources).
    Returns the redeemed counts (pass to `refund_tomes_from_score` on failure)
    or None. Raises ValueError on an illegal/unavailable request."""
    tome = resolve_tome_payment(req)
    if tome is None or not any(tome.values()):
        return None
    if tome["gold"] > int(g or 0) or tome["strength"] > int(s or 0) or tome["magic"] > int(m or 0):
        raise ValueError("Tome payment exceeds the amount being paid.")
    return game.redeem_tomes_to_score(req.player_id, tome)


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
@app.post("/api/lobby/create")
async def create_lobby(request: CreateLobbyRequest):
    """Create a new lobby, joining as its owner.

    Body: `{name, preset?, min_players?}`. The owner picks the preset
    that determines how the board is dealt at game start; only the owner
    may change it later (see `/api/lobby/preset`). Lobbies are nameless —
    clients identify them by `lobby_id` and surface them via their
    metadata (preset, member count/list, min-players floor).
    """
    display_name = _normalize_display_name(request.name)
    preset = _validate_preset(request.preset or "current")
    min_players = _validate_min_players(request.min_players, default=_MIN_PLAYERS_FLOOR)
    expansion_only = _validate_expansion_only(request.expansion_only, default=False)
    duke_select_count = _validate_duke_select_count(request.duke_select_count, default=2)
    if expansion_only and preset not in _PRESETS_WITH_EXPANSION_ONLY:
        expansion_only = False

    player_id = str(shortuuid.uuid())
    lobby_id = str(shortuuid.uuid())

    member = LobbyMember(display_name, player_id, lobby_id=lobby_id)
    member.last_active_time = time.time()

    lb = Lobby(
        lobby_id=lobby_id,
        owner_id=player_id,
        preset=preset,
        min_players=min_players,
        expansion_only=expansion_only,
        duke_select_count=duke_select_count,
    )
    lb.created_at = time.time()
    lb.members.append(member)
    lobbies[lobby_id] = lb

    await lobby_ws_manager.broadcast_lobby()
    return {"player_id": player_id, "lobby_id": lobby_id, "message": "Lobby created"}


@app.post("/api/lobby/join")
async def join_lobby(request: JoinLobbyRequest):
    """Join an existing lobby by `lobby_id`."""
    display_name = _normalize_display_name(request.name)
    lobby_id = (request.lobby_id or "").strip()
    if not lobby_id:
        raise HTTPException(status_code=400, detail="lobby_id required")

    lb = lobbies.get(lobby_id)
    if not lb:
        raise HTTPException(status_code=404, detail="Lobby not found")

    requested_pid = (request.player_id or "").strip()
    if requested_pid:
        existing_lb, existing_member = _find_member(requested_pid)
        if existing_member is not None:
            if existing_lb is lb:
                # Duplicate-join recovery: this client is already a member
                # (e.g. they hit "back" then re-joined the same lobby). Reuse
                # the existing member and just refresh the display name rather
                # than spawning a clone that can never ready up.
                existing_member.name = display_name
                existing_member.last_active_time = time.time()
                await lobby_ws_manager.broadcast_lobby()
                return {
                    "player_id": existing_member.player_id,
                    "lobby_id": lobby_id,
                    "message": "Rejoined lobby",
                }
            # Same client was sitting in a different lobby; pull them out
            # cleanly (ownership transfer / empty cleanup / draft cancel)
            # before re-adding so they only ever occupy one lobby.
            _remove_member_from_lobby(existing_lb, existing_member)
        player_id = requested_pid
    else:
        player_id = str(shortuuid.uuid())

    member = LobbyMember(display_name, player_id, lobby_id=lobby_id)
    member.last_active_time = time.time()
    lb.members.append(member)

    await lobby_ws_manager.broadcast_lobby()
    return {"player_id": player_id, "lobby_id": lobby_id, "message": "Joined lobby"}


@app.post("/api/lobby/rename")
async def rename_player(request: RenameRequest):
    """Rename a player in their current lobby."""
    new_name = _normalize_display_name(request.name)
    _, member = _find_member(request.player_id)
    if not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    member.name = new_name
    member.last_active_time = time.time()
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "Player renamed"}


@app.post("/api/lobby/leave")
async def leave_lobby(player_id: str):
    """Leave the player's current lobby. Transfers ownership or closes the lobby if empty."""
    lb, member = _find_member(player_id)
    if not lb:
        # Idempotent: already gone is fine.
        return {"message": "Not in a lobby"}
    _remove_member_from_lobby(lb, member)
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "Left lobby"}


@app.post("/api/lobby/kick")
async def kick_member(request: KickRequest):
    """Remove another member from the lobby. Only the lobby owner may call this."""
    target_pid = (request.target_player_id or "").strip()
    if not target_pid:
        raise HTTPException(status_code=400, detail="target_player_id required")
    lb, member = _find_member(request.player_id)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    if lb.owner_id != member.player_id:
        raise HTTPException(status_code=403, detail="Only the lobby owner may kick members")
    if target_pid == member.player_id:
        raise HTTPException(status_code=400, detail="Owner cannot kick themselves; leave instead")
    target = next((m for m in lb.members if m.player_id == target_pid), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Target is not a member of this lobby")
    _remove_member_from_lobby(lb, target)
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "Member kicked", "player_id": target_pid}


@app.post("/api/lobby/preset")
async def set_lobby_preset(request: SetPresetRequest):
    """Set the lobby's board preset. Only the lobby owner may call this."""
    preset = _validate_preset(request.preset)
    lb, member = _find_member(request.player_id)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    if lb.owner_id != member.player_id:
        raise HTTPException(status_code=403, detail="Only the lobby owner may change the preset")
    if lb.lobby_id in _draft_states:
        raise HTTPException(status_code=409, detail="Cannot change preset while a draft is in progress")
    lb.preset = preset
    if preset not in _PRESETS_WITH_EXPANSION_ONLY:
        lb.expansion_only = False
    member.last_active_time = time.time()
    # Changing the preset should reset readiness so members re-confirm.
    for m in lb.members:
        m.is_ready = False
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "Preset updated", "preset": preset}


@app.post("/api/lobby/expansion_only")
async def set_lobby_expansion_only(request: SetExpansionOnlyRequest):
    """Toggle expansion-only domains/dukes. Only the lobby owner may call this."""
    expansion_only = _validate_expansion_only(request.expansion_only, default=False)
    lb, member = _find_member(request.player_id)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    if lb.owner_id != member.player_id:
        raise HTTPException(status_code=403, detail="Only the lobby owner may change expansion_only")
    if lb.lobby_id in _draft_states:
        raise HTTPException(status_code=409, detail="Cannot change expansion_only while a draft is in progress")
    if expansion_only and lb.preset not in _PRESETS_WITH_EXPANSION_ONLY:
        raise HTTPException(
            status_code=400,
            detail="expansion_only is only available for base, flamesandfrost, and shadowvale presets",
        )
    lb.expansion_only = expansion_only
    member.last_active_time = time.time()
    for m in lb.members:
        m.is_ready = False
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "expansion_only updated", "expansion_only": expansion_only}


@app.post("/api/lobby/duke_select_count")
async def set_lobby_duke_select_count(request: SetDukeSelectCountRequest):
    """Set how many dukes each player is dealt (2 or 3). Only the owner may call this."""
    duke_select_count = _validate_duke_select_count(request.duke_select_count)
    lb, member = _find_member(request.player_id)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    if lb.owner_id != member.player_id:
        raise HTTPException(status_code=403, detail="Only the lobby owner may change duke_select_count")
    if lb.lobby_id in _draft_states:
        raise HTTPException(status_code=409, detail="Cannot change duke_select_count while a draft is in progress")
    lb.duke_select_count = duke_select_count
    member.last_active_time = time.time()
    for m in lb.members:
        m.is_ready = False
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "duke_select_count updated", "duke_select_count": duke_select_count}


@app.post("/api/lobby/min_players")
async def set_lobby_min_players(request: SetMinPlayersRequest):
    """Set the lobby's minimum player floor (2..5). Only the lobby owner may call this.

    The game will not auto-start until the lobby has at least this many members
    and all of them are ready. Defaults to 2 (historical behavior). Resets every
    member's ready flag so they re-confirm under the new floor.
    """
    floor = _validate_min_players(request.min_players)
    lb, member = _find_member(request.player_id)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    if lb.owner_id != member.player_id:
        raise HTTPException(status_code=403, detail="Only the lobby owner may change min_players")
    lb.min_players = floor
    member.last_active_time = time.time()
    for m in lb.members:
        m.is_ready = False
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "min_players updated", "min_players": floor}


@app.post("/api/lobby/ready")
async def set_ready(request: ReadyRequest):
    """Mark the player ready. If every member of their lobby is ready (>=2 players), start a game."""
    lb, member = _find_member(request.player_id)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")

    member.is_ready = True
    member.debug_mode = bool(request.debug_mode)
    member.last_active_time = time.time()

    try:
        new_game_id = _maybe_start_lobby_game(lb)
    except Exception as exc:
        # Roll the ready flag back so the player can retry without being stuck "ready" in a half-broken lobby.
        member.is_ready = False
        raise HTTPException(status_code=500, detail=f"Failed to create game: {exc}")

    if new_game_id == "draft_starting":
        await lobby_ws_manager.broadcast_lobby()
        return {"message": "Draft starting", "draft_starting": True}

    if new_game_id:
        _hurry_up_reset(new_game_id)
        pid_list = [g.player_id for g in gamers if g.game_id == new_game_id]
        await lobby_ws_manager.broadcast_game_started(new_game_id, pid_list)
        await lobby_ws_manager.broadcast_lobby()
        return {
            "message": "Game started",
            "game_id": new_game_id,
            "players": [{"player_id": g.player_id, "name": g.name} for g in gamers if g.game_id == new_game_id],
        }

    await lobby_ws_manager.broadcast_lobby()
    return {
        "message": "Player ready",
        "all_ready": all(m.is_ready for m in lb.members),
    }


@app.post("/api/lobby/unready")
async def set_unready(request: ReadyRequest):
    """Mark the player not ready."""
    _, member = _find_member(request.player_id)
    if not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    member.is_ready = False
    member.last_active_time = time.time()
    await lobby_ws_manager.broadcast_lobby()
    return {"message": "Player unready"}


@app.get("/api/lobby/status")
async def get_lobby_status(player_id: Optional[str] = None):
    """Return the list of lobbies plus per-player in_game/lobby_id metadata."""
    pid = (player_id or "").strip()
    if pid:
        _, member = _find_member(pid)
        if member:
            member.last_active_time = time.time()
    return build_lobby_status_dict(pid)


class DraftVoteRequest(BaseModel):
    player_id: str
    vote: Optional[object] = None  # list of area names (monsters) or int citizen_id


@app.post("/api/lobby/draft/vote")
async def submit_draft_vote(request: DraftVoteRequest):
    """Submit a draft vote. `vote` is a list of area names for the monster phase,
    a starter id (integer) for the starter phase, or a citizen id for the citizen phase."""
    pid = (request.player_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="player_id required")
    lb, member = _find_member(pid)
    if not lb or not member:
        raise HTTPException(status_code=404, detail="Player not found in any lobby")
    member.last_active_time = time.time()

    state = _draft_states.get(lb.lobby_id)
    if not state:
        raise HTTPException(status_code=409, detail="No active draft in this lobby")
    if pid not in state["player_ids"]:
        raise HTTPException(status_code=403, detail="Not a draft participant")

    phase = state["phase"]
    vote = request.vote

    if phase == "monsters":
        if not isinstance(vote, list):
            raise HTTPException(status_code=400, detail="Monster vote must be a list of area names")
        valid_areas = set(state["monster_areas"].keys())
        validated = [a for a in vote if a in valid_areas][:5]
        state["votes_monsters"][pid] = validated
    elif phase == "starters":
        try:
            sid = int(vote)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Starter vote must be a starter id (integer)")
        available_ids = {int(r["id_starters"]) for r in state.get("starter_candidates", [])}
        if sid not in available_ids:
            raise HTTPException(status_code=400, detail="Invalid starter choice")
        state.setdefault("votes_starters", {})[pid] = sid
    elif phase == "citizens":
        try:
            cid = int(vote)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Citizen vote must be a citizen id (integer)")
        current_roll = state.get("current_roll")
        if current_roll is None:
            raise HTTPException(status_code=409, detail="No citizen round active")
        available_ids = {int(r["id_citizens"]) for r in state["citizens_by_roll"].get(current_roll, [])}
        if cid not in available_ids:
            raise HTTPException(status_code=400, detail="Invalid citizen choice")
        state["votes_citizens"][pid] = cid
    else:
        raise HTTPException(status_code=409, detail="Draft is not in an active voting phase")

    n_players = len(state["player_ids"])
    if phase == "monsters" and len(state["votes_monsters"]) >= n_players:
        await _advance_draft(lb.lobby_id)
    elif phase == "starters" and len(state.get("votes_starters", {})) >= n_players:
        await _advance_draft(lb.lobby_id)
    elif phase == "citizens" and len(state["votes_citizens"]) >= n_players:
        await _advance_draft(lb.lobby_id)
    else:
        await lobby_ws_manager.broadcast_lobby()

    return {"message": "Vote submitted"}


@app.get("/api/lobby/background-cards")
async def lobby_background_cards():
    """Inclusive id ranges per card type for the lobby background canvas.

    The client builds `/card-image/{type}/{id}` URLs from these ranges and
    skips ids with no art on disk, so this only needs to bound each type.
    """
    return JSONResponse({"ranges": _LOBBY_BG_CARD_RANGES})


@app.websocket("/ws/lobby")
async def ws_lobby(websocket: WebSocket):
    await lobby_ws_manager.connect(websocket)
    await lobby_ws_manager.send_snapshot(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "identify":
                lobby_ws_manager.identify(websocket, data.get("player_id"))
                await lobby_ws_manager.send_snapshot(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        lobby_ws_manager.disconnect(websocket)


# Game endpoints
def _serialize_game_for_player(game, viewer_player_id: Optional[str]):
    """
    Serialize the game state for a given viewer.

    Security/hidden-info rule:
    - Dukes are hidden information. Only the viewing player should see their own duke.
    - For opponents we still emit ONE stub per duke they own (with no
      identifying fields beyond the type) so the client can render a duke
      card back in their tableau without leaking the actual duke. The stub
      carries `is_visible: false` + `duke_id: 0` so `cardObscuredFromViewer`
      kicks in and `obscuredTypeBackUrl` picks the duke back image.
    """
    game_json = json.dumps(game, cls=GameObjectEncoder, indent=2)
    state = json.loads(game_json)

    # Surface the hurry-up clock as seconds remaining (server's clock at
    # serialization time). The client converts to a local Date.now() deadline
    # on receipt; subsequent polls re-sync to the latest server view so
    # the countdown stays smooth even when WS pushes drop. `null` means no
    # timer is armed (e.g., not action phase, mid-prompt, concurrent gate).
    deadline = float(getattr(game, "hurry_up_deadline", 0.0) or 0.0)
    if deadline > 0.0 and _hurry_up_should_run(game):
        remaining = max(0.0, deadline - time.time())
        state["hurry_up_seconds_remaining"] = round(remaining, 2)
        state["hurry_up_total_seconds"] = HURRY_UP_SECONDS
    else:
        state["hurry_up_seconds_remaining"] = None
        state["hurry_up_total_seconds"] = HURRY_UP_SECONDS

    # Bake "rest of the game" global cost modifiers (Blessed Lands, Dark Lord
    # Rising) into the serialized board so the client's existing card-derived
    # cost math stays consistent. These apply uniformly to all players, so it
    # is safe to fold them into the shared wire copy. Server-side validation
    # applies the same modifiers independently via per-player granted flags.
    try:
        domain_discount = game.events.blessed_lands_discount()
        monster_surcharge = game.events.dark_lord_surcharge()
    except Exception:
        domain_discount = 0
        monster_surcharge = 0
    if domain_discount:
        for stack in (state.get("domain_grid") or []):
            if not isinstance(stack, list) or not stack:
                continue
            top = stack[-1]
            if isinstance(top, dict) and top.get("is_accessible"):
                base = int(top.get("gold_cost", 0) or 0)
                top["gold_cost"] = max(0, base - domain_discount)
    if monster_surcharge:
        for stack in (state.get("monster_grid") or []):
            if not isinstance(stack, list) or not stack:
                continue
            top = stack[-1]
            if not isinstance(top, dict) or not top.get("is_accessible"):
                continue
            if top.get("monster_id") is None and top.get("event_id") is None:
                continue
            top["extra_magic_cost"] = int(top.get("extra_magic_cost", 0) or 0) + monster_surcharge

    viewer_player = None
    if viewer_player_id is not None:
        for pl in game.player_list:
            if str(pl.player_id) == str(viewer_player_id):
                viewer_player = pl
                break
    if viewer_player is not None:
        def _apply_monster_scaling_cost_to_top(top):
            if not isinstance(top, dict) or not top.get("is_accessible"):
                return
            if top.get("monster_id") is None and top.get("event_id") is None:
                return
            if not top.get("has_special_cost"):
                return
            sc = top.get("special_cost")
            if not sc or not str(sc).strip():
                return
            deltas = game._monster_special_cost_deltas(viewer_player, sc)
            if deltas.get("s"):
                top["extra_strength_cost"] = int(top.get("extra_strength_cost", 0) or 0) + int(deltas["s"])
            if deltas.get("m"):
                top["extra_magic_cost"] = int(top.get("extra_magic_cost", 0) or 0) + int(deltas["m"])
            if deltas.get("g"):
                top["extra_gold_cost"] = int(top.get("extra_gold_cost", 0) or 0) + int(deltas["g"])

        for grid_key in ("monster_grid", "citizen_grid", "domain_grid"):
            for stack in (state.get(grid_key) or []):
                if not isinstance(stack, list) or not stack:
                    continue
                _apply_monster_scaling_cost_to_top(stack[-1])

    players = state.get("player_list") or []
    if not isinstance(players, list):
        return state

    for p in players:
        if not isinstance(p, dict):
            continue
        pid = p.get("player_id")
        # Per-player projection of every catalog duke's VP against this player's
        # tableau. Safe for all viewers: it's computed identically for every
        # duke, so it never reveals which one the player actually owns. Drives
        # the "list all dukes" view when inspecting an opponent's hidden duke.
        try:
            p["duke_vp_table"] = game.endgame.compute_duke_vp_table_for_player(pid)
        except Exception:
            p["duke_vp_table"] = []
        if viewer_player_id is None or str(pid) != str(viewer_player_id):
            opponent_dukes = p.get("owned_dukes") or []
            p["owned_dukes"] = [
                {
                    "duke_id": 0,
                    "name": "",
                    "is_visible": False,
                    "is_accessible": False,
                }
                for _ in opponent_dukes
            ]
        else:
            # Attach a real-time end-game VP projection for the viewer so the
            # duke inspect modal can show a live "if the game ended now" tally.
            try:
                projection = game.endgame.compute_duke_projection_for_player(pid)
            except Exception:
                projection = None
            if projection is not None:
                p["duke_vp_projection"] = projection

    return state


def _player_name_from_game_state(game, player_id: str) -> str:
    for p in getattr(game, "player_list", []) or []:
        if getattr(p, "player_id", None) == player_id:
            return getattr(p, "name", "") or "Player"
    for g in gamers:
        if g.player_id == player_id and g.game_id == getattr(game, "game_id", None):
            return getattr(g, "name", "") or "Player"
    return "Player"


async def _initiate_game_shutdown(game_id: str, reason: str, initiated_by_player_id: Optional[str] = None):
    """
    Start a 30s shutdown countdown for the game.

    - Broadcasts `state.shutdown` to all connected game clients.
    - Removes all `gamers` entries for the game so lobby won't auto-redirect people back in.
    - Destroys the game after the delay.
    """
    game = games.get(game_id)
    if not game:
        return

    # Idempotent: only start once.
    if getattr(game, "shutdown", None):
        return

    now = time.time()
    initiator = None
    if initiated_by_player_id:
        initiator = {
            "player_id": initiated_by_player_id,
            "name": _player_name_from_game_state(game, initiated_by_player_id),
        }

    game.shutdown = {
        "reason": str(reason or "ended"),
        "started_at": now,
        "redirect_at": now + float(_GAME_SHUTDOWN_DELAY_S),
        "initiated_by": initiator,
    }

    # Ensure lobby doesn't bounce players back into a game that is ending.
    global gamers
    gamers = [g for g in gamers if g.game_id != game_id]
    await lobby_ws_manager.broadcast_lobby()

    # Push state update immediately.
    _hurry_up_cancel(game_id)
    if hasattr(game, "hurry_up_deadline"):
        game.hurry_up_deadline = 0.0
    await manager.broadcast(game_id, game)

    async def _destroy_later():
        await asyncio.sleep(_GAME_SHUTDOWN_DELAY_S)
        # Only destroy if still the same game object and still marked shutdown.
        g = games.get(game_id)
        if not g:
            return
        if not getattr(g, "shutdown", None):
            return
        games.pop(game_id, None)
        game_histories.pop(game_id, None)
        _hurry_up_cancel(game_id)
        # Just in case anything re-added entries.
        global gamers
        gamers = [gm for gm in gamers if gm.game_id != game_id]
        await lobby_ws_manager.broadcast_lobby()

    asyncio.create_task(_destroy_later())


def game_not_found_json():
    """404 body for missing games so the client can clear a stale stored game_id."""
    return JSONResponse(
        status_code=404,
        content={"detail": "Game not found", "drop_stored_game": True},
    )


@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str, player_id: Optional[str] = None):
    """Get the current game state"""
    game = games.get(game_id)
    if not game:
        return game_not_found_json()
    
    game.last_active_time = time.time()
    # Ensure the beginning-of-turn roll/harvest are automatic (including the very first fetch).
    try:
        while getattr(game, "phase", None) in ("roll", "harvest"):
            if not game.advance_tick():
                break
            if getattr(game, "phase", None) == "action":
                break
    except Exception as e:
        message = f"State advance failed: {str(e)}"
        return JSONResponse(
            status_code=500,
            content={"detail": message, "error": message},
        )
    # If the engine already ended the game, kick off the shutdown countdown.
    if getattr(game, "phase", None) == "game_over" and not getattr(game, "shutdown", None):
        await _initiate_game_shutdown(game_id, reason="game_over", initiated_by_player_id=None)
    # Polls are deliberately a no-op against an already-armed deadline so that
    # the client's state-poll safety net cannot push back the hurry-up clock.
    _hurry_up_ensure(game_id)
    return _serialize_game_for_player(game, player_id)


@app.post("/api/game/{game_id}/action")
async def perform_game_action(game_id: str, request: GameActionRequest):
    """Perform a game action (hire citizen, build domain, slay monster, etc.)"""
    game = games.get(game_id)
    if not game:
        return game_not_found_json()
    
    game.last_active_time = time.time()

    # Snapshots back the dev "Back one step" button. We only record snapshots
    # for action-phase player actions (take resource / hire / build / slay).
    # Harvests, required-action prompt resolutions, concurrent submissions,
    # rolls, rerolls, and engine-driven phase advances are not snapshotable so
    # a single "back" step undoes one real action and not half of a harvest or
    # one button-press inside a multi-step prompt.
    should_snapshot = False

    try:
        if request.action_type == "hire_citizen":
            if request.citizen_id is None:
                raise HTTPException(status_code=400, detail="citizen_id required")
            if request.payment is None and request.gold_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or gold_cost/magic_cost required")
            if not game.consume_player_action(request.player_id, action_type="hire_citizen"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            redeemed = None
            try:
                redeemed = _redeem_payment_tomes(game, request, g, s, m)
                game.hire_citizen(request.player_id, request.citizen_id, g, m, s)
            except ValueError as e:
                if redeemed:
                    game.refund_tomes_from_score(request.player_id, redeemed)
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                if redeemed:
                    game.refund_tomes_from_score(request.player_id, redeemed)
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()
            should_snapshot = True

        elif request.action_type == "build_domain":
            if request.domain_id is None:
                raise HTTPException(status_code=400, detail="domain_id required")
            if request.payment is None and request.gold_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or gold_cost/magic_cost required")
            if not game.consume_player_action(request.player_id, action_type="build_domain"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            redeemed = None
            try:
                redeemed = _redeem_payment_tomes(game, request, g, s, m)
                game.build_domain(request.player_id, request.domain_id, g, m, s)
            except ValueError as e:
                if redeemed:
                    game.refund_tomes_from_score(request.player_id, redeemed)
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                if redeemed:
                    game.refund_tomes_from_score(request.player_id, redeemed)
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()
            should_snapshot = True

        elif request.action_type == "slay_monster":
            if request.monster_id is None and request.event_id is None:
                raise HTTPException(status_code=400, detail="monster_id or event_id required")
            if request.payment is None and request.strength_cost is None and request.magic_cost is None:
                raise HTTPException(status_code=400, detail="payment or strength_cost/magic_cost required")
            if not game.consume_player_action(request.player_id, action_type="slay_monster"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, s, m = resolve_action_payment(request)
            redeemed = None
            try:
                redeemed = _redeem_payment_tomes(game, request, g, s, m)
                game.slay_monster(
                    request.player_id,
                    request.monster_id,
                    s, m, g,
                    event_id=request.event_id,
                )
            except ValueError as e:
                if redeemed:
                    game.refund_tomes_from_score(request.player_id, redeemed)
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                if redeemed:
                    game.refund_tomes_from_score(request.player_id, redeemed)
                _rollback_consumed_action(game)
                raise
            game.finish_turn_if_no_actions_remaining()
            should_snapshot = True
        
        elif request.action_type == "take_resource":
            if request.resource is None or not str(request.resource).strip():
                raise HTTPException(status_code=400, detail='resource required ("gold", "strength", "magic", or "map")')
            r = str(request.resource).strip().lower()
            if r not in ("gold", "strength", "magic", "map"):
                raise HTTPException(status_code=400, detail='resource must be "gold", "strength", "magic", or "map"')
            if not game.consume_player_action(request.player_id, action_type="take_resource"):
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
            should_snapshot = True

        elif request.action_type == "buy_goods":
            if not request.slot_indices:
                raise HTTPException(status_code=400, detail="slot_indices required")
            if not game.consume_player_action(request.player_id, action_type="buy_goods"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, _s, m = resolve_action_payment(request)
            try:
                game.buy_goods(request.player_id, list(request.slot_indices), g, m,
                               tome_payment=resolve_tome_payment(request))
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            if not game.resolve_bonus_sail_if_consumed():
                game.finish_turn_if_no_actions_remaining()
            should_snapshot = True

        elif request.action_type == "buy_tomes":
            if not request.slot_indices:
                raise HTTPException(status_code=400, detail="slot_indices required")
            if not game.consume_player_action(request.player_id, action_type="buy_tomes"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            g, _s, m = resolve_action_payment(request)
            try:
                game.buy_tomes(request.player_id, list(request.slot_indices), g, m,
                               tome_payment=resolve_tome_payment(request))
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            if not game.resolve_bonus_sail_if_consumed():
                game.finish_turn_if_no_actions_remaining()
            should_snapshot = True

        elif request.action_type == "sail_exekratys":
            if request.resource is None or not str(request.resource).strip():
                raise HTTPException(status_code=400, detail='resource required ("gold", "strength", or "magic")')
            r = str(request.resource).strip().lower()
            if r not in ("gold", "strength", "magic"):
                raise HTTPException(status_code=400, detail='resource must be "gold", "strength", or "magic"')
            if not game.consume_player_action(request.player_id, action_type="sail_exekratys"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            try:
                game.sail_exekratys(request.player_id, r)
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            if not game.resolve_bonus_sail_if_consumed():
                game.finish_turn_if_no_actions_remaining()
            should_snapshot = True

        elif request.action_type == "rescue_noble":
            if request.slot_index is None:
                raise HTTPException(status_code=400, detail="slot_index required")
            if request.resource is None or not str(request.resource).strip():
                raise HTTPException(status_code=400, detail='resource required ("gold", "strength", or "magic")')
            r = str(request.resource).strip().lower()
            if r not in ("gold", "strength", "magic"):
                raise HTTPException(status_code=400, detail='resource must be "gold", "strength", or "magic"')
            if not game.consume_player_action(request.player_id, action_type="rescue_noble"):
                raise HTTPException(status_code=400, detail="Not your turn (or no actions remaining)")
            try:
                game.rescue_noble(request.player_id, int(request.slot_index), r, tome_payment=resolve_tome_payment(request))
            except ValueError as e:
                _rollback_consumed_action(game)
                raise HTTPException(status_code=400, detail=str(e))
            except Exception:
                _rollback_consumed_action(game)
                raise
            if not game.resolve_bonus_sail_if_consumed():
                game.finish_turn_if_no_actions_remaining()
            should_snapshot = True

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
        
        elif request.action_type == "reroll_pending_die":
            try:
                game.reroll_pending_die(request.player_id, request.die_one or 1)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        elif request.action_type == "reroll_both_dice":
            try:
                game.reroll_both_dice(request.player_id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        elif request.action_type == "roll_phase":
            raise HTTPException(status_code=400, detail="roll_phase is automatic")
        
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

        if should_snapshot:
            _record_snapshot(game_id, game)
        # Real player input occurred; (re)arm the hurry-up clock for whoever
        # the engine is now waiting on -- including the same player's next
        # action in a 2-action turn, or the next seat after a turn end.
        _hurry_up_reset(game_id)
        # Push updated state to all WebSocket subscribers for this game.
        await manager.broadcast(game_id, game)
        # If this action ended the game, start the countdown once.
        if getattr(game, "phase", None) == "game_over" and not getattr(game, "shutdown", None):
            await _initiate_game_shutdown(game_id, reason="game_over", initiated_by_player_id=None)
        return {"message": "Action performed", "game_state": _serialize_game_for_player(game, request.player_id)}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Action failed: {str(e)}")


class ApplyEventSlayCostRequest(BaseModel):
    player_id: str
    monster_id: Optional[int] = None
    event_id: Optional[int] = None


@app.post("/api/game/{game_id}/apply_event_slay_cost")
async def apply_event_slay_cost(game_id: str, request: ApplyEventSlayCostRequest):
    """Resolve the pending event slay-cost choice (add extra cost to a chosen monster)."""
    game = games.get(game_id)
    if not game:
        return game_not_found_json()
    if request.monster_id is None and request.event_id is None:
        raise HTTPException(status_code=400, detail="monster_id or event_id required")
    try:
        game.apply_event_slay_cost(
            request.player_id,
            monster_id=request.monster_id,
            event_id=request.event_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    while game.advance_tick():
        pass
    # Event-slay-cost is a pre-slay payment, not one of the three real
    # player actions, so it does not record a snapshot. The follow-up
    # slay_monster call will be the snapshot anchor.
    _hurry_up_reset(game_id)
    await manager.broadcast(game_id, game)
    return {"message": "Event slay cost applied", "game_state": _serialize_game_for_player(game, request.player_id)}


@app.get("/api/game/{game_id}/history")
async def get_game_history(game_id: str):
    """Return one breadcrumb per recorded snapshot for this game.

    The current live state is the LAST entry. Steps farther from the end
    are older. Indexes are 0-based and stable for the duration of the
    response (history may grow before the next call but won't reorder).
    """
    game = games.get(game_id)
    if not game:
        return game_not_found_json()
    history = game_histories.get(game_id) or deque()
    entries = [
        {"index": i, **_history_breadcrumb(snap)}
        for i, snap in enumerate(history)
    ]
    return {
        "game_id": game_id,
        "history": entries,
        "current_index": len(entries) - 1 if entries else -1,
        "max_len": _GAME_HISTORY_MAX_LEN,
        "can_step_back": len(entries) > 1,
    }


@app.post("/api/game/{game_id}/back")
async def step_game_back(game_id: str):
    """Pop the most recent snapshot and rehydrate the game from the new tail.

    Dev tool only. Intended for the dev client's "Back one step" button:
    walks the in-memory snapshot ring backward one entry. The current live
    state is dropped and replaced with the previous snapshot's rehydrated
    `Game`. WebSocket sessions are kept alive (they're keyed by `game_id`,
    not the Game object) and immediately get a fresh state broadcast.
    """
    game = games.get(game_id)
    if not game:
        return game_not_found_json()

    history = game_histories.get(game_id)
    if not history or len(history) < 2:
        raise HTTPException(status_code=400, detail="No earlier snapshot to step back to.")

    history.pop()
    target_snap = history[-1]
    try:
        rebuilt = deserialize_save_dict_to_game(target_snap)
    except Exception as exc:
        # Re-push the popped snapshot so the user isn't worse off than before.
        # This shouldn't happen given the round-trip tests, but be safe.
        history.append(target_snap)
        raise HTTPException(status_code=500, detail=f"Failed to restore snapshot: {exc}")

    rebuilt.last_active_time = time.time()
    games[game_id] = rebuilt

    _hurry_up_reset(game_id)
    await manager.broadcast(game_id, rebuilt)
    return {
        "message": "Stepped back",
        "game_id": game_id,
        "current_index": len(history) - 1,
        "history_length": len(history),
    }


@app.post("/api/game/{game_id}/abandon")
async def abandon_game(game_id: str, request: AbandonGameRequest):
    """Abandon a game. Ends the game for everyone, then destroys it after 30s."""
    game = games.get(game_id)
    if not game:
        return game_not_found_json()
    pid = str(request.player_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="player_id required")
    in_game = any(getattr(p, "player_id", None) == pid for p in getattr(game, "player_list", []) or [])
    if not in_game:
        raise HTTPException(status_code=403, detail="player not in this game")
    await _initiate_game_shutdown(game_id, reason="abandoned", initiated_by_player_id=pid)
    return {"message": "Game abandoned", "game_id": game_id}


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
                game_histories.pop(game_id, None)
                _hurry_up_cancel(game_id)
                # Remove gamers from this game
                global gamers
                gamers = [g for g in gamers if g.game_id != game_id]
    
    asyncio.create_task(cleanup())


# ── Card image lookup ────────────────────────────────────────────────────────
# A variant token is the filename segment that precedes the canonical
# ``<card_type>_<id>_`` core. ``alt`` (legacy single alternate,
# ``alt_<type>_<id>_*``) and ``alt_01`` .. ``alt_NN`` (numbered alternates,
# ``alt_NN_<type>_<id>_*``) are both supported. Restricting the token keeps
# the value safe to splice into a filename prefix (no path traversal).
_VARIANT_TOKEN_RE = re.compile(r"^[a-z0-9_]+$")


@app.get("/card-image/{card_type}/{card_id}")
async def card_image(card_type: str, card_id: int, variant: Optional[str] = None):
    """Return the card image matched by type + numeric ID prefix.

    Pass ``?variant=<token>`` (e.g. ``alt`` or ``alt_01``) to return an
    alternate artwork file (``<token>_<card_type>_<id>_*``) instead of the
    canonical one. Unknown/invalid variants fall through to a 404 so callers
    can fall back to the canonical image.
    """
    if card_type == "exhausted":
        if _EXHAUSTED_CARD_JPEG.is_file():
            return FileResponse(str(_EXHAUSTED_CARD_JPEG), media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="Exhausted card image not found")
    dir_path = _CARD_IMAGE_DIRS.get(card_type)
    if not dir_path or not dir_path.exists():
        raise HTTPException(status_code=404, detail="Unknown card type")
    if variant and _VARIANT_TOKEN_RE.match(variant):
        prefix = f"{variant}_{card_type}_{card_id:02d}_"
    else:
        prefix = f"{card_type}_{card_id:02d}_"
    for f in sorted(dir_path.iterdir()):
        if f.name.startswith(prefix) and f.suffix.lower() in _IMAGE_EXTS:
            return FileResponse(str(f), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Image not found")


@app.get("/card-image-variants")
async def card_image_variants_all():
    """Map every card that has alternate artwork to its variant tokens.

    Shape: ``{ "<card_type>": { "<card_id>": ["alt_01", ...] } }``. The game
    client fetches this once so it knows which cards to show an "Alt" control
    on, without probing the per-card endpoint for everything on the board.
    """
    from card_filters import all_card_image_variants
    return all_card_image_variants()


@app.get("/card-image-variants/{card_type}/{card_id}")
async def card_image_variants(card_type: str, card_id: int):
    """List the alternate-artwork variant tokens available for a card.

    Used by the game client to offer artwork choices (e.g. the Margrave
    starter) without hard-coding how many alternates exist on disk.
    """
    if card_type not in _CARD_IMAGE_DIRS:
        raise HTTPException(status_code=404, detail="Unknown card type")
    from card_filters import list_card_image_variants
    return {"variants": list_card_image_variants(card_type, card_id)}


# Serve static files and simple HTML client
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.mount("/images", StaticFiles(directory=str(_REPO_ROOT / "images")), name="images")
except Exception:
    pass  # static / images directory might not exist


@app.websocket("/ws/game/{game_id}")
async def ws_game(websocket: WebSocket, game_id: str, player_id: Optional[str] = None):
    game = games.get(game_id)
    if not game:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "code": 4004,
                "message": "Game not found",
                "drop_stored_game": True,
            }
        )
        await websocket.close(code=4004)
        return
    await manager.connect(game_id, websocket, player_id)
    try:
        await websocket.send_json({"type": "state", "state": _serialize_game_for_player(game, player_id)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(game_id, websocket)


@app.get("/")
async def game_client():
    return FileResponse(_GAME_CLIENT_INDEX, media_type="text/html")


@app.get("/debug")
async def debug_client():
    return FileResponse(_DEV_CLIENT_INDEX, media_type="text/html")


@app.get("/counter")
async def counter_client():
    return FileResponse(_COUNTER_INDEX, media_type="text/html")


@app.get("/wiki")
async def wiki_client():
    return FileResponse(_WIKI_INDEX, media_type="text/html")


@app.get("/api/wiki/cards")
async def wiki_cards(refresh: bool = False):
    """Return every row of every card table, grouped by type.

    The result is cached in-memory for the life of the server process.
    Pass `?refresh=1` to force a reload (useful while editing rows in the
    DB without restarting the server).
    """
    global _wiki_cards_cache
    if _wiki_cards_cache is None or refresh:
        try:
            from wiki_data import load_all_cards_for_wiki
            _wiki_cards_cache = load_all_cards_for_wiki()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to load card data from database: {exc}",
            )
    return _wiki_cards_cache


@app.get("/api/wiki/rulebooks")
async def wiki_rulebooks():
    """List rulebook PDFs and standalone rule cards for the wiki Rulebooks tab.

    Both are scanned live on each request (a handful of files, changes rarely)
    so a dropped-in file appears without a server restart.

    - `rulebooks`: PDFs under `static/rulebooks/`; each has a display `name`
      (filename without `.pdf`) and a static `url`.
    - `rule_cards`: front/back image pairs under `static/rulebooks/` named
      `rule_card_<front|back>_<slug>.<ext>`, grouped by `<slug>`. Each has a
      `name` (slug, underscores → spaces, title-cased), `slug`, and
      `front_url` / `back_url` (either may be null if only one side exists).
    """
    books = []
    pairs = {}
    if _RULEBOOKS_DIR.is_dir():
        for f in sorted(_RULEBOOKS_DIR.iterdir()):
            if not f.is_file():
                continue
            m = _RULE_CARD_RE.match(f.name)
            if m:
                side, slug = m.group(1).lower(), m.group(2)
                url = "/static/rulebooks/" + urllib.parse.quote(f.name)
                pairs.setdefault(slug, {})[side] = url
            elif f.suffix.lower() == ".pdf":
                url = "/static/rulebooks/" + urllib.parse.quote(f.name)
                books.append({"name": f.stem, "url": url})

    rule_cards = []
    for slug in sorted(pairs):
        sides = pairs[slug]
        rule_cards.append({
            "name": slug.replace("_", " ").title(),
            "slug": slug,
            "front_url": sides.get("front"),
            "back_url": sides.get("back"),
        })

    return {"rulebooks": books, "rule_cards": rule_cards}


# In-memory cache of preset previews. Card data is static between server
# restarts, so each (preset, expansion_only, players, duke_select_count)
# combination is computed once and reused.
_preset_preview_cache: Dict[tuple, dict] = {}


@app.get("/api/lobby/preset-preview")
async def lobby_preset_preview(
    preset: str,
    expansion_only: bool = False,
    players: int = 4,
    duke_select_count: int = 2,
):
    """Return every card a preset can put in play (deterministic + random pool).

    Powers the lobby's "preview this set" modal. Read-only; does not touch any
    lobby or game state.
    """
    p = _validate_preset(preset)
    eo = bool(expansion_only) and p in _PRESETS_WITH_EXPANSION_ONLY
    try:
        players = max(_MIN_PLAYERS_FLOOR, min(_MIN_PLAYERS_CEIL, int(players)))
    except (TypeError, ValueError):
        players = 4
    dsc = duke_select_count if duke_select_count in (2, 3) else 2
    cache_key = (p, eo, players, dsc)
    if cache_key not in _preset_preview_cache:
        try:
            from preset_preview import load_preset_preview
            _preset_preview_cache[cache_key] = load_preset_preview(
                p, expansion_only=eo, players=players, duke_select_count=dsc
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to build preset preview from database: {exc}",
            )
    return _preset_preview_cache[cache_key]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
