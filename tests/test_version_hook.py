import stat
from pathlib import Path

HOOK = Path(__file__).parents[1] / ".githooks" / "pre-commit"


def test_pre_commit_hook_bumps_and_stages_package_version():
    assert HOOK.stat().st_mode & stat.S_IXUSR
    script = HOOK.read_text()
    assert "git diff --quiet -- pyproject.toml uv.lock" in script
    assert "uv version --bump patch --no-sync" in script
    assert "git add -- pyproject.toml uv.lock" in script
