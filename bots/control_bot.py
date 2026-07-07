"""Control bot — random baseline for comparison."""

from bots.loop import BotRunner
from bots.strategy import RandomStrategy


class ControlBot(BotRunner):
    def __init__(self, client=None, poll_interval=1.5, log=None):
        super().__init__(
            client=client,
            strategy=RandomStrategy(),
            poll_interval=poll_interval,
            log=log,
        )
