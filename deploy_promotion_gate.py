"""Deploy only the read-only promotion diagnostic without restarting QuantBot."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from remote_config import connect_ssh


LOCAL_FILE = Path(__file__).resolve().parent / "QuantBot" / "promotion_gate.py"
REMOTE_DIR = "/root/QuantBot"
REMOTE_TARGET = f"{REMOTE_DIR}/promotion_gate.py"
REMOTE_UPLOAD = f"{REMOTE_DIR}/promotion_gate.upload.py"


def _run(ssh, command: str) -> tuple[str, str, int]:
    _, stdout, stderr = ssh.exec_command(command, timeout=45)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    return output, error, stdout.channel.recv_exit_status()


def main() -> int:
    if not LOCAL_FILE.is_file():
        raise FileNotFoundError(LOCAL_FILE)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{REMOTE_TARGET}.before_diagnosis_{stamp}"
    ssh = connect_ssh(timeout=15)
    sftp = ssh.open_sftp()
    try:
        sftp.put(str(LOCAL_FILE), REMOTE_UPLOAD)
        command = (
            f"cd {REMOTE_DIR} && "
            "./venv/bin/python -m py_compile promotion_gate.upload.py && "
            f"cp {REMOTE_TARGET} {backup} && "
            f"mv {REMOTE_UPLOAD} {REMOTE_TARGET} && "
            f"chmod 640 {REMOTE_TARGET}"
        )
        output, error, exit_code = _run(ssh, command)
        if exit_code:
            raise RuntimeError(error or output or "Uzak syntax/doğrulama başarısız.")
        print(f"DEPLOY_OK backup={backup}")
        print("SERVICE_RESTARTED=False")
        return 0
    finally:
        try:
            sftp.close()
        finally:
            ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
