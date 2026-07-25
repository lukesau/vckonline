"""Learned policy priors: score legal moves from (state, move) features.

The search's branch-attention has been a hand-written greedy softmax; this
net replaces it. Each candidate move is scored by a small numpy MLP over
[state features (agent.features.extract) || move features (below)], and a
softmax over the decision's legal moves yields prior probabilities. Trained
on MCTS root visit distributions recorded by `agent.selfplay --record-visits`
(grouped cross-entropy: match where deep search actually spent its visits).

The greedy VP-equivalent value of each move is included AS A FEATURE, so the
net learns residual corrections to the old prior rather than starting from
nothing.
"""

import numpy as np

DEFAULT_POLICY_PATH = "agent/models/policy_v1.npz"

ACTION_TYPES = (
    "take_resource",
    "hire_citizen",
    "build_domain",
    "slay_monster",
    "act_on_required_action",
    "submit_concurrent_action",
    "finalize_roll",
)
RESOURCE_KEYS = ("gold", "strength", "magic", "map")
MONSTER_TYPES = ("Boss", "Minion", "Beast", "Titan")

# one-hot action (7) + other (1) + resource one-hot (4) + payment block (6)
# + card block (13) + greedy value (1)
N_MOVE_FEATURES = 8 + 4 + 6 + 13 + 1


def _find_top(grid, id_attr, card_id):
    for stack in grid or []:
        if stack and getattr(stack[-1], id_attr, None) == card_id:
            return stack[-1]
    return None


def _target_card(game, move):
    at = move.get("action_type")
    if at == "hire_citizen":
        return _find_top(game.citizen_grid, "citizen_id", move.get("citizen_id"))
    if at == "build_domain":
        return _find_top(game.domain_grid, "domain_id", move.get("domain_id"))
    if at == "slay_monster":
        if move.get("monster_id") is not None:
            return _find_top(game.monster_grid, "monster_id", move.get("monster_id"))
        return _find_top(game.monster_grid, "event_id", move.get("event_id"))
    return None


def move_features(game, player, move, greedy_value=0.0):
    """Fixed-length encoding of one legal move (defensive: unknown shapes
    degrade to the action-type one-hot + greedy value, never raise)."""
    vec = np.zeros(N_MOVE_FEATURES, dtype=np.float32)
    at = move.get("action_type")
    try:
        idx = ACTION_TYPES.index(at)
    except ValueError:
        idx = len(ACTION_TYPES)  # "other"
    vec[idx] = 1.0
    base = 8

    res = str(move.get("resource") or "")
    for i, key in enumerate(RESOURCE_KEYS):
        if res == key:
            vec[base + i] = 1.0
    base += 4

    pay = move.get("payment") or {}
    g = int(pay.get("gold") or 0)
    s = int(pay.get("strength") or 0)
    m = int(pay.get("magic") or 0)
    vec[base + 0] = g / 10.0
    vec[base + 1] = s / 10.0
    vec[base + 2] = m / 10.0
    vec[base + 3] = (g + s + m) / 10.0
    if player is not None:
        if g and g >= int(getattr(player, "gold_score", 0) or 0):
            vec[base + 4] = 1.0
        if s and s >= int(getattr(player, "strength_score", 0) or 0):
            vec[base + 5] = 1.0
    base += 6

    card = _target_card(game, move) if game is not None else None
    if card is not None:
        vec[base + 0] = int(getattr(card, "vp_reward", 0) or 0) / 10.0
        for i, role in enumerate(("shadow", "holy", "soldier", "worker")):
            vec[base + 1 + i] = int(getattr(card, f"{role}_count", 0) or 0) / 4.0
        mtype = getattr(card, "monster_type", None)
        for i, t in enumerate(MONSTER_TYPES):
            if mtype == t:
                vec[base + 5 + i] = 1.0
        vec[base + 9] = int(getattr(card, "gold_reward", 0) or 0) / 5.0
        vec[base + 10] = int(getattr(card, "strength_reward", 0) or 0) / 5.0
        vec[base + 11] = int(getattr(card, "magic_reward", 0) or 0) / 5.0
        cost = (
            int(getattr(card, "gold_cost", 0) or 0)
            + int(getattr(card, "strength_cost", 0) or 0)
            + int(getattr(card, "magic_cost", 0) or 0)
        )
        vec[base + 12] = cost / 10.0
    base += 13

    vec[base] = float(np.clip(greedy_value / 10.0, -3.0, 3.0))
    return vec


def featurize_decision(game, pid, moves, greedy=None, state_vec=None):
    """(state_vec, move_matrix) for one decision. `greedy` supplies the
    per-move VP-equivalent values (falls back to zeros when unavailable)."""
    from agent.features import extract

    if state_vec is None:
        state_vec = extract(game, pid)
    values = None
    if greedy is not None:
        try:
            values = greedy.move_values(game, pid, moves)
        except Exception:
            values = None
    if values is None:
        values = [0.0] * len(moves)
    player = next((p for p in game.player_list if p.player_id == pid), None)
    mat = np.stack([
        move_features(game, player, move, greedy_value=value)
        for move, value in zip(moves, values)
    ])
    return state_vec.astype(np.float32), mat.astype(np.float32)


def _segment_softmax(z, starts):
    """Softmax within contiguous segments; `starts` includes the end offset."""
    p = np.empty_like(z)
    for a, b in zip(starts[:-1], starts[1:]):
        seg = z[a:b]
        seg = np.exp(seg - seg.max())
        p[a:b] = seg / seg.sum()
    return p


class PolicyNet:
    def __init__(self, n_state, n_move=N_MOVE_FEATURES, n_hidden=64, seed=0):
        n_in = n_state + n_move
        rng = np.random.default_rng(seed)
        self.w1 = rng.normal(0, np.sqrt(2.0 / n_in), (n_in, n_hidden)).astype(np.float32)
        self.b1 = np.zeros(n_hidden, dtype=np.float32)
        self.w2 = rng.normal(0, np.sqrt(2.0 / n_hidden), (n_hidden, 1)).astype(np.float32)
        self.b2 = np.zeros(1, dtype=np.float32)
        self.n_state = n_state
        self.n_move = n_move

    # ---- inference -----------------------------------------------------

    def _logits(self, x):
        h = np.maximum(x @ self.w1 + self.b1, 0.0)
        return (h @ self.w2 + self.b2)[:, 0], h

    def score(self, state_vec, move_matrix):
        """Prior probabilities over one decision's candidate moves."""
        x = np.concatenate(
            [np.repeat(state_vec[None, :], len(move_matrix), axis=0), move_matrix],
            axis=1,
        )
        z, _ = self._logits(x)
        z = np.exp(z - z.max())
        return z / z.sum()

    # ---- training ------------------------------------------------------

    def train(self, states, moves, starts, targets, epochs=30, batch_decisions=256,
              lr=1e-3, val_frac=0.1, seed=0, log=print):
        """states: D x n_state; moves: C x n_move (contiguous per decision);
        starts: D+1 offsets into moves/targets; targets: C (sums to 1/group)."""
        rng = np.random.default_rng(seed)
        n_dec = len(starts) - 1
        order = rng.permutation(n_dec)
        n_val = int(n_dec * val_frac)
        val_ids, train_ids = order[:n_val], order[n_val:]

        params = [self.w1, self.b1, self.w2, self.b2]
        mom = [np.zeros_like(p) for p in params]
        vel = [np.zeros_like(p) for p in params]
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        step = 0

        def _gather(ids):
            xs, ts, seg_starts, seg_state = [], [], [0], []
            for d in ids:
                a, b = starts[d], starts[d + 1]
                xs.append(moves[a:b])
                ts.append(targets[a:b])
                seg_state.append(np.repeat(states[d][None, :], b - a, axis=0))
                seg_starts.append(seg_starts[-1] + (b - a))
            x = np.concatenate(
                [np.concatenate(seg_state), np.concatenate(xs)], axis=1
            )
            return x, np.concatenate(ts), np.asarray(seg_starts)

        def _eval(ids):
            if not len(ids):
                return 0.0, 0.0
            x, t, seg = _gather(ids)
            z, _ = self._logits(x)
            p = _segment_softmax(z, seg)
            ce = 0.0
            top1 = 0
            for a, b in zip(seg[:-1], seg[1:]):
                ce -= float(np.sum(t[a:b] * np.log(p[a:b] + 1e-9)))
                top1 += int(np.argmax(p[a:b]) == np.argmax(t[a:b]))
            return ce / len(ids), top1 / len(ids)

        for epoch in range(1, epochs + 1):
            idx = rng.permutation(len(train_ids))
            for start in range(0, len(train_ids), batch_decisions):
                ids = train_ids[idx[start:start + batch_decisions]]
                x, t, seg = _gather(ids)
                z, h = self._logits(x)
                p = _segment_softmax(z, seg)
                dz = ((p - t) / len(ids))[:, None]
                dw2 = h.T @ dz
                db2 = dz.sum(axis=0)
                dh = dz @ self.w2.T
                dh[h <= 0] = 0.0
                dw1 = x.T @ dh
                db1 = dh.sum(axis=0)
                grads = [dw1, db1, dw2, db2]
                step += 1
                for i, (p_, g) in enumerate(zip(params, grads)):
                    mom[i] = beta1 * mom[i] + (1 - beta1) * g
                    vel[i] = beta2 * vel[i] + (1 - beta2) * g * g
                    m_hat = mom[i] / (1 - beta1 ** step)
                    v_hat = vel[i] / (1 - beta2 ** step)
                    p_ -= lr * m_hat / (np.sqrt(v_hat) + eps)
            if epoch % 5 == 0 or epoch == epochs:
                ce, top1 = _eval(val_ids)
                log(f"  epoch {epoch:3}: val CE {ce:.4f}  val top-1 {top1:.3f}")
        return self

    # ---- persistence ---------------------------------------------------

    def save(self, path):
        np.savez(path, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2,
                 n_state=self.n_state, n_move=self.n_move)

    @classmethod
    def load(cls, path):
        data = np.load(path)
        net = cls.__new__(cls)
        net.w1, net.b1 = data["w1"], data["b1"]
        net.w2, net.b2 = data["w2"], data["b2"]
        net.n_state = int(data["n_state"])
        net.n_move = int(data["n_move"])
        return net
