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

Parallelism: workers>1 runs root-parallel MCTS via ProcessPoolExecutor — each
worker builds an independent tree for a share of the iteration budget; visit
counts at the root are summed. That uses real multiple cores (unlike threads
under the GIL) without sharing a mutable tree across processes.
"""

import contextlib
import io
import math
import random
from concurrent.futures import ProcessPoolExecutor

from agent.headless import acting_player_ids, advance, apply_move, clone_game, legal_moves
from agent.move_summary import move_key
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
    return move_key(move)


def _effect_key(move):
    """Move identity ignoring the payment split, so alternative payments for
    the same purchase count as one effect when pruning to top_k."""
    if "payment" not in (move or {}):
        return move_key(move)
    return move_key({k: v for k, v in move.items() if k != "payment"})


def _biased_random_move(moves):
    builders = [
        m for m in moves
        if m.get("action_type") in ("hire_citizen", "build_domain", "slay_monster")
    ]
    if builders and random.random() < 0.75:
        return random.choice(builders)
    return random.choice(moves)


def _split_budget(total, workers):
    """Distribute total iterations across workers (remainder to the first workers)."""
    workers = max(1, int(workers))
    total = max(0, int(total))
    base = total // workers
    rem = total % workers
    return [base + (1 if i < rem else 0) for i in range(workers)]


def _parallel_worker(payload):
    """Top-level worker entry (must be picklable for ProcessPoolExecutor)."""
    save_dict, player_id, moves, iterations, cfg, seed = payload
    if seed is not None:
        random.seed(seed)
    from game_serialization import deserialize_save_dict_to_game

    game = deserialize_save_dict_to_game(save_dict)
    game.sim_mode = True
    # workers=1 so the child search stays in-process
    policy = MCTSPolicy(workers=1, **cfg)
    return policy._root_search(game, player_id, moves, iterations)


class MCTSPolicy:
    name = "mcts"

    def __init__(self, iterations=100, exploration=1.5, rollout_cap=250, descent_cap=400,
                 rollout_epsilon=0.15, top_k=12, prior_temperature=2.0, determinize=True,
                 workers=1, value_path=None, parallel_mode="root"):
        self.iterations = iterations
        self.exploration = exploration
        self.rollout_cap = rollout_cap
        self.descent_cap = descent_cap
        self.rollout_epsilon = rollout_epsilon
        self.top_k = top_k
        self.prior_temperature = prior_temperature
        self.determinize = determinize
        self.workers = max(1, int(workers))
        # How to spend `workers`: "root" = independent full trees merged by
        # visits; "halving" = sequential halving (phase 1 partitions the root
        # moves across workers for deep non-redundant screening, phase 2 gives
        # every worker the top finalists for parallel deep verification).
        # Measured: at equal budget, root-splitting dilutes depth (800x8 lost
        # 6-14 to 800x1) while depth itself pays (1000x1 beat 400x1 14-6);
        # halving exists to buy that depth back at parallel wall-clock.
        self.parallel_mode = parallel_mode if parallel_mode in ("root", "halving") else "root"
        self._greedy = GreedyPolicy()
        self.last_decision = None
        self._pool = None
        # Learned leaf evaluator (self-play value net). When set, expansion
        # leaves are scored by the net instead of playing a rollout — the
        # first learned component swapped into the search. Stored as a path
        # so root-parallel workers can load it themselves (picklable config).
        self.value_path = value_path
        self._value_net = None
        if value_path:
            from agent.value_net import ValueNet

            self._value_net = ValueNet.load(value_path)

    def _leaf_value(self, game, root_pid):
        from agent.features import extract

        try:
            return self._value_net.predict_one(extract(game, root_pid))
        except Exception:
            return self._projected_reward(game, root_pid)

    def _config_for_worker(self):
        return {
            "iterations": self.iterations,
            "exploration": self.exploration,
            "rollout_cap": self.rollout_cap,
            "descent_cap": self.descent_cap,
            "rollout_epsilon": self.rollout_epsilon,
            "top_k": self.top_k,
            "prior_temperature": self.prior_temperature,
            "determinize": self.determinize,
            "value_path": self.value_path,
        }

    def _get_pool(self):
        if self.workers <= 1:
            return None
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.workers)
        return self._pool

    def close(self):
        """Shut down the worker pool (optional; process exit also cleans up)."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

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
        to the top_k moves so search budget concentrates where it matters.

        Pruning counts distinct EFFECTS, not raw moves: alternative payment
        splits of the same purchase share one top_k slot (all kept splits stay
        in the prior with their own weight), so enumerating gold+magic splits
        cannot crowd genuinely different moves out of the search."""
        keys = list(moves_by_key)
        moves = [moves_by_key[k] for k in keys]
        values = self._greedy.move_values(sim, pid, moves)
        if values is None:
            p = 1.0 / len(keys)
            return {k: p for k in keys}
        ranked = sorted(zip(keys, values), key=lambda kv: -kv[1])
        kept, kept_groups = [], set()
        for k, v in ranked:
            group = _effect_key(moves_by_key[k])
            if group not in kept_groups:
                if len(kept_groups) >= self.top_k:
                    continue
                kept_groups.add(group)
            kept.append((k, v))
        top = kept[0][1]
        weights = {k: math.exp((v - top) / self.prior_temperature) for k, v in kept}
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

    def _root_search(self, game, player_id, moves, iterations):
        """Run ``iterations`` of search; return root stats and ranked candidates."""
        root = _Node()
        root_moves_by_key = {_move_key(m): m for m in moves}

        with contextlib.redirect_stdout(_SINK):
            for _ in range(iterations):
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
                        if self._value_net is not None and sim.phase != "game_over":
                            reward = self._leaf_value(sim, player_id)
                        else:
                            reward = self._rollout(sim, player_id)
                        break
                for visited in path:
                    visited.visits += 1
                    visited.value += reward
        _SINK.seek(0)
        _SINK.truncate(0)

        priors = root.priors
        if priors is None:
            priors = self._compute_priors(game, player_id, root_moves_by_key)
        by_key = {}
        for key, child in root.children.items():
            if key not in root_moves_by_key:
                continue
            by_key[key] = {
                "move": root_moves_by_key[key],
                "key": key,
                "visits": int(child.visits),
                "value": float(child.value),
            }
        return self._build_search_result(by_key, priors, root_moves_by_key, iterations)

    def _build_search_result(self, by_key, priors, root_moves_by_key, iterations):
        uniform = 1.0 / max(len(root_moves_by_key), 1)
        total_visits = sum(entry["visits"] for entry in by_key.values())
        candidates = []
        for key, entry in by_key.items():
            visits = entry["visits"]
            q = entry["value"] / visits if visits else 0.5
            prior = (priors or {}).get(key, uniform)
            candidates.append({
                "move": entry["move"],
                "key": key,
                "visits": visits,
                "visit_pct": (100.0 * visits / total_visits) if total_visits else 0.0,
                "q": q,
                "prior": prior,
            })
        candidates.sort(key=lambda c: (-c["visits"], -c["q"]))
        return {
            "by_key": by_key,
            "candidates": candidates,
            "iterations": iterations,
            "total_visits": total_visits,
            "priors": priors,
        }

    def _root_visits(self, game, player_id, moves, iterations):
        """Backward-compatible visit-count map from a root search."""
        result = self._root_search(game, player_id, moves, iterations)
        return {key: entry["visits"] for key, entry in result["by_key"].items()}

    def _parallel_root_search(self, game, player_id, moves):
        """Root-parallel search: independent trees, merge visit/value totals."""
        from game_serialization import serialize_game_to_save_dict

        budgets = [b for b in _split_budget(self.iterations, self.workers) if b > 0]
        if not budgets:
            return self._build_search_result({}, {}, {_move_key(m): m for m in moves}, 0)
        if len(budgets) == 1:
            return self._root_search(game, player_id, moves, budgets[0])

        save_dict = serialize_game_to_save_dict(game)
        cfg = self._config_for_worker()
        cfg.pop("iterations", None)
        base_seed = random.randrange(1 << 30)
        payloads = [
            (save_dict, player_id, moves, budget, cfg, base_seed + i)
            for i, budget in enumerate(budgets)
        ]
        pool = self._get_pool()
        root_moves_by_key = {_move_key(m): m for m in moves}
        merged = {}
        for partial in pool.map(_parallel_worker, payloads):
            for key, entry in partial.get("by_key", {}).items():
                if key not in root_moves_by_key:
                    continue
                bucket = merged.setdefault(key, {"visits": 0, "value": 0.0, "move": entry["move"]})
                bucket["visits"] += entry["visits"]
                bucket["value"] += entry["value"]
        priors = self._compute_priors(game, player_id, root_moves_by_key)
        return self._build_search_result(merged, priors, root_moves_by_key, self.iterations)

    def _parallel_root_visits(self, game, player_id, moves):
        """Root-parallel search: independent trees, sum visit counts."""
        result = self._parallel_root_search(game, player_id, moves)
        return {key: entry["visits"] for key, entry in result["by_key"].items()}

    # ---- sequential halving (partitioned parallel search) ---------------

    @staticmethod
    def _partition_by_prior(keys, priors, buckets):
        """Disjoint prior-balanced buckets: highest-prior key goes to the
        lightest bucket, so strong candidates spread across workers instead
        of piling into one."""
        buckets = max(1, min(int(buckets), len(keys)))
        out = [[] for _ in range(buckets)]
        loads = [0.0] * buckets
        for k in sorted(keys, key=lambda k: -priors.get(k, 0.0)):
            i = loads.index(min(loads))
            out[i].append(k)
            loads[i] += priors.get(k, 0.0)
        return [b for b in out if b]

    def _halving_root_search(self, game, player_id, moves, finalists_cap=4):
        """Two-phase partitioned search (see __init__ for rationale).

        Phase 1 spends half the budget with each worker searching a DISJOINT
        prior-balanced subset of the (top_k-pruned) root moves — no cross-
        worker redundancy. Phase 2 spends the rest with every worker deep-
        verifying the same top-Q finalists under different determinization
        seeds. Final stats: phase sums (finalists get both phases' visits, so
        `chosen = max visits` still lands on a finalist)."""
        from game_serialization import serialize_game_to_save_dict

        root_moves_by_key = {_move_key(m): m for m in moves}
        priors = self._compute_priors(game, player_id, root_moves_by_key)
        kept = [k for k in root_moves_by_key if k in priors]
        if not kept:
            return self._build_search_result({}, priors, root_moves_by_key, 0)

        pool = self._get_pool()
        save_dict = serialize_game_to_save_dict(game)
        cfg = self._config_for_worker()
        cfg.pop("iterations", None)
        base_seed = random.randrange(1 << 30)
        phase_budget = max(1, self.iterations // 2)

        # Every worker runs the same per-worker budget so phase-1 wall-clock
        # matches root mode. Workers cycle over the buckets: when there are
        # fewer buckets than workers, same-bucket workers differ by seed and
        # their stats merge (bounded redundancy, only where the root is
        # narrow and redundancy is unavoidable anyway).
        buckets = self._partition_by_prior(kept, priors, self.workers)
        per_worker_1 = max(1, phase_budget // self.workers)
        payloads = [
            (save_dict, player_id,
             [root_moves_by_key[k] for k in buckets[i % len(buckets)]],
             per_worker_1, cfg, base_seed + i)
            for i in range(self.workers)
        ]
        phase1 = {}
        for partial in pool.map(_parallel_worker, payloads):
            for key, entry in partial.get("by_key", {}).items():
                if key not in root_moves_by_key:
                    continue
                bucket = phase1.setdefault(key, {"visits": 0, "value": 0.0})
                bucket["visits"] += int(entry["visits"])
                bucket["value"] += float(entry["value"])

        def q_of(entry):
            v = entry["visits"]
            return entry["value"] / v if v else 0.5

        finalists = sorted(phase1, key=lambda k: -q_of(phase1[k]))
        finalists = finalists[: max(2, min(finalists_cap, len(finalists)))]
        finalist_moves = [root_moves_by_key[k] for k in finalists]

        per_worker_2 = max(1, (self.iterations - phase_budget) // self.workers)
        payloads = [
            (save_dict, player_id, finalist_moves, per_worker_2, cfg,
             base_seed + 7919 + i)
            for i in range(self.workers)
        ]
        by_key = {
            k: {"move": root_moves_by_key[k], "key": k,
                "visits": int(e["visits"]), "value": float(e["value"])}
            for k, e in phase1.items()
        }
        for partial in pool.map(_parallel_worker, payloads):
            for key, entry in partial.get("by_key", {}).items():
                if key not in root_moves_by_key:
                    continue
                bucket = by_key.setdefault(
                    key, {"move": root_moves_by_key[key], "key": key, "visits": 0, "value": 0.0}
                )
                bucket["visits"] += int(entry["visits"])
                bucket["value"] += float(entry["value"])
        return self._build_search_result(by_key, priors, root_moves_by_key, self.iterations)

    def analyze(self, game, player_id, moves):
        """Run search and record ranked root candidates on ``last_decision``."""
        if not moves:
            self.last_decision = {"policy": "mcts", "chosen": None, "candidates": []}
            return self.last_decision
        if len(moves) < 2:
            self.last_decision = {
                "policy": "mcts",
                "chosen": moves[0],
                "candidates": [],
                "trivial": True,
            }
            return self.last_decision

        if self.workers > 1 and self.parallel_mode == "halving":
            search = self._halving_root_search(game, player_id, moves)
        elif self.workers > 1:
            search = self._parallel_root_search(game, player_id, moves)
        else:
            search = self._root_search(game, player_id, moves, self.iterations)

        chosen = None
        best_visits = -1
        for entry in search["candidates"]:
            if entry["visits"] > best_visits:
                chosen = entry["move"]
                best_visits = entry["visits"]
        if chosen is None:
            chosen = random.choice(moves)

        self.last_decision = {
            "policy": "mcts",
            "chosen": chosen,
            "candidates": search["candidates"],
            "iterations": self.iterations,
            "workers": self.workers,
        }
        return self.last_decision

    def choose(self, game, view, player_id, moves):
        return self.analyze(game, player_id, moves)["chosen"]
