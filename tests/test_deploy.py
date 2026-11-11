"""Exercise the optional deployment helper with a local fake smbclient."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "mode,success", [("ok", True), ("command_error", False), ("process_error", False)]
)
def test_smb_failure_reporting_and_secret_handling(tmp_path, mode, success):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(
        root / "custom_components",
        tmp_path / "custom_components",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (tmp_path / "scripts").mkdir()
    shutil.copy(root / "scripts/deploy_smb.sh", tmp_path / "scripts")
    binary = tmp_path / "smbclient"
    binary.write_text("""#!/usr/bin/env python3
import os, pathlib, stat, sys
args = sys.argv[1:]
auth = pathlib.Path(args[args.index('-A') + 1])
assert 'TEST_PRIVATE_SMB_SECRET' not in ' '.join(args)
assert 'HA_SMB_PASS' not in os.environ
assert stat.S_IMODE(auth.stat().st_mode) == 0o600
assert 'TEST_PRIVATE_SMB_SECRET' in auth.read_text()
pathlib.Path(os.environ['AUTH_CAPTURE']).write_text(str(auth))
sys.stdin.read()
if os.environ['FAKE_MODE'] == 'process_error': sys.exit(1)
if os.environ['FAKE_MODE'] == 'command_error': print('NT_STATUS_ACCESS_DENIED opening remote file')
else: print('NT_STATUS_OBJECT_NAME_COLLISION making remote directory \\eac_cyprus')
""")
    binary.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "HA_HOST": "192.0.2.10",
        "HA_SMB_USER": "test",
        "HA_SMB_PASS": "TEST_PRIVATE_SMB_SECRET",
        "FAKE_MODE": mode,
        "AUTH_CAPTURE": str(tmp_path / "auth-path"),
    }
    result = subprocess.run(
        ["bash", str(tmp_path / "scripts/deploy_smb.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is success
    assert ("deployed to" in result.stdout) is success
    assert "TEST_PRIVATE_SMB_SECRET" not in result.stdout + result.stderr
    assert not Path((tmp_path / "auth-path").read_text()).exists()
