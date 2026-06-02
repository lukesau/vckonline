# ---------------------------------------------------------------------------
# Concurrent (non-ordered) action subsystem.
#
# A "concurrent action" is a gate where many players must each submit a
# response before the game can advance, but their submissions are unordered
# (any participant may respond at any time). This is intentionally separate
# from the per-player `action_required` field, which is used for sequential,
# turn-based prompts (e.g. action phase, manual harvest).
#
# To add a new kind, register a handler in CONCURRENT_HANDLERS. The handler
# implements:
#
#   apply(game, player_id, response)
#       Validate + apply this player's response. Raise ValueError on bad
#       input. The response payload is opaque to the engine (handler-defined).
#
#   finalize(game)
#       Optional. Runs once after every participant has submitted. Use this
#       for any cross-player resolution that has to happen after all
#       responses are in. Side-effects on individual players that don't
#       depend on others should generally happen in apply().
#
# The engine itself only knows: "while there's a concurrent_action with
# pending players, do not advance".
# ---------------------------------------------------------------------------


class _ChooseDukeConcurrentHandler:
    """Each player keeps exactly one of their dealt dukes."""

    def apply(self, game, player_id, response):
        try:
            chosen_id = int(str(response).strip())
        except Exception:
            raise ValueError("Invalid duke selection.")
        for p in game.player_list:
            if p.player_id != player_id:
                continue
            dukes = list(getattr(p, "owned_dukes", []) or [])
            if not dukes:
                raise ValueError("No dukes to choose from.")
            chosen = None
            for d in dukes:
                if int(getattr(d, "duke_id", -1)) == chosen_id:
                    chosen = d
                    break
            if chosen is None:
                raise ValueError("Selected duke not found.")
            p.owned_dukes = [chosen]
            ca = getattr(game, "concurrent_action", None) or {}
            ca.setdefault("responses", {})[player_id] = response
            pending = ca.get("pending") or []
            if player_id in pending:
                ca["pending"] = [pid for pid in pending if pid != player_id]
            ca.setdefault("completed", [])
            if player_id not in ca["completed"]:
                ca["completed"].append(player_id)
            return
        raise ValueError("Player not found.")

    def finalize(self, game):
        return


def _mark_concurrent_player_done(game, player_id, response):
    """Shared bookkeeping: stash the response and move the player from pending to completed."""
    ca = getattr(game, "concurrent_action", None) or {}
    ca.setdefault("responses", {})[player_id] = response
    pending = ca.get("pending") or []
    if player_id in pending:
        ca["pending"] = [pid for pid in pending if pid != player_id]
    ca.setdefault("completed", [])
    if player_id not in ca["completed"]:
        ca["completed"].append(player_id)


class _FlipOneCitizenConcurrentHandler:
    """Each pending player chooses one unflipped citizen on their tableau to flip face-down.

    Used by both Cursed Cavern (domain) and "A Betrayal of Bonds" (event). The
    source label shown in the log is read from `concurrent_action.data.source_label`.
    """

    def apply(self, game, player_id, response):
        try:
            idx = int(str(response).strip())
        except (TypeError, ValueError):
            raise ValueError("Invalid citizen choice (send tableau index).")
        player = game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        oc = list(getattr(player, "owned_citizens", []) or [])
        if idx < 0 or idx >= len(oc):
            raise ValueError("Invalid citizen index.")
        cit = oc[idx]
        if getattr(cit, "is_flipped", False):
            raise ValueError("That citizen is already flipped.")
        game._citizen_set_flipped(cit, True)
        ca = getattr(game, "concurrent_action", None) or {}
        source_label = ((ca.get("data") or {}).get("source_label")) or "Cursed Cavern"
        game._log_game_event(
            f"{game._player_label(player_id)} flipped citizen \"{getattr(cit, 'name', '?')}\" face-down "
            f"({source_label})."
        )
        _mark_concurrent_player_done(game, player_id, response)

    def finalize(self, game):
        return


class _EventSelfConvertConcurrentHandler:
    """Each pending player may optionally pay a resource for a bank gain (e.g. event "Support The Empire").

    `concurrent_action.data` carries:
      name        -- event name (for logs)
      pay_kind    -- 'g'/'s'/'m'/'v' for a fixed cost, or 'wild' (player picks g/s/m)
      pay_amount  -- int
      gain_kind   -- 'g'/'s'/'m'/'v'
      gain_amount -- int

    Per-player response:
      'skip'                 -- decline
      'g' / 's' / 'm'        -- (wild only) which resource to pay
      'accept'               -- (fixed cost) pay the fixed resource
    """

    _SCORE = {"g": "gold_score", "s": "strength_score", "m": "magic_score", "v": "victory_score"}

    def apply(self, game, player_id, response):
        ca = getattr(game, "concurrent_action", None) or {}
        data = ca.get("data") or {}
        player = game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        resp = str(response).strip().lower()
        name = data.get("name", "Event")
        pay_kind = (data.get("pay_kind") or "").lower()
        pay_amount = int(data.get("pay_amount") or 0)
        gain_kind = (data.get("gain_kind") or "v").lower()
        gain_amount = int(data.get("gain_amount") or 0)
        if resp == "skip":
            game._log_game_event(
                f"{game._player_label(player_id)} declined event \"{name}\"."
            )
            _mark_concurrent_player_done(game, player_id, response)
            return
        if pay_kind == "wild":
            if resp not in ("g", "s", "m"):
                raise ValueError("Choose a resource to pay (g/s/m) or skip.")
            pay_res = resp
        else:
            if resp not in ("accept", pay_kind):
                raise ValueError("Send 'accept' to pay or 'skip' to decline.")
            pay_res = pay_kind
        if int(getattr(player, self._SCORE[pay_res], 0) or 0) < pay_amount:
            raise ValueError("You cannot afford this.")
        before = game._player_scores_line(player)
        setattr(player, self._SCORE[pay_res],
                int(getattr(player, self._SCORE[pay_res], 0)) - pay_amount)
        setattr(player, self._SCORE[gain_kind],
                int(getattr(player, self._SCORE[gain_kind], 0)) + gain_amount)
        after = game._player_scores_line(player)
        game._log_game_event(
            f"{game._player_label(player_id)} resolved event \"{name}\" "
            f"(paid {pay_amount}{pay_res}); scores {before} -> {after}"
        )
        _mark_concurrent_player_done(game, player_id, response)

    def finalize(self, game):
        return


class _EventBanishCitizenForRewardConcurrentHandler:
    """Each pending player may optionally banish one owned citizen (filtered by role)
    for a bank reward (e.g. event "A Call To Arms": banish a Soldier for 3 VP).

    `concurrent_action.data` carries:
      name        -- event name
      role        -- '' or one of shadow/holy/soldier/worker (role pip filter)
      gain_kind   -- 'g'/'s'/'m'/'v'
      gain_amount -- int

    Per-player response:
      'skip'      -- decline
      <int>       -- tableau index of the owned citizen to banish
    """

    _SCORE = {"g": "gold_score", "s": "strength_score", "m": "magic_score", "v": "victory_score"}
    _ROLE_ATTR = {"shadow": "shadow_count", "holy": "holy_count", "soldier": "soldier_count", "worker": "worker_count"}

    def apply(self, game, player_id, response):
        ca = getattr(game, "concurrent_action", None) or {}
        data = ca.get("data") or {}
        player = game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        name = data.get("name", "Event")
        role = (data.get("role") or "").lower()
        gain_kind = (data.get("gain_kind") or "v").lower()
        gain_amount = int(data.get("gain_amount") or 0)
        resp = str(response).strip().lower()
        if resp == "skip":
            game._log_game_event(
                f"{game._player_label(player_id)} declined event \"{name}\"."
            )
            _mark_concurrent_player_done(game, player_id, response)
            return
        try:
            idx = int(resp)
        except (TypeError, ValueError):
            raise ValueError("Send a tableau index to banish, or 'skip'.")
        oc = list(getattr(player, "owned_citizens", []) or [])
        if idx < 0 or idx >= len(oc):
            raise ValueError("Invalid citizen index.")
        cit = oc[idx]
        if getattr(cit, "is_flipped", False):
            raise ValueError("That citizen is flipped; choose a face-up citizen.")
        if role:
            attr = self._ROLE_ATTR.get(role)
            if not attr or int(getattr(cit, attr, 0) or 0) <= 0:
                raise ValueError(f"That citizen is not a {role.title()}.")
        player.owned_citizens.remove(cit)
        game.banish_pile.append(cit)
        before = game._player_scores_line(player)
        setattr(player, self._SCORE[gain_kind],
                int(getattr(player, self._SCORE[gain_kind], 0)) + gain_amount)
        after = game._player_scores_line(player)
        game._log_game_event(
            f"{game._player_label(player_id)} banished \"{getattr(cit, 'name', '?')}\" "
            f"for event \"{name}\"; scores {before} -> {after}"
        )
        _mark_concurrent_player_done(game, player_id, response)

    def finalize(self, game):
        return


class _HarvestChoicesConcurrentHandler:
    """Concurrent wrapper for non-steal harvest decisions.

    Each participant has its own snapshotted prompt payload stored in
    `concurrent_action.data.prompts[player_id]`.
    """

    def _apply_bonus_resource_choice(self, game, player_id, choice):
        choice = (choice or "").strip().lower()
        if choice not in ("gold", "strength", "magic"):
            raise ValueError("Invalid harvest bonus choice (send gold/strength/magic).")

        target = game._player_by_id(player_id)
        if not target:
            raise ValueError("Player not found.")

        before = game._player_scores_line(target)
        if choice == "gold":
            target.gold_score = int(target.gold_score) + 1
            target.harvest_delta["gold"] = int(target.harvest_delta.get("gold", 0)) + 1
        elif choice == "strength":
            target.strength_score = int(target.strength_score) + 1
            target.harvest_delta["strength"] = int(target.harvest_delta.get("strength", 0)) + 1
        else:
            target.magic_score = int(target.magic_score) + 1
            target.harvest_delta["magic"] = int(target.harvest_delta.get("magic", 0)) + 1

        after = game._player_scores_line(target)
        game._log_game_event(
            f"{game._player_label(player_id)} harvest bonus +1 {choice} (no gold/strength/magic spent); "
            f"scores {before} -> {after}"
        )

        # Concurrent mode doesn't rely on sequential pending_harvest_choices.
        if isinstance(getattr(game, "pending_harvest_choices", None), list):
            game.pending_harvest_choices = [
                pid for pid in game.pending_harvest_choices if pid != player_id
            ]

        # Clear the singular prompt fields; the concurrent wrapper owns the gate.
        game.action_required["id"] = game.game_id
        game.action_required["action"] = ""
        game.pending_required_choice = None

    def apply(self, game, player_id, response):
        ca = getattr(game, "concurrent_action", None) or {}
        prompts = ((ca.get("data") or {}).get("prompts") or {}) if isinstance(ca, dict) else {}
        prompt = prompts.get(player_id)
        if not prompt:
            raise ValueError("No pending harvest prompt for this player.")

        sub_kind = prompt.get("sub_kind")
        action = prompt.get("action") or ""
        pending_prc = prompt.get("pending_required_choice") or {}

        # Restore singular prompt state so we can reuse the existing resolvers.
        game.action_required["id"] = player_id
        game.action_required["action"] = action
        game.pending_required_choice = dict(pending_prc) if isinstance(pending_prc, dict) else None

        # Apply the player's response.
        if sub_kind in ("harvest_optional_exchange", "harvest_wild_gain_exchange", "harvest_wild_cost_exchange", "harvest_choose"):
            game.player_actions.act_on_required_action(player_id, response)
        elif sub_kind == "bonus_resource_choice":
            self._apply_bonus_resource_choice(game, player_id, response)
        else:
            raise ValueError(f"Unknown harvest sub_kind: {sub_kind!r}.")

        # Re-drain just this player's harvest pipeline to the next prompt.
        nxt = game.harvest._harvest_drain_player(player_id)

        ca.setdefault("responses", {})[player_id] = response
        ca.setdefault("completed", [])

        if nxt is None:
            # Player is fully done with this concurrent gate.
            prompts.pop(player_id, None)
            pending = ca.get("pending") or []
            if player_id in pending:
                ca["pending"] = [pid for pid in pending if pid != player_id]
            if player_id not in ca["completed"]:
                ca["completed"].append(player_id)
            return

        if isinstance(nxt, dict) and nxt.get("__unsupported_prompt_action"):
            raise ValueError(f"Concurrent harvest hit unsupported prompt: {nxt.get('__unsupported_prompt_action')!r}.")

        # Stay pending with a new prompt payload.
        prompts[player_id] = nxt
        ca.setdefault("data", {})
        ca["data"]["prompts"] = prompts

    def finalize(self, game):
        # If the last submitted player unlocked additional prompts for others,
        # reopen (or update) the concurrent gate.
        game.harvest._open_or_resume_harvest_concurrent()


CONCURRENT_HANDLERS = {
    "choose_duke": _ChooseDukeConcurrentHandler(),
    "flip_one_citizen": _FlipOneCitizenConcurrentHandler(),
    "harvest_choices": _HarvestChoicesConcurrentHandler(),
    "event_self_convert": _EventSelfConvertConcurrentHandler(),
    "event_banish_citizen_for_reward": _EventBanishCitizenForRewardConcurrentHandler(),
}


def _new_concurrent_action(kind, participant_ids, data=None):
    """Build a concurrent_action dict for the given kind + participants."""
    if kind not in CONCURRENT_HANDLERS:
        raise ValueError(f"Unknown concurrent action kind: {kind}")
    pids = [pid for pid in participant_ids if pid]
    return {
        "kind": kind,
        "pending": list(pids),
        "completed": [],
        "responses": {},
        "data": dict(data or {}),
    }
