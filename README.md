# Thermal Printer

A standalone thermal receipt printer "appliance" that prints whatever a single trusted friend sends from their phone. Lives on a desk, decorated like an object, comes alive at random.

The Pi runs a Telegram bot. Whitelisted user sends a message, photo, or sticker. The bot prints it. That's the whole thing.

## Hardware

- Raspberry Pi Zero 2 W (Pi 3 or 4 also fine)
- Generic USB ESC/POS thermal receipt printer — built and tested on a [POS-5890C](https://www.amazon.com/dp/B07ZS5RH8Y) (58mm)
- Power supply for both, or a single barrel-to-USB splitter so the appliance has one cord

## Software

- Raspberry Pi OS Lite (headless)
- Python 3.10+
- [python-escpos](https://github.com/python-escpos/python-escpos) — printer control
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — messaging
- [Pillow](https://github.com/python-pillow/Pillow) — image preprocessing (resize, grayscale, Floyd-Steinberg dither)
- systemd to run the bot as a service

## How it works

A `RateLimiter` enforces per-hour and per-day caps. Text is wrapped to the printer's column width and stripped of curly quotes / em-dashes that the printer's codepage can't render. Photos and stickers are downscaled to the paper width, autocontrasted, dithered to 1-bit, and pushed in ESC/POS column mode (raster mode produces banding on the POS-5890C). Print attempts are logged to a rotating local file and to journalctl. Non-whitelisted users are silently ignored.

The bot replies with a quippy acknowledgement on success and a (mostly) helpful message on rate-limit, oversized input, or printer failure.

## Setup

The walkthrough assumes a fresh Pi running Raspberry Pi OS Lite with SSH enabled.

### 1. Identify the printer

Plug it in, then:

```bash
lsusb
```

Find the line for your printer and note the VID:PID. Something like `ID 0416:5011`.

Confirm the kernel sees it as a USB printer:

```bash
ls -l /dev/usb/lp*
```

You should see `/dev/usb/lp0`.

### 2. Set up the udev rule

Copy the template and fill in your VID/PID:

```bash
sudo cp 99-thermal-printer.rules.example /etc/udev/rules.d/99-thermal-printer.rules
sudo nano /etc/udev/rules.d/99-thermal-printer.rules    # replace REPLACE_VID and REPLACE_PID
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Add your user to the `lp` group so it can write to the printer:

```bash
sudo usermod -aG lp $USER
```

Log out and back in for the group change to take effect. Verify:

```bash
groups | grep lp
ls -l /dev/thermal-printer    # symlink created by the udev rule
```

Smoke-test the printer:

```bash
echo "hello from the pi" > /dev/thermal-printer
```

You should hear it whir and see paper come out.

### 3. Register a Telegram bot

Open Telegram and message [@BotFather](https://t.me/BotFather):

1. `/newbot`
2. Pick a display name and a username (`*_bot` suffix required)
3. BotFather replies with a token like `123456:ABC-DEF...`. Save it.

Find your friend's numeric Telegram ID:

1. Have them message [@userinfobot](https://t.me/userinfobot)
2. It replies with `Id: 123456789` — that's the value you want

(Or you can use your own ID first to test, and swap to your friend's later.)

### 4. Install the bot

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

cd ~
git clone https://github.com/filbot/Thermal-Printer.git friendprinter
cd friendprinter

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Configure

```bash
cp .env.example .env
nano .env       # fill in TELEGRAM_BOT_TOKEN and ALLOWED_USER_ID

cp config.yaml.example config.yaml
nano config.yaml    # adjust printer_device, paper width, limits
```

Confirm the bot can start:

```bash
source .venv/bin/activate
python bot.py
```

Send a test message from the whitelisted Telegram account. If you see the printer print and a reply come back, you're good. Stop with `Ctrl-C`.

### 6. Install the systemd service

The unit file assumes the user is `pi` and the install dir is `/home/pi/friendprinter`. If yours differs, edit `friendprinter.service` accordingly.

```bash
sudo cp friendprinter.service /etc/systemd/system/friendprinter.service
sudo systemctl daemon-reload
sudo systemctl enable --now friendprinter
sudo systemctl status friendprinter
```

The bot now starts on boot and restarts on failure.

## Configuration reference

`config.yaml`:

| Key | Meaning |
| --- | --- |
| `printer_device` | Path to the printer's character device (recommended: the udev symlink) |
| `paper_width_px` | 384 for 58mm printers, 576 for 80mm |
| `max_prints_per_hour` | Rolling-window cap |
| `max_prints_per_day` | Rolling-window cap |
| `max_text_length` | Reject single messages longer than this |
| `max_image_dimension` | Reject images larger than this on either side, pre-resize |
| `log_path` | Rotating file log destination (relative paths resolve from project dir) |

`.env`:

| Key | Meaning |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `ALLOWED_USER_ID` | Numeric Telegram ID of the one user allowed to print |

## Operating it

Tail the live log:

```bash
journalctl -u friendprinter -f
```

Restart after a config change:

```bash
sudo systemctl restart friendprinter
```

The print history log rotates at ~1MB and keeps three backups. Look in the project directory for `prints.log*`.

## Troubleshooting

**Bot starts but nothing prints.** Confirm the bot user is in the `lp` group (`groups`) and `printer_device` in `config.yaml` points to a real path (`ls -l /dev/thermal-printer`). Test the device directly with `echo "test" > /dev/thermal-printer`.

**`Permission denied` on the printer device.** udev rule didn't apply, or you didn't log out/back in after adding the user to `lp`. Re-run `sudo udevadm control --reload-rules && sudo udevadm trigger` and reboot if needed.

**Photos print with heavy vertical banding.** Make sure the image-print impl is `bitImageColumn` (default in `bot.py`). Some printer firmware also chokes if the Pi can't keep up — try a shorter USB cable or a powered hub.

**Bot is silent for the friend.** Check `journalctl -u friendprinter` for a `rejected non-whitelisted user` line. The `ALLOWED_USER_ID` in `.env` is the numeric ID, not a `@username`.

**Animated stickers don't print.** Correct — only static images render on a thermal printer. The bot tells the sender.

## What's not here (yet)

- Multiple users
- A web dashboard
- Print queue that survives reboot
- Non-Telegram interfaces
- Anything to do with the housing (decorate it yourself)

## Friend-facing onboarding

[FRIEND_SETUP.md](FRIEND_SETUP.md) is the doc the maintainer sends to the friend who'll be using the printer. It explains, in plain language, how to find their Telegram ID and send the first message. Edit it for your own bot username before sharing.

## License

MIT — see [LICENSE](LICENSE).
