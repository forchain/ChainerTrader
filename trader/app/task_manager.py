from trader.app.dynamic_task import DynamicTask
from trader.app.static_task import StaticTask


class TaskManager:
    def __init__(self,cfg,log):
        self.log = log
        self.cfg = cfg
        self.log.info(f"Init TaskManager")
        self.tasks = []

    def start(self):
        if self.cfg.data_file:
            self.tasks.append(StaticTask(self.cfg,self.log))
        if self.cfg.exchange:
            self.tasks.append(DynamicTask(self.cfg,self.log))

        for task in self.tasks:
            task.start()

    def stop(self):
        for task in self.tasks:
            task.stop()