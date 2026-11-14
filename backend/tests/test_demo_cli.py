"""Smoke tests so the hands-on tester (demo/try_classifier.py) never silently breaks."""

import importlib.util

from conftest import REPO

spec = importlib.util.spec_from_file_location("try_classifier", REPO / "demo" / "try_classifier.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


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
