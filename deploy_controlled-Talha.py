"""Deploy the audited QuantBot modules with backup, compile, and rollback."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from remote_config import connect_ssh


ROOT = Path(__file__).resolve().parent / "QuantBot"
REMOTE = "/root/QuantBot"
FILES = (
    "main.py",
    "instance_lock.py",
    "ai_core.py",
    "config.py",
    "tarayici.py",
    "live_model_compare.py",
    "signal_engine.py",
    "scanner_loop.py",
    "order_engine.py",
    "position_tracker.py",
    "risk_manager.py",
    "db_logger.py",
    "runtime_status.py",
    "mufettis.py",
    "promotion_gate.py",
    "test_ai_core_quality.py",
    "test_live_model_compare.py",
    "test_order_sync.py",
    "test_symbol_guard.py",
    "test_instance_lock.py",
    "test_promotion_gate.py",
)


def print_safe(value) -> None:
    text = str(value)
    encoding = getattr(__import__("sys").stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


def run(ssh, command: str, timeout: int = 60) -> tuple[str, str, int]:
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err, stdout.channel.recv_exit_status()


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{REMOTE}/backup_controlled_{stamp}"
    ssh = connect_ssh(timeout=15)
    sftp = ssh.open_sftp()
    try:
        out, err, code = run(ssh, "systemctl stop quantbot.service", timeout=45)
        if code:
            raise RuntimeError(f"servis durmadi: {err or out}")

        remote_files = " ".join(f"{REMOTE}/{name}" for name in FILES)
        backup_cmd = (
            f"mkdir -p {backup} && "
            f"for file in {remote_files}; do "
            f"[ ! -f \"$file\" ] || cp \"$file\" {backup}/; "
            "done"
        )
        out, err, code = run(ssh, backup_cmd, timeout=45)
        if code:
            raise RuntimeError(f"yedek alinamadi: {err or out}")

        for name in FILES:
            local_path = ROOT / name
            if not local_path.exists():
                raise FileNotFoundError(local_path)
            sftp.put(str(local_path), f"{REMOTE}/{name}")

        sftp.put(str(ROOT / "quantbot.logrotate"), "/tmp/quantbot-logrotate")

        compile_cmd = "cd /root/QuantBot && ./venv/bin/python -m py_compile " + " ".join(FILES)
        out, err, code = run(ssh, compile_cmd, timeout=120)
        if code:
            run(ssh, f"cp {backup}/*.py {REMOTE}/", timeout=60)
            run(ssh, "systemctl start quantbot.service", timeout=45)
            raise RuntimeError(f"uzak syntax kontrolu basarisiz: {err or out}")

        run(ssh, "chmod 750 /root/QuantBot && chmod 640 /root/QuantBot/*.py && chmod 600 /root/QuantBot/.env /root/QuantBot/ayar.json /root/QuantBot/aktif_detay.json 2>/dev/null || true", timeout=30)
        run(ssh, "install -o root -g root -m 644 /tmp/quantbot-logrotate /etc/logrotate.d/quantbot", timeout=30)
        out, err, code = run(ssh, "systemctl start quantbot.service", timeout=45)
        if code:
            run(ssh, f"cp {backup}/*.py {REMOTE}/ && systemctl start quantbot.service", timeout=60)
            raise RuntimeError(f"servis baslamadi: {err or out}")

        time.sleep(8)
        status, status_err, _ = run(ssh, "systemctl --no-pager --full status quantbot.service | head -35", timeout=30)
        log, log_err, _ = run(ssh, "tail -60 /root/QuantBot/bot.log 2>/dev/null", timeout=30)
        print_safe(f"DEPLOY_OK backup={backup}")
        print_safe(status)
        print_safe(log)
        if status_err or log_err:
            print_safe(status_err or log_err)
    except Exception:
        run(ssh, "systemctl start quantbot.service", timeout=45)
        raise
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
