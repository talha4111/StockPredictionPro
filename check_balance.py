"""Run the remote balance checker without embedding credentials."""

from remote_config import connect_ssh


def main() -> None:
    ssh = connect_ssh(timeout=15)
    try:
        _, stdout, stderr = ssh.exec_command(
            "cd /root/QuantBot && ./venv/bin/python balance_check_remote.py",
            timeout=45,
        )
        print(stdout.read().decode("utf-8", errors="replace"))
        error = stderr.read().decode("utf-8", errors="replace")
        if error:
            print(error)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
