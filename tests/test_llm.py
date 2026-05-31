from __future__ import annotations

from autoresearch_os.llm import CentralReasoner, _load_api_key


def test_explicit_empty_api_key_disables_env_file_loading(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_API_KEY", raising=False)

    reasoner = CentralReasoner(api_key="", workspace=tmp_path)

    assert reasoner.enabled is False


def test_explicit_workspace_does_not_fall_back_to_cwd_env_file(tmp_path, monkeypatch) -> None:
    cwd = tmp_path / "cwd"
    workspace = tmp_path / "workspace"
    cwd.mkdir()
    workspace.mkdir()
    (cwd / ".env.local").write_text("OPENAI_API_KEY=sk-cwd\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_API_KEY", raising=False)

    assert _load_api_key(workspace) is None
