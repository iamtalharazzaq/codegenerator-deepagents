import zipfile
from pathlib import Path

from orchestrator.delivery import build_zip
from orchestrator.secrets import scan_secrets


def test_scan_finds_real_looking_secrets_without_echoing_them(tmp_path: Path):
    (tmp_path / "app.py").write_text('KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    (tmp_path / "cfg.py").write_text('password = "hunter2hunter2hunter2"\n')
    (tmp_path / "pem.txt").write_text("-----BEGIN RSA PRIVATE KEY-----\n")
    findings = scan_secrets(tmp_path)
    assert {(f.path, f.kind) for f in findings} == {
        ("app.py", "aws_access_key"),
        ("cfg.py", "hardcoded_credential"),
        ("pem.txt", "private_key"),
    }
    assert all("AKIA" not in repr(f) for f in findings)


def test_scan_ignores_placeholders_env_files_and_vendor_dirs(tmp_path: Path):
    (tmp_path / "a.py").write_text('password = "changeme-example-value"\n')
    (tmp_path / ".env").write_text("TOKEN=AKIAABCDEFGHIJKLMNOP\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text('const k = "AKIAABCDEFGHIJKLMNOP"\n')
    assert scan_secrets(tmp_path) == []


def test_zip_has_code_at_root_docs_under_orchestrator_and_leaves_out_junk(tmp_path: Path):
    work, runs = tmp_path / "work", tmp_path / "runs" / "r1"
    (work / "src").mkdir(parents=True)
    (work / "src" / "app.py").write_text("print(1)\n")
    (work / ".env").write_text("SECRET=1\n")
    (work / ".env.example").write_text("SECRET=\n")
    (work / ".git").mkdir()
    (work / ".git" / "HEAD").write_text("ref\n")
    (work / "node_modules").mkdir()
    (work / "node_modules" / "m.js").write_text("x\n")
    (work / "link.py").symlink_to(work / "src" / "app.py")
    runs.mkdir(parents=True)
    (runs / "report.md").write_text("# report\n")
    (runs / "ab12cd34.md").write_text("design\n---\nstatus: pass\nreason: ok\n---\n")
    (runs / "ab12cd34.attempt1.md").write_text("old\n")
    (runs / "task_log.json").write_text("{}")
    dest, count = build_zip(work, runs, tmp_path / "out.zip")
    names = set(zipfile.ZipFile(dest).namelist())
    assert names == {"src/app.py", ".env.example", "docs/orchestrator/report.md", "docs/orchestrator/ab12cd34.md"}
    assert count == 4


def test_partial_zip_is_labelled(tmp_path: Path):
    work, runs = tmp_path / "work", tmp_path / "runs"
    work.mkdir()
    runs.mkdir()
    dest, _ = build_zip(work, runs, tmp_path / "p.zip", partial=True)
    assert "PARTIAL.txt" in zipfile.ZipFile(dest).namelist()
