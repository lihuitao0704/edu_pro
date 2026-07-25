from pathlib import Path

import main


def test_resolve_server_port_falls_back_to_8001(monkeypatch):
    monkeypatch.setattr(main, "is_port_available", lambda port: port == 8001)
    monkeypatch.setattr(main, "release_workspace_listener", lambda port: False)

    assert main.resolve_server_port() == 8001


def test_resolve_server_port_fails_clearly_when_both_supported_ports_are_busy(monkeypatch):
    monkeypatch.setattr(main, "is_port_available", lambda _port: False)
    monkeypatch.setattr(main, "release_workspace_listener", lambda _port: False)

    try:
        main.resolve_server_port()
    except RuntimeError as exc:
        assert "8000" in str(exc) and "8001" in str(exc)
    else:
        raise AssertionError("an occupied 8001 must not be passed to Uvicorn")


def test_unknown_listener_is_not_terminated(monkeypatch):
    monkeypatch.setattr(main, "listener_command", lambda port: "python D:/other/app.py")

    assert main.release_workspace_listener(8000) is False


def test_frontend_build_is_skipped_when_dist_exists(monkeypatch, tmp_path: Path):
    (tmp_path / "frontend" / "dist").mkdir(parents=True)
    (tmp_path / "frontend" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    invoked = []
    monkeypatch.setattr(main.subprocess, "run", lambda *args, **kwargs: invoked.append(args))

    main.ensure_frontend_build(tmp_path)

    assert invoked == []


def test_advisor_workspace_routes_match_the_frontend_api_contract():
    assert str(main.app.url_path_for("advisor_chat")) == "/api/advisor"
    assert str(main.app.url_path_for("asset_allocation")) == "/api/advisor/allocation"
    assert str(main.app.url_path_for("holdings_analysis")) == "/api/advisor/holdings-analysis"
    assert str(main.app.url_path_for("recommendation_feedback", recommendation_id="1")) == "/api/advisor/recommendations/1/feedback"
