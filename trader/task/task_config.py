from trader.task.task_type import TaskType
import json

class TaskConfig:
    def __init__(self,type:TaskType,start_time:int=0,end_time:int=0):
        self.type=type
        self.start_time=start_time
        self.end_time=end_time

# '[{"task_type": "CHECK_KLINES", "start_time": 0,"end_time":0}]'
def parse_task_config(cfg)->[TaskConfig]:
    parsed_list = json.loads(cfg)
    ret=[]
    for tcd in parsed_list:
        tc=TaskConfig(tcd['task_type'])
        if "start_time" in tcd:
            tc.start_time=tcd['start_time']
        if "end_time" in tcd:
            tc.start_time=tcd['end_time']

        ret.append(tc)
