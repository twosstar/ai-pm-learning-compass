from scripts.audit_release import inspect_blob


def test_audit_detects_staged_secret_bytes_without_echoing_values():
    secret = b"sk-" + b"dummy" * 8
    issues = inspect_blob("app/example.py", b"credential = '" + secret + b"'", (secret,))
    assert {issue["kind"] for issue in issues} == {
        "provider credential format", "matches a configured local secret",
    }
    assert secret.decode() not in str(issues)


def test_audit_rejects_private_notes_env_backups_and_databases():
    for name in ("MEMORY.md", ".env.local", "data/backup.db", "sources/course.txt", "logs/session.txt"):
        assert inspect_blob(name, b"private content"), name
    assert inspect_blob(".env.example", b"LLM_API_KEY=\n") == []
    assert inspect_blob(".env.example", b"LLM_API_KEY=nonempty-example-value\n")


def test_audit_detects_personal_paths_and_only_exempts_exact_negative_test_url():
    path = "C:" + "/Users/" + "sample-person/private/course.txt"
    assert inspect_blob("README.md", path.encode())[0]["kind"] == "personal absolute path"
    fixture = "https://" + "user:" + "password@" + "model.example/v1"
    assert inspect_blob("tests/test_model_settings.py", fixture.encode()) == []
    assert inspect_blob("app/anything.py", fixture.encode())
