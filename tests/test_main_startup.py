from pathlib import Path

import main


def test_resolve_server_port_falls_back_to_8001(monkeypatch):
    monkeypatch.setattr(main, "is_port_available", lambda port: port == 8001)
    monkeypatch.setattr(main, "release_workspace_listener", lambda port: False)

    assert main.resolve_server_port() == 8001


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
