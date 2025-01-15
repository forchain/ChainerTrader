import logging

from trader.common.common import NAME
from trader.common.config import Config


class Logger:
    def __init__(self,cfg:Config):
        self.cfg=cfg
        self.name=NAME
        self.logger = logging.getLogger(self.name)

        self.logger.setLevel(cfg.log_level)

        self.initRoot()

    def setLevel(self,level):
        self.logger.setLevel(level)
        logging.getLogger("root").setLevel(level)

    def log(self):
        return self.logger

    def enableConsole(self):
        formatter = get_formatter()
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        # console_handler.setLevel(level)
        # 将处理器添加到记录器
        return console_handler

    def enableFile(self):
        if len(self.logger.handlers) != 1:
            return

        file_handler = logging.FileHandler(self.file_name())
        file_handler.setFormatter(get_formatter())
        # file_handler.setLevel(level)
        self.logger.addHandler(file_handler)
        return file_handler


    def file_name(self):
        return self.name + '.log'

    def initRoot(self):
        if self.cfg.log_file:
            logging.basicConfig(
                filename=self.file_name(),
                filemode='a',
                level=self.cfg.log_level,
                format=formatter_str()
            )
        else:
            logging.basicConfig(
                level=self.cfg.log_level,
                format=formatter_str()
            )

        logging.info("Init root logger")



def get_formatter():
    return logging.Formatter(formatter_str())

def formatter_str():
    return '%(asctime)s[%(levelname)s:%(name)s] %(message)s'

def default()->logging.Logger:
    return logging.getLogger("root")