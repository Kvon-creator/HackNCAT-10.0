"""Smoke tests so the hands-on tester (demo/try_classifier.py) never silently breaks."""

import importlib.util

from conftest import REPO

spec = importlib.util.spec_from_file_location("try_classifier", REPO / "demo" / "try_classifier.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_env_file_loader_respects_shell_and_skips_blanks(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nOPENAI_MODEL=\"test-model\"\nOPENAI_API_KEY=\nexport OTHER_VAR='x'\nALREADY=file\n",
        encoding="utf-8",
    )
    for key in ("OPENAI_MODEL", "OPENAI_API_KEY", "OTHER_VAR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ALREADY", "shell")
    loaded = cli.load_env_file(env)
    import os
    assert os.environ["OPENAI_MODEL"] == "test-model"
    assert "OPENAI_API_KEY" not in os.environ  # blank values are not loaded
    assert os.environ["OTHER_VAR"] == "x"
    assert os.environ["ALREADY"] == "shell"  # shell wins
    assert sorted(loaded) == ["OPENAI_MODEL", "OTHER_VAR"]


def test_live_mode_without_key_exits_with_guidance(monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", REPO / "does-not-exist.env")
    monkeypatch.setattr(cli, "load_env_file", lambda path=None: [])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    import pytest
    with pytest.raises(SystemExit) as info:
        cli.make_provider("live")
    assert "backend/.env" in str(info.value)


def test_eval_fallback_and_canned_pass_all_fixtures(capsys):
    assert cli.main(["eval"]) == 0
    assert cli.main(["eval", "--mode", "canned"]) == 0
    assert "passed 13/13" in capsys.readouterr().out


def test_show_feed_list_and_try_run(capsys):
    cli.main(["list"])
    cli.main(["show", "intern-001", "--profile", "cs_internship"])
    cli.main(["feed", "--profile", "me_research"])
    cli.main(["try", "--subject", "Robotics talk", "--body", "Talk on December 9, 2026 at 4 p.m. ET in McNair Hall."])
    out = capsys.readouterr().out
    assert "relevance     : 80 / 100" in out
    assert "label check   : PASS" in out
    assert "2026-12-09T16:00:00-05:00" in out
