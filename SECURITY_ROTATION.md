# Security Rotation Checklist

Step 1 cleaned the repository side: hardcoded remote credentials were removed from the Python scripts, and sensitive local files were removed from Git tracking.

If this repository was ever pushed to a remote Git host, assume the old secrets are exposed. Removing files from the current index is not enough for already-pushed history; rotate the secrets first, then purge history with a dedicated tool before pushing cleaned history.

Manual rotation still needs to happen outside this repo:

1. Rotate the remote server password or disable password login and use an SSH key.
2. Create a new Binance live API key. Delete the old one. Use IP allowlisting and futures permission only when needed.
3. Create a new Binance testnet/demo API key if the old key was ever shared.
4. Rotate the Telegram bot token with BotFather and update the chat id if needed.
5. Rotate the Gemini API key.
6. Replace local values in `.env` and `ayar.json`; keep both files untracked.

Required local variables for remote scripts:

```env
REMOTE_HOST=
REMOTE_USER=
REMOTE_PORT=22
REMOTE_PASSWORD=
# Or, preferably:
REMOTE_KEY_FILE=C:\path\to\private-key.pem
```

Do not paste real keys into source files. Use `.env`, OS environment variables, or a secret manager.
