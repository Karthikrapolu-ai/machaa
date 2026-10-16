"""Files a public repository must keep, and files it must not contain."""

from pathlib import Path


def test_license_stays_apache_2():
    text = Path("LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0" in text


def test_gitignore_covers_runtime_state():
    text = Path(".gitignore").read_text(encoding="utf-8")
    for needle in (".env", "data/", "browser-profile/", "*.sqlite3", "*.log"):
        assert needle in text


def test_env_example_has_no_secrets():
    text = Path(".env.example").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "api_key=" not in lowered
    assert "sk-" not in text
    assert "akia" not in lowered
    assert "begin private" not in lowered
    assert "password=" not in lowered


def test_compose_is_a_restricted_local_worker():
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "docker.sock" not in text
    assert "privileged: true" not in text
    assert "127.0.0.1:8787:8787" in text
    assert 'user: "1000:1000"' in text
    assert "cap_drop:" in text
    assert "no-new-privileges:true" in text
    assert "mem_limit: 2g" in text
    assert "read_only: true" in text
    assert "machaa-data:/data" in text
    assert "~/" not in text
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "USER machaa" in dockerfile
    assert "useradd" in dockerfile
    assert "--with-deps chromium" in dockerfile


def test_start_scripts_exist_for_each_desktop():
    assert Path("start.sh").read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    assert "docker compose up --build" in Path("start.bat").read_text(encoding="utf-8")
    assert "docker compose up --build" in Path("start.ps1").read_text(encoding="utf-8")


def test_docs_name_the_future_work_and_the_guardian():
    readme = Path("README.md").read_text(encoding="utf-8")
    roadmap = Path("ROADMAP.md").read_text(encoding="utf-8")
    security = Path("SECURITY.md").read_text(encoding="utf-8")
    contributing = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "MACHAA" in readme
    assert "127.0.0.1:8787" in readme
    assert "Windows" in readme and "Mac" in readme and "Linux" in readme
    assert "open Machaa" in roadmap
    assert "pgvector" in roadmap
    assert "personal Chrome" in security
    assert "Apache-2.0" in contributing or "Apache" in contributing
