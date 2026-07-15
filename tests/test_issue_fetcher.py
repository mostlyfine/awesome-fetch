from _module_loader import load_module

issue_fetcher = load_module("issue_fetcher", "bin/issue_fetcher.py")


def test_read_existing_timestamp_returns_none_when_file_missing(tmp_path):
    file_path = tmp_path / "owner-repo-1.md"
    assert issue_fetcher._read_existing_timestamp(file_path) is None


def test_read_existing_timestamp_returns_none_when_no_timestamp_field(tmp_path):
    file_path = tmp_path / "owner-repo-1.md"
    file_path.write_text('---\ntype: "GitHub Issue"\n---\n\nbody\n', encoding="utf-8")
    assert issue_fetcher._read_existing_timestamp(file_path) is None


def test_read_existing_timestamp_decodes_json_encoded_value(tmp_path):
    file_path = tmp_path / "owner-repo-1.md"
    file_path.write_text('---\ntimestamp: "2024-01-01T00:00:00Z"\n---\n\nbody\n', encoding="utf-8")
    assert issue_fetcher._read_existing_timestamp(file_path) == "2024-01-01T00:00:00Z"


def test_should_skip_returns_false_when_no_existing_timestamp():
    assert issue_fetcher._should_skip(None, "2024-01-01T00:00:00Z", force=False) is False


def test_should_skip_returns_true_when_timestamps_match():
    assert issue_fetcher._should_skip("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", force=False) is True


def test_should_skip_returns_false_when_timestamps_differ():
    assert issue_fetcher._should_skip("2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z", force=False) is False


def test_should_skip_returns_false_when_force_true_even_if_match():
    assert issue_fetcher._should_skip("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z", force=True) is False


def test_issue_file_path_matches_naming_convention(tmp_path):
    file_path = issue_fetcher._issue_file_path("owner", "repo", "123", tmp_path)
    assert file_path == tmp_path / "owner-repo-123.md"
