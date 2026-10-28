"""Show the current service logging configuration without changing it."""

from remote_config import connect_ssh


if __name__ == "__main__":
    ssh = connect_ssh(timeout=15)
    try:
        _, stdout, _ = ssh.exec_command("systemctl cat quantbot.service", timeout=15)
        print(stdout.read().decode("utf-8", errors="replace"))
    finally:
        ssh.close()
