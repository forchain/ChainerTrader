import logging

from trader.common.common import NAME
from trader.common.config import Config
from trader.common.log_buffer import LogBuffer
from trader.common.log_tag import LogTag


class Logger:
    def __init__(self, cfg: Config, buffer_size: int = 100, enable_log_buffer: bool = False):
        self.cfg = cfg
        self.name = NAME
        self.logger = logging.getLogger(self.name)
        self.enable_log_buffer = enable_log_buffer
        if not self.enable_log_buffer:
            self.enable_log_buffer = cfg.is_server()

        if self.enable_log_buffer:
            self.log_buffer = LogBuffer(buffer_size)
        else:
            self.log_buffer = None

        self.logger.setLevel(cfg.log_level)
        self.initRoot()

    def setLevel(self, level):
        self.logger.setLevel(level)
        logging.getLogger("root").setLevel(level)

    def get_level(self) -> str:
        return logging.getLevelName(logging.getLogger("root").level)

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
        return self.name + ".log"

    def initRoot(self):
        if self.cfg.log_file:
            logging.basicConfig(
                filename=self.file_name(),
                filemode="a",
                level=self.cfg.log_level,
                format=formatter_str(),
            )
        else:
            logging.basicConfig(level=self.cfg.log_level, format=formatter_str())

        logging.info("Init root logger")

    def get_buffer_str(self) -> list[str]:
        if not self.enable_log_buffer or not self.log_buffer:
            return []
        return self.log_buffer.get_logs()

    def get_buffer_size(self):
        if not self.enable_log_buffer or not self.log_buffer:
            return 0
        return self.log_buffer.size()

    def is_buffer_empty(self):
        return self.get_buffer_size() == 0

    def info(self, msg: str, tag: LogTag = LogTag.GENERAl):
        if self.enable_log_buffer and self.log_buffer and tag != LogTag.PRIVATE and self.logger.isEnabledFor(logging.INFO):
            self.log_buffer.add(msg)

        self.logger.info(msg)

    def debug(self, msg: str, tag: LogTag = LogTag.GENERAl):
        if self.enable_log_buffer and self.log_buffer and tag != LogTag.PRIVATE and self.logger.isEnabledFor(logging.DEBUG):
            self.log_buffer.add(msg)

        self.logger.debug(msg)

    def error(self, msg: str, tag: LogTag = LogTag.GENERAl):
        if self.enable_log_buffer and self.log_buffer and tag != LogTag.PRIVATE and self.logger.isEnabledFor(logging.ERROR):
            self.log_buffer.add(msg)

        self.logger.error(msg)

    def warning(self, msg: str, tag: LogTag = LogTag.GENERAl):
        if self.enable_log_buffer and self.log_buffer and tag != LogTag.PRIVATE and self.logger.isEnabledFor(logging.WARNING):
            self.log_buffer.add(msg)

        self.logger.warning(msg)

    def add_log_buffer(self, msg: str, tag: LogTag = LogTag.GENERAl):
        if self.enable_log_buffer and self.log_buffer and tag != LogTag.PRIVATE and self.logger.isEnabledFor(logging.INFO):
            self.log_buffer.add(msg)


def get_formatter():
    return logging.Formatter(formatter_str())


def formatter_str():
    return "%(asctime)s[%(levelname)s:%(name)s] %(message)s"


def default() -> logging.Logger:
    return logging.getLogger("root")
