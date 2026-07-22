"""Open-loop Monte Carlo Tree Search over the headless simulator.

Per decision: N iterations of clone -> descend (UCT) -> expand -> rollout ->
backpropagate. Chance events (dice, deck reveals) are re-sampled naturally on
every iteration because each descent replays through the live engine — nodes
are keyed by the move taken, not by resulting state (open-loop MCTS), which is
the standard fix for stochastic games.

Rewards are from the root player's perspective: win=1, tie=0.5, loss=0. At
opponent decision nodes UCT selects with the inverted reward, i.e. the opponent
is assumed to play to beat us (2-player). Rollouts use the biased-random
policy; rollouts that hit the step cap are scored by comparing projected final
scores (victory_score + duke VP via the engine's own endgame calculator).

Hidden information is handled by determinization (ISMCTS-style): each iteration
re-randomizes everything the root player cannot see — buried domain cards, the
undealt exhausted/event deck order, and the opponent's duke — so the search
plans against samples of its information set rather than the true hidden state.
(One residual leak: the deck's event COMPOSITION is kept, only its order is
reshuffled; resampling composition from the full event pool is a refinement.)
"""

import contextlib
import io
import json
import math
import random

from agent.headless import acting_player_ids, advance, apply_move, clone_game, legal_moves
from agent.play_random import _fingerprint
from agent.policies import GreedyPolicy

_SINK = io.StringIO()


class _Node:
    __slots__ = ("children", "visits", "value", "invalid", "priors")

    def __init__(self):
        self.children = {}
        self.visits = 0
        self.value = 0.0
        self.invalid = set()
        self.priors = None  # {move_key: prior_prob}, computed on first visit


def _move_key(move):
    return json.dumps(move, sort_keys=True, default=str)


def _biased_random_move(moves):
    builders = [
        m for m in moves
        if m.get("action_type") in ("hire_citizen", "build_domain", "slay_monster")
    ]
    if builders and random.random() < 0.75:
        return random.choice(builders)
    return random.choice(moves)


class MCTSPolicy:
    name = "mcts"

    def __init__(self, iterations=100, exploration=1.5, rollout_cap=250, descent_cap=400,
                 rollout_epsilon=0.15, top_k=12, prior_temperature=2.0, determinize=True):
        self.iterations = iterations
        self.exploration = exploration
        self.rollout_cap = rollout_cap
        self.descent_cap = descent_cap
        self.rollout_epsilon = rollout_epsilon
        self.top_k = top_k
        self.prior_temperature = prior_temperature
        self.determinize = determinize
        self._greedy = GreedyPolicy()

    # ---- determinization (ISMCTS-style) --------------------------------

    def _determinize(self, game, root_pid):
        """Re-randomize everything the root player cannot see, so the search
        plans against a fresh sample of hidden state each iteration instead of
        peeking at the true buried cards. Hidden zones in base1 2-player:
        face-down domain cards, the undealt exhausted/event deck order, and
        the opponent's duke."""
        hidden_slots, hidden_cards = [], []
        for stack in game.domain_grid or []:
            for j, card in enumerate(stack):
                if card is not None and not getattr(card, "is_visible", True):
                    hidden_slots.append((stack, j))
                    hidden_cards.append(card)
        if len(hidden_cards) > 1:
            random.shuffle(hidden_cards)
            for (stack, j), card in zip(hidden_slots, hidden_cards):
                stack[j] = card

        deck = getattr(game, "exhausted_stack", None)
        if isinstance(deck, list) and len(deck) > 1:
            random.shuffle(deck)

        catalog = list(getattr(game, "all_dukes", None) or [])
        if catalog:
            me = next((p for p in game.player_list if p.player_id == root_pid), None)
            known = {
                getattr(d, "duke_id", None)
                for d in (getattr(me, "owned_dukes", None) or [])
            }
            pool = [d for d in catalog if getattr(d, "duke_id", None) not in known]
            random.shuffle(pool)
            for p in game.player_list:
                if p.player_id == root_pid:
                    continue
                n = len(getattr(p, "owned_dukes", None) or [])
                if n and len(pool) >= n:
                    p.owned_dukes = [pool.pop() for _ in range(n)]

    def _compute_priors(self, sim, pid, moves_by_key):
        """Softmax of greedy VP-values -> prior move probabilities; also prunes
        to the top_k moves so search budget concentrates where it matters."""
        keys = list(moves_by_key)
        moves = [moves_by_key[k] for k in keys]
        values = self._greedy.move_values(sim, pid, moves)
        if values is None:
            p = 1.0 / len(keys)
            return {k: p for k in keys}
        ranked = sorted(zip(keys, values), key=lambda kv: -kv[1])[: self.top_k]
        top = ranked[0][1]
        weights = {k: math.exp((v - top) / self.prior_temperature) for k, v in ranked}
        total = sum(weights.values())
        return {k: w / total for k, w in weights.items()}

    # ---- rewards -------------------------------------------------------

    def _terminal_reward(self, game, root_pid):
        winners = set((game.final_result or {}).get("winner_player_ids") or [])
        if not winners:
            return 0.5
        if root_pid in winners:
            return 1.0 if len(winners) == 1 else 0.5
        return 0.0

    def _projected_reward(self, game, root_pid):
        """Score an unfinished rollout by projected final VP (engine's own math)."""
        try:
            scores = game.endgame._calculate_final_scores()
        except Exception:
            scores = [
                {"player_id": p.player_id, "total_vp": int(p.victory_score), "tableau_size": 0}
                for p in game.player_list
            ]
        ranked = sorted(
            scores, key=lambda r: (-int(r["total_vp"]), -int(r.get("tableau_size") or 0))
        )
        top_vp = int(ranked[0]["total_vp"])
        leaders = [r["player_id"] for r in ranked if int(r["total_vp"]) == top_vp]
        if root_pid in leaders:
            return 1.0 if len(leaders) == 1 else 0.5
        return 0.0

    # ---- one simulated step -------------------------------------------

    def _sim_decision(self, game):
        """Return (pid, moves) at the current block point, or None if game over/stuck."""
        guard = 0
        while game.phase != "game_over":
            for pid in acting_player_ids(game):
                moves = legal_moves(game, pid)
                if moves:
                    return pid, moves
            if not game.advance_tick():
                return None
            advance(game)
            guard += 1
            if guard > 50:
                return None
        return None

    def _apply(self, game, move):
        """Apply move; True on progress, False if rejected/no-op.

        IndexError is a known engine crash (Undead Samurai 6th-area
        _return_monster_to_stack, raised before any mutation) — treat as rejected.
        """
        before = _fingerprint(game)
        try:
            apply_move(game, move)
        except (ValueError, KeyError, IndexError):
            return False
        return _fingerprint(game) != before

    def _rollout(self, game, root_pid):
        """Play out with epsilon-greedy policy (both seats) — realistic playouts
        make the win/loss signal far less noisy than uniform-random ones."""
        for _ in range(self.rollout_cap):
            decision = self._sim_decision(game)
            if decision is None:
                break
            pid, moves = decision
            while moves:
                if random.random() < self.rollout_epsilon:
                    move = _biased_random_move(moves)
                else:
                    move = self._greedy.choose(game, None, pid, moves) or moves[0]
                moves.remove(move)
                if self._apply(game, move):
                    break
        if game.phase == "game_over":
            return self._terminal_reward(game, root_pid)
        return self._projected_reward(game, root_pid)

    # ---- UCT -----------------------------------------------------------

    def _select(self, node, keys, priors, maximize):
        """PUCT: Q + c * P * sqrt(N) / (1 + n), with greedy-softmax priors P."""
        sqrt_n = math.sqrt(max(node.visits, 1))
        uniform = 1.0 / max(len(keys), 1)
        best_key, best_score = None, None
        for key in keys:
            child = node.children.get(key)
            n = child.visits if child is not None else 0
            if n == 0:
                mean = 0.5
            else:
                mean = child.value / child.visits
                if not maximize:
                    mean = 1.0 - mean
            prior = priors.get(key, uniform)
            score = mean + self.exploration * prior * sqrt_n / (1 + n)
            if best_score is None or score > best_score:
                best_key, best_score = key, score
        return best_key

    def choose(self, game, view, player_id, moves):
        if not moves:
            return None
        if len(moves) < 2:
            return moves[0]
        root = _Node()
        root_moves_by_key = {_move_key(m): m for m in moves}

        with contextlib.redirect_stdout(_SINK):
            for _ in range(self.iterations):
                sim = clone_game(game)
                if self.determinize:
                    self._determinize(sim, player_id)
                node = root
                path = [root]
                reward = None
                depth = 0
                while True:
                    depth += 1
                    if depth > self.descent_cap:
                        reward = self._projected_reward(sim, player_id)
                        break
                    if sim.phase == "game_over":
                        reward = self._terminal_reward(sim, player_id)
                        break
                    decision = self._sim_decision(sim)
                    if decision is None:
                        reward = (
                            self._terminal_reward(sim, player_id)
                            if sim.phase == "game_over"
                            else self._projected_reward(sim, player_id)
                        )
                        break
                    pid, sim_moves = decision
                    moves_by_key = {
                        k: m for k, m in ((_move_key(m), m) for m in sim_moves)
                        if k not in node.invalid
                    }
                    if not moves_by_key:
                        reward = self._projected_reward(sim, player_id)
                        break
                    if node.priors is None:
                        node.priors = self._compute_priors(sim, pid, moves_by_key)
                    # restrict to the pruned/prioritized set when it applies here
                    candidate_keys = [k for k in moves_by_key if k in node.priors]
                    if not candidate_keys:
                        candidate_keys = list(moves_by_key)
                    key = self._select(
                        node, candidate_keys, node.priors, maximize=(pid == player_id)
                    )
                    fresh = key not in node.children
                    if not self._apply(sim, moves_by_key[key]):
                        node.invalid.add(key)
                        node.children.pop(key, None)
                        continue
                    child = node.children.get(key)
                    if child is None:
                        child = node.children[key] = _Node()
                    path.append(child)
                    node = child
                    if fresh:
                        reward = self._rollout(sim, player_id)
                        break
                for visited in path:
                    visited.visits += 1
                    visited.value += reward
        _SINK.seek(0)
        _SINK.truncate(0)

        best_key, best_visits = None, -1
        for key, child in root.children.items():
            if key in root_moves_by_key and child.visits > best_visits:
                best_key, best_visits = key, child.visits
        if best_key is None:
            return random.choice(moves)
        return root_moves_by_key[best_key]
