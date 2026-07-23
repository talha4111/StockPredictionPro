"""Basic production service and log check without embedded credentials."""

from remote_config import connect_ssh


if __name__ == "__main__":
    ssh = connect_ssh(timeout=15)
    try:
        command = "systemctl --no-pager --full status quantbot.service; tail -40 /root/QuantBot/bot.log"
        _, stdout, _ = ssh.exec_command(command, timeout=30)
        print(stdout.read().decode("utf-8", errors="replace"))
    finally:
        ssh.close()
