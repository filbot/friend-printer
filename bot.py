"""
Friend-printer bot.

Listens on Telegram for messages from a single whitelisted user and prints
text, photos, and stickers to a USB thermal printer (ESC/POS).
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import random
import sys
import textwrap
import time
from collections import deque
from io import BytesIO
from pathlib import Path

import yaml
from dotenv import load_dotenv
from escpos.printer import File
from PIL import Image, ImageEnhance, ImageOps
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# --- Config loading ----------------------------------------------------------

# Resolve every file path relative to this script, so the bot can be launched
# from any working directory without breaking.
PROJECT_DIR = Path(__file__).resolve().parent

REQUIRED_ENV_VARS = ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_IDS")
REQUIRED_CONFIG_KEYS = (
    "printer_device",
    "paper_width_px",
    "max_prints_per_hour",
    "max_prints_per_day",
    "max_text_length",
    "max_image_dimension",
    "log_path",
)


def _fail(message: str) -> None:
    """Print a friendly error to stderr and exit. Visible in journalctl."""
    print(f"friendprinter: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


load_dotenv(PROJECT_DIR / ".env")

_missing_env = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
if _missing_env:
    _fail(
        f"missing required environment variable(s): {', '.join(_missing_env)}. "
        f"Set them in .env or via systemd EnvironmentFile."
    )

try:
    ALLOWED_USER_IDS = frozenset(
        int(p.strip())
        for p in os.environ["ALLOWED_USER_IDS"].split(",")
        if p.strip()
    )
except ValueError:
    _fail(
        f"ALLOWED_USER_IDS must be comma-separated integer Telegram user IDs, "
        f"got: {os.environ['ALLOWED_USER_IDS']!r}"
    )

if not ALLOWED_USER_IDS:
    _fail("ALLOWED_USER_IDS must contain at least one Telegram user ID.")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

_config_path = PROJECT_DIR / "config.yaml"
try:
    with open(_config_path) as _f:
        CONFIG = yaml.safe_load(_f)
except FileNotFoundError:
    _fail(f"config.yaml not found at {_config_path}")
except yaml.YAMLError as exc:
    _fail(f"config.yaml is not valid YAML: {exc}")

if not isinstance(CONFIG, dict):
    _fail(f"config.yaml must be a mapping, got {type(CONFIG).__name__}")

_missing_cfg = [k for k in REQUIRED_CONFIG_KEYS if k not in CONFIG]
if _missing_cfg:
    _fail(f"config.yaml is missing required key(s): {', '.join(_missing_cfg)}")

# A relative log_path resolves against the project directory.
_log_path = Path(CONFIG["log_path"])
if not _log_path.is_absolute():
    _log_path = PROJECT_DIR / _log_path


# --- Tunable constants -------------------------------------------------------

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

LOG_MAX_BYTES = 1_000_000  # rotate at ~1 MB per file
LOG_BACKUP_COUNT = 3       # keep three older rotations

# 58mm printer: roughly 32 columns at default font.
TEXT_COLUMNS = 32
TRAILING_FEED = "\n\n\n"   # whitespace before each cut

# Image preprocessing tuning. All have been chosen empirically for this printer
# and conservative enough that most photos look better, not worse.
AUTOCONTRAST_CUTOFF_PCT = 2   # trim darkest/lightest 2% of histogram
CONTRAST_BOOST = 1.2          # multiplier applied after autocontrast
WHITE_RGB = (255, 255, 255)
IMAGE_PRINT_IMPL = "bitImageColumn"  # ESC * — see print_image comment


# --- Bot responses -----------------------------------------------------------
# One gets picked at random each time. Keep them short, dry, and printer-aware.

START_MESSAGE = (
    "Hi. I'm a thermal printer living on a desk somewhere. "
    "Send me text, photos, or stickers and I'll print them."
)

REPLY_TEXT_PRINTED = [
    "Done and cut.",
    "Hot off the roll.",
    "Receipt issued.",
    "Whirring complete.",
    "Out it came.",
    "Filed under: printed.",
    "On the desk.",
    "Spat out a fresh one.",
    "Paper warmed, message delivered.",
]

REPLY_PHOTO_PRINTED = [
    "Photo's out.",
    "Pixels-to-dots. Done.",
    "Black-and-white edition, ready.",
    "One dithered masterpiece, served.",
    "Hot off the print head.",
    "Photo on the desk.",
    "Floyd-Steinberged and printed.",
]

REPLY_STICKER_PRINTED = [
    "Sticker on paper.",
    "Sticker dithered and done.",
    "Tiny art, delivered.",
    "Squeezed it through.",
    "Sticker out.",
]

REPLY_TOO_LONG = [
    "That's a novel — {len} characters, I cap at {max}.",
    "I'm a receipt printer, not a book. {len} chars vs my {max} max.",
    "Trim it down — {len} characters, limit's {max}.",
    "Too much paper for one thought. {len} chars, max {max}.",
]

REPLY_PHOTO_TOO_BIG = [
    "That photo's huge — {w}x{h}, max {max} on a side.",
    "Too many pixels: {w}x{h}, my cap is {max} per side.",
    "Bigger than I can think about. {w}x{h}, limit {max}.",
]

REPLY_RATE_LIMIT_HOUR = [
    "Easy there — {limit} prints this hour already. Catch you in a bit.",
    "Need a breather. {limit}/hour is my ceiling.",
    "Pumping the brakes — that's {limit} this hour.",
    "Hit the hourly cap ({limit}). Try again in a bit.",
]

REPLY_RATE_LIMIT_DAY = [
    "That's my daily budget ({limit}). See you tomorrow.",
    "Done for the day — {limit} prints in. Try tomorrow.",
    "Out of paper budget until midnight ({limit}/day).",
]

REPLY_ANIMATED_STICKER = [
    "Can't do moving pictures. Send a still one.",
    "I'm thermal, not cinematic. Stills only.",
    "Paper doesn't animate — try a still sticker.",
    "No moving parts here (well, the cutter). Stills only.",
]

REPLY_PRINT_FAILED = [
    "Mechanical hiccup: {err}",
    "Something jammed up: {err}",
    "The printer's having a moment: {err}",
    "Print didn't take: {err}",
]

REPLY_UNSUPPORTED = [
    "Not sure what to do with that. Text, photos, or stickers, please.",
    "That's not on my menu — text, photos, or stickers only.",
    "I don't speak that format. Try text, photos, or stickers.",
]


def pick(messages: list[str], **fmt: object) -> str:
    return random.choice(messages).format(**fmt)


# --- Logging -----------------------------------------------------------------

logger = logging.getLogger("friendprinter")
logger.setLevel(logging.INFO)

# Rotating file: see LOG_MAX_BYTES / LOG_BACKUP_COUNT.
file_h = logging.handlers.RotatingFileHandler(
    _log_path,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
file_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(file_h)

# stdout: shows up in `journalctl -u friendprinter` once we add the service.
stream_h = logging.StreamHandler()
stream_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(stream_h)


# --- Rate limiter ------------------------------------------------------------


class RateLimiter:
    """Sliding window: counts print events in the last hour and last day."""

    def __init__(self, per_hour: int, per_day: int) -> None:
        self.per_hour = per_hour
        self.per_day = per_day
        self.events: deque[float] = deque()

    def check_and_record(self) -> tuple[bool, str | None]:
        """Returns (allowed, kind) where kind is "hour", "day", or None."""
        now = time.time()
        # Drop events older than a day.
        while self.events and now - self.events[0] > SECONDS_PER_DAY:
            self.events.popleft()

        hour_count = sum(1 for t in self.events if now - t < SECONDS_PER_HOUR)
        day_count = len(self.events)

        if hour_count >= self.per_hour:
            return False, "hour"
        if day_count >= self.per_day:
            return False, "day"

        self.events.append(now)
        return True, None


rate_limiter = RateLimiter(
    per_hour=CONFIG["max_prints_per_hour"],
    per_day=CONFIG["max_prints_per_day"],
)


# --- Printer wrapper ---------------------------------------------------------

# iOS/Android autocorrect produces curly quotes, em dashes, and ellipses that
# the printer's codepages don't contain. Fold them down to ASCII equivalents.
TYPOGRAPHIC_REPLACEMENTS = str.maketrans({
    "‘": "'",   # left single quote
    "’": "'",   # right single quote / apostrophe
    "‚": "'",   # single low-9 quote
    "‛": "'",   # single high-reversed-9 quote
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "„": '"',   # double low-9 quote
    "–": "-",   # en dash
    "—": "-",   # em dash
    "―": "-",   # horizontal bar
    "…": "...", # horizontal ellipsis
    " ": " ",   # non-breaking space
    "•": "*",   # bullet
})


def normalize_for_printer(text: str) -> str:
    """Replace typographic Unicode with ASCII equivalents the printer handles."""
    return text.translate(TYPOGRAPHIC_REPLACEMENTS)


# Serializes access to /dev/usb/lp0. The kernel allows only one writer at a
# time, so without this two concurrent handlers will race and one will get
# EBUSY. asyncio.Lock is the right primitive because all callers are async.
printer_lock = asyncio.Lock()


async def print_text(text: str) -> None:
    """Print wrapped text. Serializes printer access and offloads I/O to a thread."""
    async with printer_lock:
        await asyncio.to_thread(_blocking_print_text, text)


def _blocking_print_text(text: str) -> None:
    text = normalize_for_printer(text)
    # Wrap each paragraph independently so blank lines are preserved.
    paragraphs = text.split("\n")
    wrapped = "\n".join(
        textwrap.fill(line, width=TEXT_COLUMNS) if line else ""
        for line in paragraphs
    )
    p = File(CONFIG["printer_device"])
    try:
        p.text(wrapped + TRAILING_FEED)
        p.cut()
    finally:
        p.close()


async def print_image(img: Image.Image) -> None:
    """Print a PIL image. Serializes printer access and offloads work to a thread.

    Image preprocessing happens inside the lock too. On a single-core Pi the
    extra concurrency wouldn't help, and serializing keeps peak memory bounded.
    """
    async with printer_lock:
        await asyncio.to_thread(_blocking_print_image, img)


def _blocking_print_image(img: Image.Image) -> None:
    target_w = CONFIG["paper_width_px"]

    # Composite RGBA/LA onto white to avoid transparent regions printing as noise.
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, WHITE_RGB)
        bg.paste(img, mask=img.split()[-1])
        img = bg

    img = img.convert("L")  # grayscale

    # Resize to printer width.
    if img.width != target_w:
        ratio = target_w / img.width
        new_h = max(1, int(img.height * ratio))
        img = img.resize((target_w, new_h), Image.LANCZOS)

    # Normalize the histogram so the dither uses the full available range.
    img = ImageOps.autocontrast(img, cutoff=AUTOCONTRAST_CUTOFF_PCT)

    # Thermal prints look muddy without a contrast nudge.
    img = ImageEnhance.Contrast(img).enhance(CONTRAST_BOOST)

    # Floyd-Steinberg dither to 1-bit so the printer doesn't have to guess.
    img = img.convert("1", dither=Image.FLOYDSTEINBERG)

    p = File(CONFIG["printer_device"])
    try:
        # Column mode (ESC *) instead of the default raster (GS v 0).
        # The Winbond-clone POS-5890C produces vertical banding in raster mode
        # because its USB buffer can't keep up with the print head's strobe
        # timing. Column mode sends narrow slices the controller pipelines
        # cleanly.
        p.image(
            img,
            impl=IMAGE_PRINT_IMPL,
            high_density_vertical=True,
            high_density_horizontal=True,
        )
        p.text(TRAILING_FEED)
        p.cut()
    finally:
        p.close()


# --- Whitelist gate ----------------------------------------------------------


def is_authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ALLOWED_USER_IDS


async def log_rejected(update: Update) -> None:
    user = update.effective_user
    logger.warning(
        "rejected non-whitelisted user id=%s username=%s",
        user.id if user else "?",
        user.username if user else "?",
    )
    # Stay silent. Don't confirm the bot exists to strangers.


# --- Handlers ----------------------------------------------------------------


def rate_limit_reply(kind: str) -> str:
    if kind == "hour":
        return pick(REPLY_RATE_LIMIT_HOUR, limit=CONFIG["max_prints_per_hour"])
    return pick(REPLY_RATE_LIMIT_DAY, limit=CONFIG["max_prints_per_day"])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await log_rejected(update)
        return
    await update.message.reply_text(START_MESSAGE)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await log_rejected(update)
        return

    text = update.message.text or ""
    max_len = CONFIG["max_text_length"]
    if len(text) > max_len:
        await update.message.reply_text(pick(REPLY_TOO_LONG, len=len(text), max=max_len))
        logger.info("rejected oversized text: %d chars", len(text))
        return

    ok, kind = rate_limiter.check_and_record()
    if not ok:
        await update.message.reply_text(rate_limit_reply(kind))
        logger.info("rate-limited text: %s", kind)
        return

    try:
        await print_text(text)
    except Exception as exc:
        logger.exception("print_text failed")
        await update.message.reply_text(pick(REPLY_PRINT_FAILED, err=exc))
        return

    await update.message.reply_text(pick(REPLY_TEXT_PRINTED))
    logger.info("printed text: %d chars", len(text))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await log_rejected(update)
        return

    # Telegram sends each photo in several sizes; the largest is last.
    photo = update.message.photo[-1]

    max_dim = CONFIG["max_image_dimension"]
    if max(photo.width, photo.height) > max_dim:
        await update.message.reply_text(
            pick(REPLY_PHOTO_TOO_BIG, w=photo.width, h=photo.height, max=max_dim)
        )
        logger.info("rejected oversized photo: %dx%d", photo.width, photo.height)
        return

    ok, kind = rate_limiter.check_and_record()
    if not ok:
        await update.message.reply_text(rate_limit_reply(kind))
        logger.info("rate-limited photo: %s", kind)
        return

    try:
        tg_file = await photo.get_file()
        buf = BytesIO()
        await tg_file.download_to_memory(buf)
        buf.seek(0)
        with Image.open(buf) as img:
            await print_image(img)
    except Exception as exc:
        logger.exception("print photo failed")
        await update.message.reply_text(pick(REPLY_PRINT_FAILED, err=exc))
        return

    await update.message.reply_text(pick(REPLY_PHOTO_PRINTED))
    logger.info("printed photo: %dx%d", photo.width, photo.height)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await log_rejected(update)
        return

    sticker = update.message.sticker

    if sticker.is_animated or sticker.is_video:
        await update.message.reply_text(pick(REPLY_ANIMATED_STICKER))
        logger.info("rejected animated sticker")
        return

    ok, kind = rate_limiter.check_and_record()
    if not ok:
        await update.message.reply_text(rate_limit_reply(kind))
        return

    try:
        tg_file = await sticker.get_file()
        buf = BytesIO()
        await tg_file.download_to_memory(buf)
        buf.seek(0)
        with Image.open(buf) as img:
            await print_image(img)
    except Exception as exc:
        logger.exception("print sticker failed")
        await update.message.reply_text(pick(REPLY_PRINT_FAILED, err=exc))
        return

    await update.message.reply_text(pick(REPLY_STICKER_PRINTED))
    logger.info("printed sticker: %s", sticker.emoji or "?")


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        await log_rejected(update)
        return
    await update.message.reply_text(pick(REPLY_UNSUPPORTED))


# --- Entry point -------------------------------------------------------------


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    # Anything else: explain.
    app.add_handler(
        MessageHandler(
            ~(filters.TEXT | filters.PHOTO | filters.Sticker.ALL | filters.COMMAND),
            handle_unsupported,
        )
    )

    logger.info("bot starting")
    app.run_polling()


if __name__ == "__main__":
    main()
