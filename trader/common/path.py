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

def is_filename_only(string):
    return not ("/" in string or "\\" in string) and os.path.basename(string) == string

def get_file_path(file_path):
    if is_filename_only(file_path):
        return os.path.join(GetDatasDir(),file_path)
    else:
        return file_path