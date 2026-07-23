import os

import paramiko


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value and not os.environ.get(key):
                os.environ[key] = value


def remote_settings():
    _load_env_file(os.path.join(BASE_DIR, ".env"))
    _load_env_file(os.path.join(BASE_DIR, "QuantBot", ".env"))
    host = os.environ.get("REMOTE_HOST") or os.environ.get("QUANTBOT_HOST")
    user = os.environ.get("REMOTE_USER") or os.environ.get("QUANTBOT_USER")
    password = os.environ.get("REMOTE_PASSWORD") or os.environ.get("QUANTBOT_PASSWORD")
    key_file = os.environ.get("REMOTE_KEY_FILE") or os.environ.get("QUANTBOT_KEY_FILE")
    port = int(os.environ.get("REMOTE_PORT", "22"))

    if not host or not user:
        raise RuntimeError("REMOTE_HOST ve REMOTE_USER ortam degiskenleri gerekli.")
    if not password and not key_file:
        raise RuntimeError("REMOTE_PASSWORD veya REMOTE_KEY_FILE ortam degiskenlerinden biri gerekli.")

    return {
        "host": host,
        "user": user,
        "password": password,
        "key_file": key_file,
        "port": port,
    }


def connect_ssh(timeout=10):
    cfg = remote_settings()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": cfg["host"],
        "username": cfg["user"],
        "port": cfg["port"],
        "timeout": timeout,
    }
    if cfg["key_file"]:
        connect_kwargs["key_filename"] = cfg["key_file"]
    else:
        connect_kwargs["password"] = cfg["password"]

    ssh.connect(**connect_kwargs)
    return ssh
