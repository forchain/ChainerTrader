from asyncio import Queue
from logging import Logger

from trader.common.common import sleep
from trader.common.config import Config
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig


class DebugTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
    ):
        super().__init__(tcfg, cfg, log)

    def name(self):
        return f"{self.tcfg.id}.{self.type().name}"

    async def start(self, queue: Queue):
        super().start(queue)

        count = self.tcfg.limit

        while count > 0:
            count -= 1

            if self.quit.is_set():
                self.log.info(f"Exit {self.name()}. process={count}/{self.tcfg.limit}")
                return False

            self.log.info(f"Run {self.name()}. process={count}/{self.tcfg.limit}")

            await sleep(self.log, 1)

        return True
