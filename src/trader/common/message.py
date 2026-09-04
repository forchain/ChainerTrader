from enum import Enum

class MessageType(Enum):
    EXIT = 0
    STR = 1
    TASK = 2
    STAT = 3
    BACKTRADER = 4


class Message:
    count:int=0
    def __init__(self,tp:MessageType,data=None,id=0):
        if id == 0:
            self.id=Message.count
        else:
            self.id=id

        Message.count+=1

        self.tp=tp
        self.data=data

    def get_id(self)->int:
        return self.id

    def get_data(self):
        return self.data

    def name(self):
        return f"{self.tp.name}({self.id})"

    def is_exit(self):
        return self.tp == MessageType.EXIT

    def is_task(self):
        return self.tp == MessageType.TASK

    def is_stat(self):
        return self.tp == MessageType.STAT

def new_exit_msg()->Message:
    return Message(MessageType.EXIT)

def new_str_msg(string:str)->Message:
    return Message(MessageType.STR,string)

def new_task_msg(data)->Message:
    return Message(MessageType.TASK,data)

def new_stat_msg(data,id=0)->Message:
    return Message(MessageType.STAT,data,id)