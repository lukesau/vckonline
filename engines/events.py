"""EventsEngine -- composed sub-engine of Game.

Owns activation / passive effects for non-monster Event cards. Monster events
(``is_monster`` truthy) keep their existing behavior: they sit on the board to
be slain and fire ``roll_effect`` on matching rolls (see ``DiceEngine``). This
engine only handles the ``activation_effect`` / ``passive_effect`` strings used
by expansion events (kingsguard / undeadsamurai / shadowvale / flamesandfrost).

Lifecycle of a non-monster event:

- It is flipped off the Exhausted stack onto a board stack when that stack
  empties (slay / hire / build / banish / free-take / harvest payout). All of
  those paths route through ``reveal_exhausted_onto_stack``.
- On reveal, an ``activation_effect`` fires once; a ``passive_effect`` becomes
  "in play" and is scanned for as long as the card sits on a board stack.
- A revealed non-monster event becomes a face-up but non-accessible card (it is
  not slayable). It still occupies the slot like an exhausted token, so if a
  later effect returns a card to that center stack the event un-exhausts back
  into the deck (see ``_unexhaust_stack_top_if_present``) and can be re-revealed
  and re-fire later in the game.

Activation effects reuse the same mechanics as domains where possible
(self_convert bank trades, concurrent flip, banish-for-reward, all_lose).

Effect-string grammar (stored in ``events.activation_effect`` /
``events.passive_effect``):

  active_may gain_action pay=m:3                       (active player may pay 3m for +1 action)
  all_may self_convert pay=wild:5 gain=v:3             (each player may pay 5 of one chosen resource for 3 VP)
  all_may banish_owned_citizen role=soldier gain=v:3   (each player may banish an owned Soldier for 3 VP)
  all_must flip_citizen                                (each player must flip a citizen)
  active_lose g 3 + others_lose g 1                    (active loses 3g, every other player loses 1g)
  roll.on_event doubles all_lose m 3                   (passive: on a doubles roll, all players lose 3m)
"""
from cards import Event
from game_helpers import _parse_domain_effect_kv
from game_concurrent import _new_concurrent_action


_SCORE_ATTR = {"g": "gold_score", "s": "strength_score", "m": "magic_score", "v": "victory_score"}
_ROLE_ATTR = {"shadow": "shadow_count", "holy": "holy_count", "soldier": "soldier_count", "worker": "worker_count"}


def _parse_res_amount(spec):
    """'wild:5' -> ('wild', 5); 'm:3' -> ('m', 3); 'v:3' -> ('v', 3). Else (None, 0)."""
    if not spec or ":" not in spec:
        return None, 0
    kind, rest = spec.split(":", 1)
    kind = (kind or "").strip().lower()
    try:
        n = int((rest or "").strip())
    except (TypeError, ValueError):
        return None, 0
    if kind == "vp":
        kind = "v"
    if kind not in ("g", "s", "m", "v", "wild"):
        return None, 0
    return kind, n


class EventsEngine:
    def __init__(self, game):
        self.game = game

    # ---- reveal plumbing -------------------------------------------------

    def reveal_exhausted_onto_stack(self, stack):
        """Pop the top exhausted card, place it on ``stack`` and (for Event cards)
        reveal it. Returns the drawn card, or ``None`` if the exhausted stack is
        empty. Centralizes the previously-duplicated draw-from-exhausted logic.

        For a non-monster activation/passive event this also fires its effect.
        """
        if not self.game.exhausted_stack:
            return None
        card = self.game.exhausted_stack.pop()
        stack.append(card)
        self.game.exhausted_count = int(self.game.exhausted_count) + 1
        if isinstance(card, Event):
            card.toggle_visibility(True)
            card.toggle_accessibility(True)
            self.on_event_revealed(card)
        return card

    def on_event_revealed(self, event, revealing_player_id=None):
        """React to an Event card becoming visible on a board stack."""
        if bool(getattr(event, "is_monster", 0)):
            return  # monster events: slayable + board roll effects, unchanged
        if revealing_player_id is None:
            revealing_player_id = self.game.lifecycle.current_player_id()
        passive = (getattr(event, "passive_effect", None) or "").strip()
        activation = (getattr(event, "activation_effect", None) or "").strip()
        # A revealed non-monster event is shown face-up but is not slayable.
        event.toggle_accessibility(False)
        if bool(getattr(event, "has_passive_effect", 0)) and passive:
            self.game._log_game_event(
                f"Event \"{getattr(event, 'name', 'Event')}\" is now in play (passive)."
            )
            return
        if bool(getattr(event, "has_activation_effect", 0)) and activation:
            spec = {
                "event_id": int(getattr(event, "event_id", -1)),
                "name": getattr(event, "name", "Event"),
                "activation_effect": activation,
                "revealing_player_id": revealing_player_id,
            }
            # Fire immediately when it can resolve right now. Otherwise carry it
            # in the serialized pending queue (tagged to the revealing player)
            # until that player's Action Phase. This matters for the rare case
            # where an additional-action grant ("active_may gain_action") is
            # revealed outside the Action Phase (e.g. a harvest payout empties a
            # stack): the grant is held and offered when the player can actually
            # spend it, then expires with the turn.
            if self._engine_busy() or not self._activation_ready(spec):
                self.game.pending_event_activations.append(spec)
                if self._is_gain_action(spec):
                    self.game._log_game_event(
                        f"Event \"{spec['name']}\" revealed; "
                        f"{self.game._player_label(revealing_player_id)} may use it in their action phase."
                    )
                else:
                    self.game._log_game_event(
                        f"Event \"{spec['name']}\" revealed; activation queued."
                    )
            else:
                self._fire_activation(spec)

    def _engine_busy(self):
        """True when something is already blocking the engine (a player choice,
        concurrent prompt, or pending payout/action-end work)."""
        ca = getattr(self.game, "concurrent_action", None) or None
        if ca and (ca.get("pending") or []):
            return True
        ar = getattr(self.game, "action_required", None) or {}
        aid = ar.get("id")
        aact = str(ar.get("action", "") or "")
        if aid and aid != self.game.game_id and aact and aact != "standard_action":
            return True
        if getattr(self.game, "pending_payout_continuation", None):
            return True
        if getattr(self.game, "pending_action_end_queue", None):
            return True
        return False

    @staticmethod
    def _is_gain_action(spec):
        """True for an additional-action grant (`active_may gain_action ...`)."""
        return (spec.get("activation_effect") or "").strip().lower().startswith("active_may gain_action")

    def _activation_ready(self, spec):
        """True if `spec` can resolve in the current state.

        Most activations resolve any time the engine is idle. An additional-action
        grant only resolves during the revealing player's own Action Phase, since
        it bumps that player's usable actions for the turn.
        """
        if self._is_gain_action(spec):
            if getattr(self.game, "phase", None) != "action":
                return False
            rid = spec.get("revealing_player_id")
            return (not rid) or rid == self.game.lifecycle.current_player_id()
        return True

    def drain_pending_event_activations(self):
        """Fire queued activations one at a time while the engine is idle.

        Specs that cannot resolve yet (an additional-action grant awaiting the
        revealing player's Action Phase) stay queued in order. A grant tagged to
        a player whose turn has already passed is expired (dropped) rather than
        leaking onto a later active player.
        """
        queue = getattr(self.game, "pending_event_activations", None)
        if not isinstance(queue, list) or not queue:
            return
        holdover = []
        while queue and not self._engine_busy():
            spec = queue.pop(0)
            if self._is_gain_action(spec) and getattr(self.game, "phase", None) == "action":
                rid = spec.get("revealing_player_id")
                if rid and rid != self.game.lifecycle.current_player_id():
                    self.game._log_game_event(
                        f"Event \"{spec.get('name', 'Event')}\" additional-action offer expired."
                    )
                    continue
            if not self._activation_ready(spec):
                holdover.append(spec)
                continue
            self._fire_activation(spec)
        if holdover:
            self.game.pending_event_activations = holdover + queue

    # ---- activation dispatch --------------------------------------------

    def _fire_activation(self, spec):
        effect = (spec.get("activation_effect") or "").strip()
        name = spec.get("name", "Event")
        rid = spec.get("revealing_player_id") or self.game.lifecycle.current_player_id()
        if not effect:
            return
        low = effect.lower()
        if low.startswith("active_may "):
            self._fire_active_may(name, rid, effect[len("active_may "):].strip())
            return
        if low.startswith("all_may "):
            self._fire_all_may(name, rid, effect[len("all_may "):].strip())
            return
        if low.startswith("all_must "):
            self._fire_all_must(name, rid, effect[len("all_must "):].strip())
            return
        # Default: immediate synchronous resource changes (active_lose / others_lose
        # / all_lose, and their _gain counterparts). No prompt is opened.
        self._fire_immediate_resource_legs(name, rid, effect)

    # ---- active player optional prompts ----------------------------------

    def _fire_active_may(self, name, rid, body):
        parts = body.split()
        if not parts:
            return
        verb = parts[0].lower()
        if verb == "gain_action":
            kv = _parse_domain_effect_kv(body)
            pay_kind, pay_amount = _parse_res_amount(kv.get("pay", ""))
            self._prompt_gain_action(name, rid, pay_kind, pay_amount)
            return
        self.game._log_game_event(
            f"Event \"{name}\" has an unsupported active_may effect: {body!r}"
        )

    def _prompt_gain_action(self, name, player_id, pay_kind, pay_amount):
        """Open the active player's optional 'pay N to gain +1 action' prompt."""
        if pay_kind not in ("g", "s", "m") or pay_amount <= 0:
            self.game._log_game_event(f"Event \"{name}\" gain_action is malformed; skipped.")
            return
        if getattr(self.game, "phase", None) != "action":
            self.game._log_game_event(
                f"Event \"{name}\" can only grant an action during the Action Phase; skipped."
            )
            return
        player = self.game._player_by_id(player_id)
        if not player or int(getattr(player, _SCORE_ATTR[pay_kind], 0) or 0) < pay_amount:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} cannot afford event \"{name}\"; skipped."
            )
            return
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "event_gain_action"
        self.game.pending_required_choice = {
            "kind": "event_gain_action",
            "player_id": player_id,
            "event_name": name,
            "pay_kind": pay_kind,
            "pay_amount": int(pay_amount),
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} may pay {pay_amount}{pay_kind} "
            f"for an additional action (\"{name}\")."
        )

    def resolve_gain_action(self, player_id, accept):
        """Resolve the event_gain_action prompt. ``accept`` truthy pays + grants the action."""
        prc = getattr(self.game, "pending_required_choice", None) or {}
        if prc.get("kind") != "event_gain_action" or prc.get("player_id") != player_id:
            raise ValueError("No pending additional-action choice for you.")
        name = prc.get("event_name", "Event")
        pay_kind = prc.get("pay_kind", "m")
        pay_amount = int(prc.get("pay_amount", 0) or 0)
        player = self.game._player_by_id(player_id)
        if accept:
            if not player or int(getattr(player, _SCORE_ATTR[pay_kind], 0) or 0) < pay_amount:
                raise ValueError("You cannot afford this.")
            before = self.game._player_scores_line(player)
            setattr(player, _SCORE_ATTR[pay_kind],
                    int(getattr(player, _SCORE_ATTR[pay_kind], 0)) - pay_amount)
            self.game.actions_remaining = int(getattr(self.game, "actions_remaining", 0) or 0) + 1
            after = self.game._player_scores_line(player)
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} paid {pay_amount}{pay_kind} for an "
                f"additional action (\"{name}\"); scores {before} -> {after}"
            )
        else:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} declined event \"{name}\"."
            )
        self.game.pending_required_choice = None
        self.game.domain_effects._resume_after_domain_activation_follow_up()

    # ---- all-player concurrent prompts -----------------------------------

    def _event_participants(self, predicate):
        """Players that are negative-effect targets (resting seats excluded) and pass ``predicate``."""
        out = []
        for p in list(getattr(self.game, "player_list", []) or []):
            if not self.game._player_is_negative_effect_target(p):
                continue
            if predicate(p):
                out.append(p.player_id)
        return out

    def _fire_all_may(self, name, rid, body):
        parts = body.split()
        if not parts:
            return
        verb = parts[0].lower()
        if verb == "self_convert":
            self._begin_all_self_convert(name, body)
            return
        if verb == "banish_owned_citizen":
            self._begin_all_banish_for_reward(name, body)
            return
        self.game._log_game_event(
            f"Event \"{name}\" has an unsupported all_may effect: {body!r}"
        )

    def _fire_all_must(self, name, rid, body):
        parts = body.split()
        if not parts:
            return
        verb = parts[0].lower()
        if verb == "flip_citizen":
            self._begin_all_flip_citizen(name)
            return
        self.game._log_game_event(
            f"Event \"{name}\" has an unsupported all_must effect: {body!r}"
        )

    def _begin_all_self_convert(self, name, body):
        kv = _parse_domain_effect_kv(body)
        pay_kind, pay_amount = _parse_res_amount(kv.get("pay", ""))
        gain_kind, gain_amount = _parse_res_amount(kv.get("gain", ""))
        if not pay_kind or pay_amount <= 0 or gain_kind not in ("g", "s", "m", "v") or gain_amount <= 0:
            self.game._log_game_event(f"Event \"{name}\" self_convert is malformed; skipped.")
            return

        def can_afford(p):
            if pay_kind == "wild":
                return any(int(getattr(p, _SCORE_ATTR[r], 0) or 0) >= pay_amount for r in ("g", "s", "m"))
            return int(getattr(p, _SCORE_ATTR[pay_kind], 0) or 0) >= pay_amount

        targets = self._event_participants(can_afford)
        if not targets:
            self.game._log_game_event(f"Event \"{name}\": no player could pay; skipped.")
            return
        if getattr(self.game, "concurrent_action", None):
            # Should not happen (we only fire when idle) but guard anyway.
            self.game._log_game_event(f"Event \"{name}\" could not start (another prompt active).")
            return
        self.game.concurrent_action = _new_concurrent_action(
            "event_self_convert",
            targets,
            data={
                "name": name,
                "pay_kind": pay_kind,
                "pay_amount": int(pay_amount),
                "gain_kind": gain_kind,
                "gain_amount": int(gain_amount),
            },
        )
        self.game._log_game_event(
            f"Event \"{name}\": each player may pay {pay_amount}"
            f"{'(g/s/m)' if pay_kind == 'wild' else pay_kind} for {gain_amount}{gain_kind}."
        )

    def _begin_all_banish_for_reward(self, name, body):
        kv = _parse_domain_effect_kv(body)
        role = (kv.get("role") or "").strip().lower()
        gain_kind, gain_amount = _parse_res_amount(kv.get("gain", ""))
        if role and role not in _ROLE_ATTR:
            self.game._log_game_event(f"Event \"{name}\" banish role {role!r} unknown; skipped.")
            return
        if gain_kind not in ("g", "s", "m", "v") or gain_amount <= 0:
            self.game._log_game_event(f"Event \"{name}\" banish reward is malformed; skipped.")
            return

        def has_target(p):
            for c in list(getattr(p, "owned_citizens", []) or []):
                if getattr(c, "is_flipped", False):
                    continue
                if not role or int(getattr(c, _ROLE_ATTR[role], 0) or 0) > 0:
                    return True
            return False

        targets = self._event_participants(has_target)
        if not targets:
            self.game._log_game_event(
                f"Event \"{name}\": no player had a{' ' + role.title() if role else ''} citizen to banish; skipped."
            )
            return
        if getattr(self.game, "concurrent_action", None):
            self.game._log_game_event(f"Event \"{name}\" could not start (another prompt active).")
            return
        self.game.concurrent_action = _new_concurrent_action(
            "event_banish_citizen_for_reward",
            targets,
            data={
                "name": name,
                "role": role,
                "gain_kind": gain_kind,
                "gain_amount": int(gain_amount),
            },
        )
        self.game._log_game_event(
            f"Event \"{name}\": each player may banish a{' ' + role.title() if role else ''} citizen "
            f"for {gain_amount}{gain_kind}."
        )

    def _begin_all_flip_citizen(self, name):
        targets = self._event_participants(
            lambda p: any(not getattr(c, "is_flipped", False) for c in (getattr(p, "owned_citizens", []) or []))
        )
        if not targets:
            self.game._log_game_event(f"Event \"{name}\": no player had a citizen to flip; skipped.")
            return
        if getattr(self.game, "concurrent_action", None):
            self.game._log_game_event(f"Event \"{name}\" could not start (another prompt active).")
            return
        self.game.concurrent_action = _new_concurrent_action(
            "flip_one_citizen",
            targets,
            data={"source_label": name},
        )
        self.game._log_game_event(
            f"Event \"{name}\": each player with citizens must flip one face-down."
        )

    # ---- immediate (no-prompt) resource changes --------------------------

    def _fire_immediate_resource_legs(self, name, rid, effect):
        """Apply one or more ` + `-joined legs of the form
        ``active_lose|others_lose|all_lose|active_gain|all_gain <res> <int>``."""
        applied_any = False
        for leg in effect.split(" + "):
            tokens = leg.split()
            if len(tokens) < 3:
                continue
            verb = tokens[0].lower()
            res = tokens[1].lower()
            try:
                amount = int(tokens[2])
            except (TypeError, ValueError):
                continue
            if res not in _SCORE_ATTR or amount <= 0:
                continue
            sign, audience = self._classify_lose_gain_verb(verb)
            if sign == 0:
                self.game._log_game_event(f"Event \"{name}\" unknown verb {verb!r}; leg skipped.")
                continue
            applied_any = True
            for p in self._immediate_audience(audience, rid):
                if sign < 0 and not self.game._player_is_negative_effect_target(p):
                    self.game._log_game_event(
                        f"{self.game._player_label(p.player_id)} is resting; "
                        f"loses 0{res} from event \"{name}\"."
                    )
                    continue
                attr = _SCORE_ATTR[res]
                before = int(getattr(p, attr, 0) or 0)
                if sign < 0:
                    new_val = max(0, before - amount)
                else:
                    new_val = before + amount
                setattr(p, attr, new_val)
                verbed = "loses" if sign < 0 else "gains"
                self.game._log_game_event(
                    f"{self.game._player_label(p.player_id)} {verbed} {amount}{res} "
                    f"from event \"{name}\" (was {before}, now {new_val})."
                )
        if not applied_any:
            self.game._log_game_event(f"Event \"{name}\" had no recognizable effect: {effect!r}")

    @staticmethod
    def _classify_lose_gain_verb(verb):
        """Return (sign, audience). sign: -1 lose, +1 gain, 0 unknown."""
        mapping = {
            "active_lose": (-1, "active"),
            "others_lose": (-1, "others"),
            "all_lose": (-1, "all"),
            "active_gain": (1, "active"),
            "others_gain": (1, "others"),
            "all_gain": (1, "all"),
        }
        return mapping.get(verb, (0, ""))

    def _immediate_audience(self, audience, active_pid):
        players = list(getattr(self.game, "player_list", []) or [])
        if audience == "active":
            ap = self.game._player_by_id(active_pid)
            return [ap] if ap else []
        if audience == "others":
            return [p for p in players if p.player_id != active_pid]
        return players  # "all"

    # ---- passive board scans ---------------------------------------------

    def _iter_inplay_passive_events(self):
        """Yield non-monster Event cards currently in play (top of any board stack)."""
        for grid in (self.game.monster_grid, self.game.citizen_grid, self.game.domain_grid):
            for stack in (grid or []):
                if not stack:
                    continue
                top = stack[-1]
                if not isinstance(top, Event):
                    continue
                if bool(getattr(top, "is_monster", 0)):
                    continue
                if not bool(getattr(top, "has_passive_effect", 0)):
                    continue
                if not (getattr(top, "passive_effect", None) or "").strip():
                    continue
                yield top

    def apply_board_event_passive_roll_effects(self):
        """Fire ``roll.on_event <event> all_lose <res> <amt>`` passives of in-play
        events against the current ``roll_events`` (e.g. Curse of The North on doubles)."""
        events = set(getattr(self.game, "roll_events", None) or [])
        if not events:
            return
        for ev in self._iter_inplay_passive_events():
            raw = (getattr(ev, "passive_effect", None) or "").strip()
            parts = raw.split()
            if len(parts) < 5 or parts[0].lower() != "roll.on_event":
                continue
            trigger = parts[1].lower()
            verb = parts[2].lower()
            res = parts[3].lower()
            try:
                amount = int(parts[4])
            except (TypeError, ValueError):
                continue
            if trigger not in events or verb != "all_lose" or res not in _SCORE_ATTR or amount <= 0:
                continue
            for p in list(getattr(self.game, "player_list", []) or []):
                if not self.game._player_is_negative_effect_target(p):
                    self.game._log_game_event(
                        f"{self.game._player_label(p.player_id)} is resting; "
                        f"loses 0{res} from event \"{getattr(ev, 'name', 'Event')}\"."
                    )
                    continue
                attr = _SCORE_ATTR[res]
                before = int(getattr(p, attr, 0) or 0)
                new_val = max(0, before - amount)
                setattr(p, attr, new_val)
                self.game._log_game_event(
                    f"{self.game._player_label(p.player_id)} loses {amount}{res} from event "
                    f"\"{getattr(ev, 'name', 'Event')}\" ({trigger}); was {before}, now {new_val}."
                )
