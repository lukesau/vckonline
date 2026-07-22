"""Small numpy MLP predicting P(viewer wins) from state features.

Deliberately dependency-light (numpy only): a 1-hidden-layer net trained with
Adam on binary cross-entropy. This is the first, bootstrap version of the
learned evaluator; it slots into MCTS at the leaf-evaluation attachment point
and can later be replaced by something bigger without touching the search.
"""

import numpy as np

DEFAULT_MODEL_PATH = "agent/models/value_v1.npz"


class ValueNet:
    def __init__(self, n_in, n_hidden=64, seed=0):
        rng = np.random.default_rng(seed)
        self.w1 = rng.normal(0, np.sqrt(2.0 / n_in), (n_in, n_hidden)).astype(np.float32)
        self.b1 = np.zeros(n_hidden, dtype=np.float32)
        self.w2 = rng.normal(0, np.sqrt(2.0 / n_hidden), (n_hidden, 1)).astype(np.float32)
        self.b2 = np.zeros(1, dtype=np.float32)

    # ---- inference -----------------------------------------------------

    def forward(self, x):
        h = np.maximum(x @ self.w1 + self.b1, 0.0)
        logit = h @ self.w2 + self.b2
        return 1.0 / (1.0 + np.exp(-logit)), h

    def predict(self, x):
        p, _ = self.forward(np.atleast_2d(x))
        return p[:, 0]

    def predict_one(self, x):
        return float(self.predict(x)[0])

    # ---- training ------------------------------------------------------

    def train(self, x, y, epochs=30, batch_size=256, lr=1e-3, val_frac=0.1,
              seed=0, log=print):
        rng = np.random.default_rng(seed)
        n = len(x)
        order = rng.permutation(n)
        x, y = x[order], y[order]
        n_val = int(n * val_frac)
        x_val, y_val = x[:n_val], y[:n_val]
        x_tr, y_tr = x[n_val:], y[n_val:]

        params = [self.w1, self.b1, self.w2, self.b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        step = 0
        for epoch in range(1, epochs + 1):
            idx = rng.permutation(len(x_tr))
            for start in range(0, len(x_tr), batch_size):
                batch = idx[start:start + batch_size]
                xb, yb = x_tr[batch], y_tr[batch][:, None]
                p, h = self.forward(xb)
                # BCE gradient through sigmoid: (p - y)
                dlogit = (p - yb) / len(xb)
                dw2 = h.T @ dlogit
                db2 = dlogit.sum(axis=0)
                dh = dlogit @ self.w2.T
                dh[h <= 0] = 0.0
                dw1 = xb.T @ dh
                db1 = dh.sum(axis=0)
                grads = [dw1, db1, dw2, db2]
                step += 1
                for i, (p_, g) in enumerate(zip(params, grads)):
                    m[i] = beta1 * m[i] + (1 - beta1) * g
                    v[i] = beta2 * v[i] + (1 - beta2) * g * g
                    m_hat = m[i] / (1 - beta1 ** step)
                    v_hat = v[i] / (1 - beta2 ** step)
                    p_ -= lr * m_hat / (np.sqrt(v_hat) + eps)
            if epoch % 5 == 0 or epoch == epochs:
                p_val = self.predict(x_val)
                bce = -np.mean(
                    y_val * np.log(p_val + 1e-9) + (1 - y_val) * np.log(1 - p_val + 1e-9)
                )
                acc = np.mean((p_val > 0.5) == (y_val > 0.5))
                log(f"  epoch {epoch:3}: val BCE {bce:.4f}  val acc {acc:.3f}")
        return self

    # ---- persistence ---------------------------------------------------

    def save(self, path):
        np.savez(path, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2)

    @classmethod
    def load(cls, path):
        data = np.load(path)
        net = cls.__new__(cls)
        net.w1, net.b1 = data["w1"], data["b1"]
        net.w2, net.b2 = data["w2"], data["b2"]
        return net
