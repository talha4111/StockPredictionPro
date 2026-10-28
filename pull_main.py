"""Pull selected production files using the configured SSH connection."""

from pathlib import Path

from remote_config import connect_ssh


ROOT = Path(__file__).resolve().parent
REMOTE = "/root/QuantBot"


def main() -> None:
    ssh = connect_ssh(timeout=15)
    sftp = ssh.open_sftp()
    try:
        for name in ("main.py", "position_tracker.py"):
            sftp.get(f"{REMOTE}/{name}", str(ROOT / "QuantBot" / name))
            print(f"Pulled {name}")
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
