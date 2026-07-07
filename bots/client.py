"""HTTP client for the hosted VCK Online API."""

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://vcko.lukesau.com"


class VckoApiError(Exception):
    def __init__(self, status, detail, payload=None):
        self.status = status
        self.detail = detail
        self.payload = payload or {}
        super().__init__(detail)


class IllegalActionError(VckoApiError):
    pass


class VckoClient:
    def __init__(self, base_url=DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def _request(self, method, path, body=None, params=None):
        url = self.base_url + path
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if qs:
                url = url + ("&" if "?" in url else "?") + qs
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"detail": raw or e.reason}
            detail = payload.get("detail", e.reason)
            if isinstance(detail, list):
                detail = json.dumps(detail)
            err_cls = IllegalActionError if e.code == 400 else VckoApiError
            raise err_cls(e.code, str(detail), payload) from e

    def create_lobby(self, name, preset="base", min_players=2):
        payload = self._request("POST", "/api/lobby/create", {
            "name": name,
            "preset": preset,
            "min_players": min_players,
        })
        return payload["player_id"], payload["lobby_id"]

    def join_lobby(self, name, lobby_id, player_id=None):
        body = {"name": name, "lobby_id": lobby_id}
        if player_id:
            body["player_id"] = player_id
        payload = self._request("POST", "/api/lobby/join", body)
        return payload["player_id"], payload["lobby_id"]

    def ready(self, player_id, debug_mode=False):
        payload = self._request("POST", "/api/lobby/ready", {
            "player_id": player_id,
            "debug_mode": debug_mode,
        })
        return payload.get("game_id")

    def lobby_status(self, player_id=None):
        params = {}
        if player_id:
            params["player_id"] = player_id
        return self._request("GET", "/api/lobby/status", params=params)

    def get_state(self, game_id, player_id):
        return self._request(
            "GET",
            f"/api/game/{urllib.parse.quote(str(game_id))}/state",
            params={"player_id": player_id},
        )

    def post_action(self, game_id, body):
        payload = self._request(
            "POST",
            f"/api/game/{urllib.parse.quote(str(game_id))}/action",
            body,
        )
        return payload.get("game_state") or payload

    def apply_event_slay_cost(self, game_id, body):
        payload = self._request(
            "POST",
            f"/api/game/{urllib.parse.quote(str(game_id))}/apply_event_slay_cost",
            body,
        )
        return payload.get("game_state") or payload

    def execute_move(self, game_id, move):
        """POST a move dict from legal_moves.enumerate_actions."""
        route = move.get("_route", "action")
        body = {k: v for k, v in move.items() if not k.startswith("_")}
        if route == "apply_event_slay_cost":
            return self.apply_event_slay_cost(game_id, body)
        return self.post_action(game_id, body)
