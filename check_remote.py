from remote_config import connect_ssh

ssh = connect_ssh(timeout=10)

print("--- PERFORMANS JSON ---")
stdin, stdout, stderr = ssh.exec_command("cat /root/QuantBot/performans.json")
print(stdout.read().decode('utf-8'))

print("\n--- SON 10 ISLEM (TRADE HISTORY) ---")
stdin, stdout, stderr = ssh.exec_command("tail -n 10 /root/QuantBot/trade_history.csv")
print(stdout.read().decode('utf-8'))

print("\n--- TMUX LOGLARI (SON 20 SATIR) ---")
stdin, stdout, stderr = ssh.exec_command("tmux capture-pane -pt quantbot | tail -n 20")
print(stdout.read().decode('utf-8'))

ssh.close()
