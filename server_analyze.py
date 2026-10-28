"""Run the repository's non-destructive production audit remotely."""

from remote_config import connect_ssh


if __name__ == "__main__":
    ssh = connect_ssh(timeout=15)
    try:
        _, stdout, stderr = ssh.exec_command(
            "cd /root/QuantBot && ./venv/bin/python ops_scan.py",
            timeout=120,
        )
        print(stdout.read().decode("utf-8", errors="replace"))
        print(stderr.read().decode("utf-8", errors="replace"))
    finally:
        ssh.close()
