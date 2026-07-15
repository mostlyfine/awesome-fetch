from _module_loader import load_module

jira_issue_fetcher = load_module("jira_issue_fetcher", "bin/jira_issue_fetcher.py")


def test_read_existing_timestamp_returns_none_when_file_missing(tmp_path):
    file_path = tmp_path / "PROJ-123.md"
    assert jira_issue_fetcher._read_existing_timestamp(file_path) is None


def test_read_existing_timestamp_decodes_json_encoded_value(tmp_path):
    file_path = tmp_path / "PROJ-123.md"
    file_path.write_text('---\ntimestamp: "2024-01-01T00:00:00.000+0900"\n---\n\nbody\n', encoding="utf-8")
    assert jira_issue_fetcher._read_existing_timestamp(file_path) == "2024-01-01T00:00:00.000+0900"


def test_should_skip_returns_true_when_timestamps_match():
    assert jira_issue_fetcher._should_skip("2024-01-01T00:00:00.000+0900", "2024-01-01T00:00:00.000+0900", force=False) is True


def test_should_skip_returns_false_when_timestamps_differ():
    assert jira_issue_fetcher._should_skip("2024-01-01T00:00:00.000+0900", "2024-02-01T00:00:00.000+0900", force=False) is False


def test_should_skip_returns_false_when_force_true_even_if_match():
    assert jira_issue_fetcher._should_skip("2024-01-01T00:00:00.000+0900", "2024-01-01T00:00:00.000+0900", force=True) is False


def test_issue_file_path_matches_naming_convention(tmp_path):
    file_path = jira_issue_fetcher._issue_file_path("PROJ-123", tmp_path)
    assert file_path == tmp_path / "PROJ-123.md"
