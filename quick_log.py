"""Read the latest production status through the configured SSH connection."""

from remote_config import connect_ssh


def main() -> None:
    ssh = connect_ssh(timeout=15)
    try:
        for command in (
            "ps aux | grep 'python.*main.py' | grep -v grep || echo 'Bot calismadi'",
            "ls -la /root/QuantBot/bot.log 2>/dev/null || echo 'Log yok'",
            "tail -20 /root/QuantBot/bot.log 2>/dev/null || echo 'Log yok'",
        ):
            _, stdout, _ = ssh.exec_command(command, timeout=15)
            print(stdout.read().decode("utf-8", errors="replace"))
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
