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
  all_gain_per_owned gain=m:1 per=citizen              (each player gains 1m per owned citizen)
  active_choose self_gain:g:2 | all_gain:m:4           (active player picks exactly one option)
  seq all_must pay_to_chosen pay=wild:2                (in turn order: pay 2 of one resource to a chosen player)
  seq all_must banish_center_citizen                   (in turn order: banish a citizen from the center stacks)
  seq all_may banish_owned_citizen gain=v:3            (in turn order: optionally banish an owned citizen for 3 VP)
  roll.on_event doubles all_lose m 3                   (passive: on a doubles roll, all players lose 3m)
  roll.on_event doubles all_gain g 1 + all_gain s 1 + all_gain m 1   (passive: doubles -> all gain 1g/1s/1m)
  grant_all action.blessedlands                        (passive: grant a rest-of-game flag to every player)
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


def _parse_pay_spec(raw):
    """Parse a self_convert ``pay=`` value into a normalized payment mode.

    Returns one of:
      ("single", kind, amount)        e.g. "m:3"
      ("wild", None, amount)          e.g. "wild:5"  (player picks g/s/m)
      ("compound", [(k, a), ...], 0)  e.g. "g:1,s:1,m:1" (pay every leg)
    or None if malformed.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if "," in raw:
        legs = []
        for part in raw.split(","):
            k, a = _parse_res_amount(part.strip())
            if not k or k in ("wild", "v") or a <= 0:
                return None
            legs.append((k, a))
        return ("compound", legs, 0) if legs else None
    kind, amount = _parse_res_amount(raw)
    if not kind or amount <= 0:
        return None
    if kind == "wild":
        return ("wild", None, amount)
    if kind == "v":
        return None
    return ("single", kind, amount)


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
            name = getattr(event, "name", "Event")
            low = passive.lower()
            if low.startswith("grant_all "):
                # "Rest of the game" global modifier (e.g. Blessed Lands, Dark
                # Lord Rising): grant a named effect flag to every player once.
                # Idempotent so a re-reveal (un-exhaust then re-draw) won't stack.
                flag = passive[len("grant_all "):].strip()
                self._grant_effect_to_all(flag, name)
                return
            self.game._log_game_event(
                f"Event \"{name}\" is now in play (passive)."
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
        if low.startswith("seq "):
            self._fire_sequence(name, rid, effect[len("seq "):].strip())
            return
        if low.startswith("active_choose "):
            self._fire_active_choose(name, rid, effect[len("active_choose "):].strip())
            return
        if low.startswith("all_gain_per_owned "):
            self._fire_all_gain_per_owned(name, effect[len("all_gain_per_owned "):].strip())
            return
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
        spec = _parse_pay_spec(kv.get("pay", ""))
        gain_kind, gain_amount = _parse_res_amount(kv.get("gain", ""))
        if not spec or gain_kind not in ("g", "s", "m", "v") or gain_amount <= 0:
            self.game._log_game_event(f"Event \"{name}\" self_convert is malformed; skipped.")
            return
        mode, payload, pay_amount = spec

        data = {"name": name, "gain_kind": gain_kind, "gain_amount": int(gain_amount)}
        if mode == "compound":
            legs = payload
            data["pay_legs"] = [[k, int(a)] for k, a in legs]
            cost_label = "+".join(f"{a}{k}" for k, a in legs)

            def can_afford(p):
                return all(int(getattr(p, _SCORE_ATTR[k], 0) or 0) >= a for k, a in legs)
        elif mode == "wild":
            data["pay_kind"] = "wild"
            data["pay_amount"] = int(pay_amount)
            cost_label = f"{pay_amount}(g/s/m)"

            def can_afford(p):
                return any(int(getattr(p, _SCORE_ATTR[r], 0) or 0) >= pay_amount for r in ("g", "s", "m"))
        else:  # single
            pay_kind = payload
            data["pay_kind"] = pay_kind
            data["pay_amount"] = int(pay_amount)
            cost_label = f"{pay_amount}{pay_kind}"

            def can_afford(p):
                return int(getattr(p, _SCORE_ATTR[pay_kind], 0) or 0) >= pay_amount

        targets = self._event_participants(can_afford)
        if not targets:
            self.game._log_game_event(f"Event \"{name}\": no player could pay; skipped.")
            return
        if getattr(self.game, "concurrent_action", None):
            # Should not happen (we only fire when idle) but guard anyway.
            self.game._log_game_event(f"Event \"{name}\" could not start (another prompt active).")
            return
        self.game.concurrent_action = _new_concurrent_action("event_self_convert", targets, data=data)
        self.game._log_game_event(
            f"Event \"{name}\": each player may pay {cost_label} for {gain_amount}{gain_kind}."
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

    # ---- immediate scaled gain -------------------------------------------

    def _fire_all_gain_per_owned(self, name, body):
        """`all_gain_per_owned gain=m:1 per=citizen`: every player immediately
        gains `amount` of the resource for each card of `per` they own. Positive,
        so the resting seat gains too."""
        kv = _parse_domain_effect_kv(body)
        gain_kind, gain_amount = _parse_res_amount(kv.get("gain", ""))
        per = (kv.get("per") or "citizen").strip().lower()
        if gain_kind not in ("g", "s", "m", "v") or gain_amount <= 0:
            self.game._log_game_event(f"Event \"{name}\" all_gain_per_owned is malformed; skipped.")
            return
        if per != "citizen":
            self.game._log_game_event(f"Event \"{name}\" unsupported per={per!r}; skipped.")
            return
        attr = _SCORE_ATTR[gain_kind]
        for p in list(getattr(self.game, "player_list", []) or []):
            count = len(list(getattr(p, "owned_citizens", []) or []))
            if count <= 0:
                self.game._log_game_event(
                    f"{self.game._player_label(p.player_id)} owns no citizens; "
                    f"gains 0{gain_kind} from event \"{name}\"."
                )
                continue
            total = gain_amount * count
            before = int(getattr(p, attr, 0) or 0)
            setattr(p, attr, before + total)
            self.game._log_game_event(
                f"{self.game._player_label(p.player_id)} gains {total}{gain_kind} "
                f"({gain_amount} x {count} citizens) from event \"{name}\" "
                f"(was {before}, now {before + total})."
            )

    # ---- active player choose-one-of-two ---------------------------------

    def _parse_choose_option(self, raw):
        """'self_gain:g:2' -> {audience,'self'|'all', verb:'gain', kind, amount}."""
        bits = (raw or "").strip().split(":")
        if len(bits) != 3:
            return None
        head, kind, amt = bits[0].strip().lower(), bits[1].strip().lower(), bits[2].strip()
        if head in ("self_gain", "active_gain"):
            audience = "active"
        elif head == "all_gain":
            audience = "all"
        else:
            return None
        if kind == "vp":
            kind = "v"
        if kind not in ("g", "s", "m", "v"):
            return None
        try:
            amount = int(amt)
        except (TypeError, ValueError):
            return None
        if amount <= 0:
            return None
        return {"audience": audience, "kind": kind, "amount": amount}

    def _fire_active_choose(self, name, rid, body):
        """`active_choose self_gain:g:2 | all_gain:m:4`: the active player must
        pick exactly one of the listed options (Golden Idol)."""
        options = []
        for raw in body.split("|"):
            opt = self._parse_choose_option(raw)
            if opt:
                options.append(opt)
        if len(options) < 2:
            self.game._log_game_event(f"Event \"{name}\" active_choose is malformed; skipped.")
            return
        player = self.game._player_by_id(rid)
        if not player:
            self.game._log_game_event(f"Event \"{name}\": active player missing; skipped.")
            return
        self.game.action_required["id"] = rid
        self.game.action_required["action"] = "event_active_choose"
        self.game.pending_required_choice = {
            "kind": "event_active_choose",
            "player_id": rid,
            "event_name": name,
            "options": options,
        }
        self.game._log_game_event(
            f"{self.game._player_label(rid)} must choose an option for event \"{name}\"."
        )

    def resolve_active_choose(self, player_id, choice_index):
        prc = getattr(self.game, "pending_required_choice", None) or {}
        if prc.get("kind") != "event_active_choose" or prc.get("player_id") != player_id:
            raise ValueError("No pending event choice for you.")
        options = list(prc.get("options") or [])
        try:
            idx = int(choice_index)
        except (TypeError, ValueError):
            raise ValueError("Invalid choice.")
        if idx < 0 or idx >= len(options):
            raise ValueError("Invalid choice index.")
        name = prc.get("event_name", "Event")
        opt = options[idx]
        attr = _SCORE_ATTR[opt["kind"]]
        if opt["audience"] == "active":
            recipients = [self.game._player_by_id(player_id)]
        else:
            recipients = list(getattr(self.game, "player_list", []) or [])
        for p in recipients:
            if not p:
                continue
            before = int(getattr(p, attr, 0) or 0)
            setattr(p, attr, before + opt["amount"])
            self.game._log_game_event(
                f"{self.game._player_label(p.player_id)} gains {opt['amount']}{opt['kind']} "
                f"from event \"{name}\" (was {before}, now {before + opt['amount']})."
            )
        self.game.pending_required_choice = None
        self.game.action_required["id"] = self.game.game_id
        self.game.action_required["action"] = ""

    # ---- sequential "in turn order" resolution ---------------------------

    def _fire_sequence(self, name, rid, body):
        """Begin an "in turn order" event. `body` is one of:
          all_must pay_to_chosen pay=wild:2
          all_must banish_center_citizen
          all_may  banish_owned_citizen gain=v:3
        Players resolve one at a time, active player first, resting seat excluded.
        """
        parts = body.split()
        if len(parts) < 2:
            self.game._log_game_event(f"Event \"{name}\" seq is malformed; skipped.")
            return
        audience = parts[0].lower()
        verb = parts[1].lower()
        mandatory = audience == "all_must"
        rest = body[len(parts[0]):].strip()
        rest = rest[len(parts[1]):].strip()
        kv = _parse_domain_effect_kv(rest) if rest else {}
        data = {}
        if verb == "pay_to_chosen":
            pay_kind, pay_amount = _parse_res_amount(kv.get("pay", ""))
            if not pay_kind or pay_amount <= 0:
                self.game._log_game_event(f"Event \"{name}\" pay_to_chosen is malformed; skipped.")
                return
            data = {"pay_kind": pay_kind, "pay_amount": int(pay_amount)}
        elif verb == "banish_center_citizen":
            data = {}
        elif verb == "banish_owned_citizen":
            gain_kind, gain_amount = _parse_res_amount(kv.get("gain", ""))
            role = (kv.get("role") or "").strip().lower()
            if gain_kind not in ("g", "s", "m", "v") or gain_amount <= 0:
                self.game._log_game_event(f"Event \"{name}\" banish reward is malformed; skipped.")
                return
            data = {"gain_kind": gain_kind, "gain_amount": int(gain_amount), "role": role}
        else:
            self.game._log_game_event(f"Event \"{name}\" unsupported seq verb {verb!r}; skipped.")
            return
        self._begin_sequence(name, verb, mandatory, data)

    def _begin_sequence(self, name, verb, mandatory, data):
        if getattr(self.game, "pending_event_sequence", None):
            self.game._log_game_event(f"Event \"{name}\" could not start (sequence already running).")
            return
        order = self.game._harvest_player_id_order_starting_active()
        if not order:
            self.game._log_game_event(f"Event \"{name}\": no eligible players; skipped.")
            return
        self.game.pending_event_sequence = {
            "name": name,
            "verb": verb,
            "mandatory": bool(mandatory),
            "queue": list(order),
            "data": dict(data or {}),
        }
        self.game._log_game_event(f"Event \"{name}\": resolving in turn order.")
        self._advance_sequence()

    def _seq_center_citizen_stacks(self):
        """Indices of center citizen stacks with an accessible top citizen."""
        out = []
        for idx, stack in enumerate(list(getattr(self.game, "citizen_grid", []) or [])):
            if not stack:
                continue
            top = stack[-1]
            if isinstance(top, Event):
                continue
            if getattr(top, "citizen_id", None) is None:
                continue
            if not getattr(top, "is_accessible", False):
                continue
            out.append(idx)
        return out

    def _seq_owned_citizen_indices(self, player, role=""):
        out = []
        for i, c in enumerate(list(getattr(player, "owned_citizens", []) or [])):
            if getattr(c, "is_flipped", False):
                continue
            if role and role in _ROLE_ATTR and int(getattr(c, _ROLE_ATTR[role], 0) or 0) <= 0:
                continue
            out.append(i)
        return out

    def _seq_player_can_act(self, seq, player):
        """Whether `player` has a legal move for the current sequence verb."""
        verb = seq.get("verb")
        data = seq.get("data") or {}
        if verb == "pay_to_chosen":
            amt = int(data.get("pay_amount") or 0)
            return any(int(getattr(player, _SCORE_ATTR[r], 0) or 0) >= amt for r in ("g", "s", "m"))
        if verb == "banish_center_citizen":
            return bool(self._seq_center_citizen_stacks())
        if verb == "banish_owned_citizen":
            return bool(self._seq_owned_citizen_indices(player, role=(data.get("role") or "")))
        return False

    def _advance_sequence(self):
        """Open the next player's prompt, skipping players with no legal move.
        Clears the sequence and unblocks the engine when the queue empties."""
        seq = getattr(self.game, "pending_event_sequence", None)
        if not seq:
            return
        name = seq.get("name", "Event")
        verb = seq.get("verb")
        mandatory = bool(seq.get("mandatory"))
        queue = seq.get("queue") or []
        while queue:
            pid = queue[0]
            player = self.game._player_by_id(pid)
            if not player or not self._seq_player_can_act(seq, player):
                if player:
                    self.game._log_game_event(
                        f"{self.game._player_label(pid)} has no legal move for event \"{name}\"; skipped."
                    )
                queue.pop(0)
                continue
            # Open this player's prompt and wait.
            self.game.action_required["id"] = pid
            self.game.action_required["action"] = "event_sequence"
            self.game.pending_required_choice = {
                "kind": "event_sequence",
                "player_id": pid,
                "event_name": name,
                "verb": verb,
                "mandatory": mandatory,
                "data": dict(seq.get("data") or {}),
            }
            if verb == "banish_center_citizen":
                self.game.pending_required_choice["stack_options"] = self._seq_center_citizen_stacks()
            elif verb == "banish_owned_citizen":
                self.game.pending_required_choice["owned_options"] = self._seq_owned_citizen_indices(
                    player, role=(seq.get("data") or {}).get("role") or ""
                )
            self.game._log_game_event(
                f"{self.game._player_label(pid)} must resolve event \"{name}\"."
                if mandatory else
                f"{self.game._player_label(pid)} may resolve event \"{name}\"."
            )
            return
        # Queue drained.
        self.game.pending_event_sequence = None
        self.game.pending_required_choice = None
        self.game.action_required["id"] = self.game.game_id
        self.game.action_required["action"] = ""
        self.game._log_game_event(f"Event \"{name}\": all players resolved.")

    def resolve_sequence_response(self, player_id, action):
        """Apply one player's response to the active sequence, then advance."""
        seq = getattr(self.game, "pending_event_sequence", None)
        if not seq:
            raise ValueError("No event sequence in progress.")
        queue = seq.get("queue") or []
        if not queue or queue[0] != player_id:
            raise ValueError("It is not your turn to resolve this event.")
        verb = seq.get("verb")
        name = seq.get("name", "Event")
        data = seq.get("data") or {}
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        act = (action or "").strip().lower()

        if verb == "pay_to_chosen":
            # "pay <g|s|m> <recipient_player_id>"
            toks = act.split()
            if len(toks) != 3 or toks[0] != "pay":
                raise ValueError("Send 'pay <g|s|m> <recipient_player_id>'.")
            res = toks[1]
            recipient_id = (action or "").strip().split()[2]
            amt = int(data.get("pay_amount") or 0)
            if res not in ("g", "s", "m"):
                raise ValueError("Choose a resource to pay (g/s/m).")
            if int(getattr(player, _SCORE_ATTR[res], 0) or 0) < amt:
                raise ValueError("You cannot afford that resource.")
            recipient = self.game._player_by_id(recipient_id)
            if not recipient or recipient.player_id == player_id:
                raise ValueError("Choose another player as the recipient.")
            pb = self.game._player_scores_line(player)
            rb = self.game._player_scores_line(recipient)
            setattr(player, _SCORE_ATTR[res], int(getattr(player, _SCORE_ATTR[res], 0)) - amt)
            setattr(recipient, _SCORE_ATTR[res], int(getattr(recipient, _SCORE_ATTR[res], 0)) + amt)
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} paid {amt}{res} to "
                f"{self.game._player_label(recipient_id)} for event \"{name}\"; "
                f"{pb}->{self.game._player_scores_line(player)}, "
                f"{rb}->{self.game._player_scores_line(recipient)}."
            )

        elif verb == "banish_center_citizen":
            toks = act.split()
            if len(toks) == 2 and toks[0] == "stack":
                idx_raw = toks[1]
            else:
                idx_raw = act
            try:
                stack_idx = int(idx_raw)
            except (TypeError, ValueError):
                raise ValueError("Send the center citizen stack index to banish.")
            if stack_idx not in self._seq_center_citizen_stacks():
                raise ValueError("That center citizen stack has no banishable citizen.")
            banished = self.game.payouts._banish_center_citizen(stack_idx)
            if banished is None:
                raise ValueError("Could not banish from that stack.")
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} banished center citizen "
                f"\"{getattr(banished, 'name', '?')}\" for event \"{name}\"."
            )

        elif verb == "banish_owned_citizen":
            if act in ("skip", "decline", "no", "pass"):
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} declined event \"{name}\"."
                )
            else:
                try:
                    idx = int(act)
                except (TypeError, ValueError):
                    raise ValueError("Send a tableau index to banish, or 'skip'.")
                role = (data.get("role") or "")
                if idx not in self._seq_owned_citizen_indices(player, role=role):
                    raise ValueError("Invalid citizen choice.")
                cit = list(player.owned_citizens)[idx]
                gain_kind = data.get("gain_kind", "v")
                gain_amount = int(data.get("gain_amount") or 0)
                player.owned_citizens.remove(cit)
                self.game.banish_pile.append(cit)
                before = self.game._player_scores_line(player)
                setattr(player, _SCORE_ATTR[gain_kind],
                        int(getattr(player, _SCORE_ATTR[gain_kind], 0)) + gain_amount)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} banished \"{getattr(cit, 'name', '?')}\" "
                    f"for event \"{name}\"; scores {before} -> {self.game._player_scores_line(player)}."
                )
        else:
            raise ValueError(f"Unsupported sequence verb {verb!r}.")

        queue.pop(0)
        self._advance_sequence()

    # ---- "rest of the game" granted flags + global cost mods -------------

    def _grant_effect_to_all(self, flag, event_name):
        flag = (flag or "").strip()
        if not flag:
            return
        granted_to = []
        for p in list(getattr(self.game, "player_list", []) or []):
            ge = getattr(p, "granted_effects", None)
            if ge is None:
                ge = []
                p.granted_effects = ge
            if flag not in ge:
                ge.append(flag)
                granted_to.append(self.game._player_label(p.player_id))
        if granted_to:
            self.game._log_game_event(
                f"Event \"{event_name}\" is now in play for the rest of the game "
                f"(granted {flag} to all players)."
            )
        else:
            self.game._log_game_event(
                f"Event \"{event_name}\" re-revealed; {flag} already in effect."
            )

    def on_event_unexhausted(self, event):
        """Reverse a `grant_all` passive when its event leaves play (un-exhaust).

        The flag is removed from every player until the event is re-revealed
        (which re-applies it via ``on_event_revealed``). Monster events and
        non-grant passives are no-ops.
        """
        if not isinstance(event, Event) or bool(getattr(event, "is_monster", 0)):
            return
        passive = (getattr(event, "passive_effect", None) or "").strip()
        if passive.lower().startswith("grant_all "):
            flag = passive[len("grant_all "):].strip()
            self._revoke_effect_from_all(flag, getattr(event, "name", "Event"))

    def _revoke_effect_from_all(self, flag, event_name):
        flag = (flag or "").strip()
        if not flag:
            return
        removed = False
        for p in list(getattr(self.game, "player_list", []) or []):
            ge = getattr(p, "granted_effects", None) or []
            if flag in ge:
                p.granted_effects = [g for g in ge if g != flag]
                removed = True
        if removed:
            self.game._log_game_event(
                f"Event \"{event_name}\" left play; {flag} no longer in effect."
            )

    def _any_player_has_flag(self, flag):
        for p in list(getattr(self.game, "player_list", []) or []):
            if flag in list(getattr(p, "granted_effects", None) or []):
                return True
        return False

    def blessed_lands_discount(self):
        """Gold reduction applied to every Domain build while Blessed Lands is in play."""
        return 2 if self._any_player_has_flag("action.blessedlands") else 0

    def dark_lord_surcharge(self):
        """Extra Magic added to every Monster slay while Dark Lord Rising is in play."""
        return 1 if self._any_player_has_flag("action.darklordrising") else 0

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
        """Fire ``roll.on_event <trigger> <legs>`` passives of in-play events
        against the current ``roll_events``. Legs are ` + `-joined
        ``all_lose|all_gain <res> <amt>`` clauses, e.g.:

          roll.on_event doubles all_lose m 3                         (Curse of The North)
          roll.on_event doubles all_gain g 1 + all_gain s 1 + all_gain m 1   (Good Omen)

        Losses skip the resting seat (negative); gains apply to everyone.
        """
        events = set(getattr(self.game, "roll_events", None) or [])
        if not events:
            return
        for ev in self._iter_inplay_passive_events():
            raw = (getattr(ev, "passive_effect", None) or "").strip()
            parts = raw.split(None, 2)
            if len(parts) < 3 or parts[0].lower() != "roll.on_event":
                continue
            trigger = parts[1].lower()
            if trigger not in events:
                continue
            ev_name = getattr(ev, "name", "Event")
            for leg in parts[2].split(" + "):
                tokens = leg.split()
                if len(tokens) < 3:
                    continue
                verb, res = tokens[0].lower(), tokens[1].lower()
                try:
                    amount = int(tokens[2])
                except (TypeError, ValueError):
                    continue
                if res not in _SCORE_ATTR or amount <= 0:
                    continue
                sign, audience = self._classify_lose_gain_verb(verb)
                if sign == 0 or audience != "all":
                    continue
                attr = _SCORE_ATTR[res]
                for p in list(getattr(self.game, "player_list", []) or []):
                    if sign < 0 and not self.game._player_is_negative_effect_target(p):
                        self.game._log_game_event(
                            f"{self.game._player_label(p.player_id)} is resting; "
                            f"loses 0{res} from event \"{ev_name}\"."
                        )
                        continue
                    before = int(getattr(p, attr, 0) or 0)
                    new_val = max(0, before - amount) if sign < 0 else before + amount
                    setattr(p, attr, new_val)
                    self.game._log_game_event(
                        f"{self.game._player_label(p.player_id)} "
                        f"{'loses' if sign < 0 else 'gains'} {amount}{res} from event "
                        f"\"{ev_name}\" ({trigger}); was {before}, now {new_val}."
                    )
