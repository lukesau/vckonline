"""Bot decision strategies."""

import random


class RandomStrategy:
    def pick(self, actions):
        if not actions:
            return None
        return random.choice(actions)
