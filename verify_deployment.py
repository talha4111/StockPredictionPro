"""Verify deployed files and service health without exposing secrets."""

import hashlib
import json

from deploy_controlled import FILES, ROOT
from remote_config import connect_ssh


def run(ssh, command, timeout=30):
    _, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()
    return output, error, stdout.channel.recv_exit_status()


def ascii_text(value):
    return str(value).encode("ascii", errors="replace").decode("ascii")


def main():
    local_hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in FILES
    }
    ssh = connect_ssh(timeout=12)
    try:
        sftp = ssh.open_sftp()
        service, service_error, service_code = run(
            ssh, "systemctl is-active quantbot.service"
        )
        main_pid, pid_error, pid_code = run(
            ssh, "systemctl show quantbot.service -p MainPID --value"
        )
        process_cwd, cwd_error, cwd_code = run(
            ssh, f"readlink -f /proc/{main_pid}/cwd" if main_pid.isdigit() else "false"
        )
        model_locations, model_location_error, _ = run(
            ssh,
            "find /root -maxdepth 3 -type f -name '*_meta.json' "
            "-printf '%T@ %p\\n' | sort -nr | head -10",
        )
        remote_hashes_raw, hash_error, hash_code = run(
            ssh,
            "sha256sum "
            + " ".join(f"/root/QuantBot/{name}" for name in FILES),
        )
        remote_hashes = {}
        for line in remote_hashes_raw.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                remote_hashes[parts[1].rsplit("/", 1)[-1]] = parts[0]

        permissions, perm_error, perm_code = run(
            ssh,
            "stat -c '%a %n' /root/QuantBot /root/QuantBot/.env "
            "/root/QuantBot/ayar.json /root/QuantBot/aktif_detay.json "
            "/etc/logrotate.d/quantbot",
        )
        journal, journal_error, _ = run(
            ssh,
            "journalctl -u quantbot.service --since '10 minutes ago' "
            "--no-pager -n 80",
        )
        bot_log, bot_log_error, _ = run(
            ssh, "tail -n 80 /root/QuantBot/bot.log 2>/dev/null"
        )

        runtime = {}
        try:
            with sftp.open("/root/QuantBot/runtime_status.json", "r") as status_file:
                runtime = json.loads(status_file.read().decode("utf-8"))
        except (OSError, ValueError, TypeError):
            runtime = {}

        comparison_state = {}
        try:
            with sftp.open(
                "/root/QuantBot/live_model_compare_state.json", "r"
            ) as comparison_file:
                comparison_state = json.loads(
                    comparison_file.read().decode("utf-8")
                )
        except (OSError, ValueError, TypeError):
            comparison_state = {}

        latest_models = []
        try:
            model_paths = [
                line.split(maxsplit=1)[1]
                for line in model_locations.splitlines()
                if len(line.split(maxsplit=1)) == 2
            ]
            for model_path in model_paths[:5]:
                with sftp.open(model_path, "r") as meta_file:
                    meta = json.loads(meta_file.read().decode("utf-8"))
                latest_models.append(
                    {
                        "file": model_path.rsplit("/", 1)[-1],
                        "schema": meta.get("model_schema_version"),
                        "score": meta.get("walk_forward_skoru"),
                    }
                )
        except (OSError, ValueError, TypeError):
            latest_models = []

        mismatches = [
            name
            for name, local_hash in local_hashes.items()
            if remote_hashes.get(name) != local_hash
        ]
        command_errors = [
            error
            for error in (
                service_error,
                pid_error,
                cwd_error,
                model_location_error,
                hash_error,
                perm_error,
                journal_error,
                bot_log_error,
            )
            if error
        ]

        print(f"SERVICE_OK={service_code == 0 and service == 'active'}")
        print(f"MAIN_PID={main_pid if pid_code == 0 else 'unknown'}")
        print(f"PROCESS_CWD={process_cwd if cwd_code == 0 else 'unknown'}")
        print("MODEL_LOCATIONS=" + ascii_text(model_locations))
        print(f"FILES_MATCH={hash_code == 0 and not mismatches}")
        print("MISMATCHES=" + (",".join(mismatches) if mismatches else "none"))
        print(f"PERMISSIONS_OK={perm_code == 0}")
        print(ascii_text(permissions))
        print(
            "RUNTIME="
            + json.dumps(
                {
                    "updated": runtime.get("guncelleme_zamani"),
                    "phase": runtime.get("faz"),
                    "status": runtime.get("bot_durumu"),
                    "live_mode": runtime.get("live_mod"),
                    "live_trigger": runtime.get("live_tetik"),
                    "demo_orders": runtime.get("demo_emir_aktif"),
                    "demo_profile": runtime.get("demo_profil"),
                    "last_error": runtime.get("son_hata"),
                },
                ensure_ascii=True,
            )
        )
        print(
            "MODEL_COMPARISON="
            + json.dumps(runtime.get("model_karsilastirma", {}), ensure_ascii=True)
        )
        comparison_models = comparison_state.get("models", {})
        print(
            "MODEL_COMPARISON_STATE="
            + json.dumps(
                {
                    "schema": comparison_state.get("schema"),
                    "pending": len(comparison_state.get("pending", {})),
                    "450_8_evaluated": comparison_models.get("450_8", {}).get(
                        "evaluated", 0
                    ),
                    "450_8_signals": comparison_models.get("450_8", {}).get(
                        "signals", 0
                    ),
                    "400_5_evaluated": comparison_models.get("400_5", {}).get(
                        "evaluated", 0
                    ),
                    "400_5_signals": comparison_models.get("400_5", {}).get(
                        "signals", 0
                    ),
                },
                ensure_ascii=True,
            )
        )
        print("LATEST_MODELS=" + json.dumps(latest_models, ensure_ascii=True))
        if command_errors:
            print("REMOTE_ERRORS=" + ascii_text(" | ".join(command_errors)))
        print("RECENT_JOURNAL_BEGIN")
        print(ascii_text(journal))
        print("RECENT_JOURNAL_END")
        print("RECENT_BOT_LOG_BEGIN")
        print(ascii_text("\n".join(bot_log.splitlines()[-20:])))
        print("RECENT_BOT_LOG_END")
    finally:
        try:
            sftp.close()
        except UnboundLocalError:
            pass
        ssh.close()


if __name__ == "__main__":
    main()
