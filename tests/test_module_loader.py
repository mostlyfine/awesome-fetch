from pathlib import Path

from _module_loader import load_module


def test_load_module_can_load_issue_fetcher():
    module = load_module("issue_fetcher_smoke", "bin/issue_fetcher.py")
    assert module.sanitize_filename("a/b:c") == "a_b_c"
