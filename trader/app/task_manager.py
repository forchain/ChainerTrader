from trader.app.app import App
from trader.app.dynamic_task import DynamicTask
from trader.app.static_task import StaticTask


class TaskManager:
    def __init__(self,app:App):
        self.app=app
        self.log = app.log()
        self.cfg = app.config()
        self.log.info(f"Init TaskManager")
        self.tasks = []

    def start(self):
        if not self.cfg.checkSymbolsIntervals():
            self.log.error(f"symbols intervals error")
            return

        if self.cfg.data_file:
            self.tasks.append(StaticTask(self.cfg,self.log))
        if self.cfg.exchange:
            self.tasks.append(DynamicTask(self.app))

        for task in self.tasks:
            task.start()

    def stop(self):
        for task in self.tasks:
            task.stop()