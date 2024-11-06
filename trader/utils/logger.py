import logging

class Logger:
    def __init__(self,name, level):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        console_handler = logging.StreamHandler()
        #console_handler.setLevel(level)

        file_handler = logging.FileHandler(name+'.log')
        #file_handler.setLevel(level)

        formatter = logging.Formatter('%(asctime)s[%(levelname)s] %(message)s')
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # 将处理器添加到记录器
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def setLevel(self,level):
        self.logger.setLevel(level)

    def log(self):
        return self.logger
