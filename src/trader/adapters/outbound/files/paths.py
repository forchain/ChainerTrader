import os
import re

# ``paths.py`` now lives two directories deeper than the legacy ``common/path.py``
# (src/trader/adapters/outbound/files), so project-level lookups climb one more level.
_PROJECT_ROOT = "./../../../../../"
_DATA_DIR = "./../../../../../data"
_SCRIPTS_DIR = "./../../../../../scripts"
_CONFIGS_DIR = "./../../../../../configs"
_TRADER_DIR = "./../../../"


def _dir(relative: str) -> str:
    baseDir = os.path.abspath(os.path.dirname(__file__))
    return os.path.realpath(os.path.join(baseDir, relative))


def GetProjectDir():
    return _dir(_PROJECT_ROOT)


def GetTraderDir():
    return _dir(_TRADER_DIR)


def GetDataDir():
    return _dir(_DATA_DIR)


def GetScriptsDir():
    return _dir(_SCRIPTS_DIR)


def GetConfigsDir():
    return _dir(_CONFIGS_DIR)


def is_filename_only(string):
    return not ("/" in string or "\\" in string) and os.path.basename(string) == string


def is_like_file(string):
    return bool(re.match(r"^[a-zA-Z]:\\|/|.*\.[a-zA-Z0-9]+$", string))


def get_file_path(file_path):
    if not is_like_file(file_path):
        return file_path

    if is_filename_only(file_path):
        return os.path.join(GetDataDir(), file_path)
    if not os.path.isabs(file_path):
        project_path = os.path.join(GetProjectDir(), file_path)
        if os.path.exists(project_path):
            return project_path
    else:
        return file_path
    return file_path
