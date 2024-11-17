import os

def GetProjectDir():
    baseDir = os.path.abspath(os.path.dirname(__file__))
    filePath = os.path.join(baseDir, './../../')
    return os.path.realpath(filePath)

def GetTraderDir():
    baseDir = os.path.abspath(os.path.dirname(__file__))
    filePath = os.path.join(baseDir, './../../trader')
    return os.path.realpath(filePath)

def GetDatasDir():
    baseDir = os.path.abspath(os.path.dirname(__file__))
    filePath = os.path.join(baseDir, './../../datas')
    return os.path.realpath(filePath)