from pathlib import Path


def test_serve_sets_python_warning_filter_for_backtrader_invalid_escape_warning():
    repo_root = Path(__file__).resolve().parents[1]
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")

    assert 'PYTHONWARNINGS="ignore:invalid escape sequence"' in makefile
