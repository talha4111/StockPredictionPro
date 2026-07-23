"""Deploy accounting modules through the configured SSH connection."""

from pathlib import Path

from remote_config import connect_ssh


ROOT = Path(__file__).resolve().parent / "QuantBot"
REMOTE = "/root/QuantBot"
FILES = ("account_sync.py", "db_logger.py", "demo_trade_journal.py", "runtime_status.py")


if __name__ == "__main__":
    ssh = connect_ssh(timeout=15)
    sftp = ssh.open_sftp()
    try:
        for name in FILES:
            sftp.put(str(ROOT / name), f"{REMOTE}/{name}")
            print(f"Uploaded {name}")
    finally:
        sftp.close()
        ssh.close()
