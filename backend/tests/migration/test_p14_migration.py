# tests/migration/test_p14_migration.py
"""
Phase P14 verification tests:
1. Fake LLM provider configuration and production refusal.
2. Repository secret hygiene (no .env, keys, venv, dumps tracked).
3. Requirements pinning and .gitattributes line-ending configuration.
4. Database bootstrap script structure.
5. Automation script existence and executable syntax.
"""
import os
from pathlib import Path
import subprocess
import pytest
from app.llm import build_llm
from app.llm_fake import FakeLLM
from app.main import startup_check
from app.settings import Settings, settings

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_fake_llm_provider_behavior():
    """LLM_PROVIDER=fake returns FakeLLM instance in development."""
    orig_provider = settings.llm_provider
    try:
        settings.llm_provider = "fake"
        client = build_llm()
        assert isinstance(client, FakeLLM)
    finally:
        settings.llm_provider = orig_provider


def test_production_refuses_fake_llm():
    """ENV=production strictly refuses LLM_PROVIDER=fake."""
    with pytest.raises(RuntimeError, match="LLM_PROVIDER=fake is not allowed when ENV=production"):
        Settings(
            env="production",
            llm_provider="fake",
            payments_mode="razorpay",
            razorpay_key_id="rzp_live_123",
            razorpay_key_secret="secret_123",
            razorpay_webhook_secret="whsec_123",
        )


@pytest.mark.asyncio
async def test_startup_check_refuses_fake_llm_in_production():
    """FastAPI startup_check rejects LLM_PROVIDER=fake in production."""
    orig_env = settings.env
    orig_llm = settings.llm_provider
    orig_pay = settings.payments_mode
    try:
        settings.env = "production"
        settings.llm_provider = "fake"
        settings.payments_mode = "razorpay"
        with pytest.raises(RuntimeError, match="LLM_PROVIDER=fake is not allowed"):
            await startup_check()
    finally:
        settings.env = orig_env
        settings.llm_provider = orig_llm
        settings.payments_mode = orig_pay


def test_git_tracked_files_secret_hygiene():
    """Verify that git tracks zero sensitive files (.env, keys, dumps, venv, vector store)."""
    res = subprocess.run(["git", "ls-files"], cwd=str(REPO_ROOT), capture_output=True, text=True, check=True)
    tracked_files = res.stdout.strip().splitlines()

    forbidden_patterns = [
        r"^\.env$",
        r"\.pem$",
        r"\.key$",
        r"^venv/",
        r"^node_modules/",
        r"gympro_vector_store/",
        r"\.dump$",
        r"\.sql\.tar$",
        r"mailpit\.exe$",
        r"^mail_outbox/",
    ]

    import re
    violations = []
    for f in tracked_files:
        for pat in forbidden_patterns:
            if re.search(pat, f, re.IGNORECASE):
                violations.append((f, pat))

    assert not violations, f"Sensitive or generated files are tracked by git: {violations}"


def test_database_bootstrap_script_integrity():
    """backend/db/00_create_databases.sql creates gympro and gympro_test."""
    sql_file = REPO_ROOT / "backend" / "db" / "00_create_databases.sql"
    assert sql_file.exists(), "00_create_databases.sql must exist"
    content = sql_file.read_text(encoding="utf-8")
    assert "CREATE DATABASE gympro" in content
    assert "CREATE DATABASE gympro_test" in content


def test_pinned_requirements_and_gitattributes():
    """Requirements must pin exact versions and .gitattributes must configure line endings."""
    req_file = REPO_ROOT / "backend" / "requirements.txt"
    assert req_file.exists()
    req_text = req_file.read_text(encoding="utf-8")
    assert "fastapi==" in req_text
    assert "pydantic==" in req_text
    assert "asyncpg==" in req_text

    gitattrs = REPO_ROOT / ".gitattributes"
    assert gitattrs.exists()
    attr_text = gitattrs.read_text(encoding="utf-8")
    assert "*.py text eol=lf" in attr_text
    assert "*.sql text eol=lf" in attr_text
    assert "*.ps1 text eol=crlf" in attr_text


def test_migration_scripts_exist():
    """All required PowerShell automation scripts and docs exist."""
    scripts_dir = REPO_ROOT / "scripts"
    assert (scripts_dir / "check_prereqs.ps1").exists()
    assert (scripts_dir / "setup_company_pc.ps1").exists()
    assert (scripts_dir / "start_all.ps1").exists()
    assert (scripts_dir / "reset_dev_db.ps1").exists()
    assert (scripts_dir / "dev_smtp_sink.py").exists()

    assert (REPO_ROOT / "docs" / "COMPANY_PC_SETUP.md").exists()
    assert (REPO_ROOT / ".env.example").exists()
    assert "LLM_PROVIDER=fake" in (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
