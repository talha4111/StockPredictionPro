"""List production files through the configured SSH connection."""

from remote_config import connect_ssh


if __name__ == "__main__":
    ssh = connect_ssh(timeout=15)
    try:
        _, stdout, _ = ssh.exec_command("find /root/QuantBot -maxdepth 1 -type f -printf '%f\\n' | sort", timeout=15)
        print(stdout.read().decode("utf-8", errors="replace"))
    finally:
        ssh.close()
