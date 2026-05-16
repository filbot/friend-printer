# Thermal Printer

A little appliance for your desk. A friend sends a text or photo from Telegram. Your printer prints it on receipt paper.

## What you're building

A Raspberry Pi runs a small Telegram bot. The bot accepts messages only from people you whitelist (you, your friend, whoever). When a message comes in, the bot formats it for the printer and pushes it out.

## What you need

Hardware:

- Any Raspberry Pi (I'm running this from an original Raspberry Pi 1)
- USB ESC/POS thermal receipt printer. This was built and tested on a POS-5890C, which is the cheap 58mm kind you see around
- Power for both. One barrel-to-USB splitter keeps it to a single cord
- A microSD card (8GB+) and a way to flash it from your laptop

Accounts:

- A Telegram account (free, no phone number sharing)

That's it. No domain name, no cloud account, nothing else to pay for.

## Before you start

This guide assumes a few things:

1. Your Pi is running **Raspberry Pi OS Lite** (the headless version with no desktop). If you've never set up a Pi before, the [Raspberry Pi Imager](https://www.raspberrypi.com/software/) walks you through it. Enable SSH and your Wi-Fi in the Imager's advanced options so you can log in without a monitor.
2. You can SSH into the Pi. From your laptop's terminal: `ssh pi@raspberrypi.local` (or use the Pi's IP address). If you set a different username in the Imager, use that.
3. You're comfortable copy-pasting commands and reading what they do. Every command below is explained. Don't run things you don't understand. If a step looks scary, the explanation underneath usually clears it up.

A note on `sudo`: any command starting with `sudo` runs as the root user. It's how Linux says "this affects the whole system, not just you." You'll get prompted for your password the first time in a session. That's normal.

A note on `nano`: when a step says `nano somefile`, it opens a basic text editor. Save with `Ctrl-O` then `Enter`. Exit with `Ctrl-X`. If you're more comfortable with another editor, use it.

## Setup

### Step 1. Install the system packages and clone this repo

SSH into your Pi, then run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git \
    libopenjp2-7 libtiff6 libwebp7 libjpeg62-turbo libfreetype6
```

The first line refreshes the list of available packages. The second installs Python, git, and a handful of image libraries that Pillow (the Python image library) needs. Pi OS Lite doesn't ship with these by default. If you skip them, the bot crashes on startup with a confusing `libopenjp2.so.7: cannot open shared object file` error.

Now pull down the project:

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/Thermal-Printer.git friendprinter
cd friendprinter
```

Replace `YOUR_USERNAME` with whoever owns the fork you're using.

Set up a Python virtual environment and install the bot's dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A virtual environment is a sandbox for Python packages so they don't conflict with system Python. The `source .venv/bin/activate` line activates it. You'll know it worked because your prompt picks up a `(.venv)` prefix.

On a Pi Zero 2 W, this install takes a few minutes. Pillow has C code to compile and the Pi isn't fast. Go make tea.

### Step 2. Find the printer

Plug the printer's USB cable into the Pi and turn it on. Then ask Linux what it sees:

```bash
lsusb
```

You'll get a list of USB devices. Find your printer's line. It looks something like:

```
Bus 001 Device 004: ID 0416:5011 Winbond Electronics Corp.
```

The important bit is `0416:5011`. The first part (`0416`) is the vendor ID. The second (`5011`) is the product ID. Write both down. You need them in the next step.

Now check that the kernel exposed it as a printer device:

```bash
ls -l /dev/usb/lp*
```

You should see `/dev/usb/lp0`. If you see "No such file or directory", the printer is plugged in but not recognized as a USB printer. Try a different USB port, or check that the printer is actually powered on.

### Step 3. Give your user permission to talk to the printer

Out of the box, only root can write to `/dev/usb/lp0`. You don't want to run the bot as root. The fix is two things: a udev rule that gives the device a friendly name and predictable permissions, and adding your user to the `lp` group.

From inside the project folder, copy the example rule and edit it:

```bash
sudo cp 99-thermal-printer.rules.example /etc/udev/rules.d/99-thermal-printer.rules
sudo nano /etc/udev/rules.d/99-thermal-printer.rules
```

Inside the file, replace `REPLACE_VID` and `REPLACE_PID` with the VID and PID you noted in Step 2. Save with `Ctrl-O`, `Enter`, then `Ctrl-X`.

Tell udev to reload the rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Add your user to the `lp` group (the standard "line printer" group on Linux):

```bash
sudo usermod -aG lp $USER
```

This change doesn't take effect until you log out and back in. Disconnect your SSH session, reconnect, then check:

```bash
groups | grep lp
ls -l /dev/thermal-printer
```

The first command should print a line containing `lp`. The second should show a symlink that your udev rule created. If the symlink isn't there, unplug the printer's USB cable, wait a second, and plug it back in so the rule fires fresh.

Now the moment of truth. Send some text straight to the printer:

```bash
echo "hello from the pi" > /dev/thermal-printer
```

The printer should whir and spit out a tiny receipt. If it doesn't, check the Troubleshooting section before moving on. Don't continue until this works.

### Step 4. Make a Telegram bot

Open Telegram on your phone or laptop and start a chat with [@BotFather](https://t.me/BotFather). BotFather is Telegram's official bot for making bots.

1. Send `/newbot`
2. Pick a display name (anything you want)
3. Pick a username. It has to end in `bot` (e.g. `my_friend_printer_bot`)
4. BotFather sends back a token that looks like `123456:ABC-DEF...`. **Save this.** It's the password to your bot. Don't share it or commit it.

You also need the numeric Telegram ID of every person you want to let print. To find your own ID, message [@userinfobot](https://t.me/userinfobot). It replies with `Id: 123456789`. That number is what you want, not the `@username`.

Get your friend's ID the same way. They message @userinfobot and send you the number back.

### Step 5. Configure the bot

Two config files: `.env` for secrets, `config.yaml` for settings.

```bash
cp .env.example .env
nano .env
```

Fill in `TELEGRAM_BOT_TOKEN` (the BotFather token) and `ALLOWED_USER_IDS` (comma-separated numeric IDs). Save and exit.

```bash
cp config.yaml.example config.yaml
nano config.yaml
```

The defaults are sensible. The one you might want to change is `printer_device`, which should point at the udev symlink (`/dev/thermal-printer`) if Step 3 went well. If you have an 80mm printer instead of a 58mm one, set `paper_width_px: 576`.

Make sure your virtualenv is still active (`(.venv)` in your prompt). If not, run `source .venv/bin/activate` from the project folder. Then start the bot manually to test:

```bash
python bot.py
```

From a whitelisted Telegram account, send the bot a message. The printer should print it within a few seconds and you'll see a reply in Telegram. If it works, kill the bot with `Ctrl-C`. You're ready for the final step.

### Step 6. Run the bot as a service

You don't want to keep an SSH session open forever. systemd is Linux's service manager. It runs the bot in the background, restarts it if it crashes, and starts it again on reboot.

The service file in the repo assumes your user is `pi` and the project lives at `/home/pi/friendprinter`. If either is different for you, edit `friendprinter.service` first and change the paths.

Then install it:

```bash
sudo cp friendprinter.service /etc/systemd/system/friendprinter.service
sudo systemctl daemon-reload
sudo systemctl enable --now friendprinter
sudo systemctl status friendprinter
```

The `status` command should show `active (running)` in green. If it says `failed`, scroll up in the output for the actual error. The most common cause is wrong paths in the service file.

That's it. Reboot the Pi (`sudo reboot`) to confirm the bot comes back on its own. Send it a message after it boots to be sure.

## Config reference

`config.yaml`:

| Key | Meaning |
| --- | --- |
| `printer_device` | Path to the printer's character device. Use the udev symlink if you can |
| `paper_width_px` | 384 for 58mm printers, 576 for 80mm |
| `max_prints_per_hour` | Rolling cap on prints in any 60-minute window |
| `max_prints_per_day` | Same, for 24 hours |
| `max_text_length` | Reject single messages longer than this |
| `max_image_dimension` | Reject images larger than this on either side (before resize) |
| `log_path` | Where the print history log goes. Relative paths resolve from the project folder |

`.env`:

| Key | Meaning |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `ALLOWED_USER_IDS` | Comma-separated numeric Telegram IDs allowed to print |

## Day-to-day operation

Watch the live log:

```bash
journalctl -u friendprinter -f
```

Restart after a config change:

```bash
sudo systemctl restart friendprinter
```

Stop the bot:

```bash
sudo systemctl stop friendprinter
```

Start it again:

```bash
sudo systemctl start friendprinter
```

The print history (separate from the systemd log) is in `prints.log` in the project folder. It rotates at about 1MB and keeps three backups.

## Troubleshooting

**The bot starts but nothing prints.** Two things to check. Run `groups` and confirm `lp` is in the list. Then check `printer_device` in `config.yaml` points to a real path with `ls -l /dev/thermal-printer`. Test the device directly with `echo "test" > /dev/thermal-printer`.

**`Permission denied` writing to the printer.** Either the udev rule isn't applying or you didn't log out and back in after adding yourself to `lp`. Try `sudo udevadm control --reload-rules && sudo udevadm trigger`, and if that doesn't help, reboot.

**Photos print with heavy vertical banding.** The bot uses `bitImageColumn` mode by default for a reason. If you changed it, switch back. If it's still banding, try a shorter USB cable or a powered USB hub. Some printer firmware can't keep up if the Pi's USB power sags.

**The bot is silent when my friend messages it.** Run `journalctl -u friendprinter -f` and have them send another message. If you see `rejected non-whitelisted user`, the numeric ID in `ALLOWED_USER_IDS` is wrong. Remember: numeric IDs, not `@usernames`, and separated by commas.

**`ImportError: libfoo.so.N: cannot open shared object file`** at startup. A system library Pillow needs is missing. Install it with `sudo apt install -y libfoo<N>` (for example `libopenjp2-7`, `libtiff6`, `libwebp7`). Step 1 covers the common ones. If you skipped any, install them now.

**Animated stickers don't print.** Correct. Thermal printers can only do static images. The bot replies to the sender to let them know.

## What's not here (yet)

- Multiple users with separate quotas
- A web dashboard
- A print queue that survives a reboot
- Anything besides Telegram (no SMS, email, web form)
- Anything about the physical housing. Build whatever case you want around it

## Onboarding the friend

When you're ready to hand it over, send your friend [FRIEND_SETUP.md](FRIEND_SETUP.md). It's a plain-language doc that walks them through getting Telegram, finding the bot, and sending the first message. Edit the bot username in there before sharing.

## License

MIT. See [LICENSE](LICENSE).
