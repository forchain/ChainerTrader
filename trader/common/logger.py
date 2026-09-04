import logging

class Logger:
    def __init__(self,name, level=logging.DEBUG):
        self.name=name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        if len(self.logger.handlers) <= 0:
            self.enableConsole()

    def setLevel(self,level):
        self.logger.setLevel(level)

    def log(self):
        return self.logger

    def enableConsole(self):
        formatter = get_formatter()
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        # console_handler.setLevel(level)
        # 将处理器添加到记录器
        self.logger.addHandler(console_handler)

    def enableFile(self):
        if len(self.logger.handlers) != 1:
            return

        file_handler = logging.FileHandler(self.name + '.log')
        file_handler.setFormatter(get_formatter())
        # file_handler.setLevel(level)
        self.logger.addHandler(file_handler)

def get_formatter():
    return logging.Formatter('%(asctime)s[%(levelname)s] %(message)s')