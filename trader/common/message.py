from enum import Enum

class MessageType(Enum):
    EXIT = 0


class Message:
    count:int=0
    def __init__(self,tp:MessageType,data=None):
        self.id=Message.count
        Message.count+=1

        self.tp=tp
        self.data=data

    def get_id(self)->int:
        return self.id

    def get_data(self):
        return self.data

    def name(self):
        return f"{self.tp.name}({self.id})"


def new_exit_msg()->Message:
    return Message(MessageType.EXIT)