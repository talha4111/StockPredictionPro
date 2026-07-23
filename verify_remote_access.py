"""Verify remote access without printing credentials or sensitive bot data."""

from remote_config import connect_ssh


def main():
    ssh = connect_ssh(timeout=12)
    try:
        _, stdout, stderr = ssh.exec_command(
            "systemctl is-active quantbot.service", timeout=12
        )
        status = stdout.read().decode("utf-8", errors="replace").strip()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        print("SSH_OK")
        print(f"SERVICE={status or 'unknown'}")
        print(f"REMOTE_COMMAND_OK={exit_code == 0 and not error}")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
