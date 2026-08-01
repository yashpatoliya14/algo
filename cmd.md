Yes. **Don't leave the SSH terminal open.** That's not how you run a production bot.

The correct approach is to use a **process manager** so your bot keeps running:

* ✅ 24/7
* ✅ After you disconnect SSH
* ✅ After the VM reboots
* ✅ If the bot crashes

For a Python bot, I recommend **systemd** (built into Ubuntu). PM2 also works, but systemd is the standard choice for Python.

---

# Step 1: Find your Python path

Activate your virtual environment:

```bash
source venv/bin/activate
```

Then run:

```bash
which python
```

Example output:

```text
/home/yash/trading-bot/venv/bin/python
```

Save this path.

---

# Step 2: Find your project path

Run:

```bash
pwd
```

Example:

```text
/home/yash/trading-bot
```

---

# Step 3: Create a service

```bash
sudo nano /etc/systemd/system/delta-bot.service
```

Paste this (replace the paths with yours):

```ini
[Unit]
Description=Delta Trading Bot
After=network.target

[Service]
User=yash
WorkingDirectory=/home/yash/trading-bot
ExecStart=/home/yash/trading-bot/venv/bin/python /home/yash/trading-bot/delta_trader.py

Restart=always
RestartSec=10

Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Save:

* `Ctrl + O`
* Enter
* `Ctrl + X`

---

# Step 4: Enable the service

```bash
sudo systemctl daemon-reload

sudo systemctl enable delta-bot

sudo systemctl start delta-bot
```

---

# Step 5: Check status

```bash
sudo systemctl status delta-bot
```

If everything is working you'll see:

```
Active: active (running)
```

---

# Step 6: View logs

```bash
journalctl -u delta-bot -f
```

You'll see your bot's output live.

---

# Step 7: Disconnect

Now you can simply type:

```bash
exit
```

or close your terminal.

The bot will continue running on the Azure VM.

---

## Before enabling live trading

Keep these settings while testing:

```env
DRY_RUN=true
LEVERAGE=1
RISK_PCT=0.5
```

Confirm the bot:

* Connects to Delta.
* Receives market data.
* Generates signals correctly.
* Does **not** place real orders.

Only then change:

```env
DRY_RUN=false
```

to begin live trading.

### I can help you verify the deployment

Before setting up the service, tell me:

1. What is the output of:

   ```bash
   pwd
   ```
2. What is the output of:

   ```bash
   which python
   ```
3. What is the name of the file that starts your bot?

   * `delta_trader.py`
   * `main.py`
   * something else?

With those three pieces of information, I'll give you the exact `systemd` service file for your setup.
