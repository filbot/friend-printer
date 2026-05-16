# Welcome to the Friend Printer

I've set up a tiny thermal printer that lives on my desk. It prints whatever you send it from Telegram — text, photos, stickers — as little receipt-sized printouts that pile up until I take them down.

Here's how to get hooked up. About five minutes, no technical knowledge needed.

## 1. Get Telegram

If you don't already have it, grab Telegram from your phone's app store (search "Telegram" — the icon is a white paper airplane on a blue circle). Sign up with your phone number when it asks. Free, ad-free, no fuss.

## 2. Find your Telegram ID

To let you in, I need your unique Telegram ID number — not your username or your phone number, but a number Telegram assigns every account. It looks like `123456789`.

Easiest way to find it:

1. Open Telegram.
2. Tap the magnifying glass (search icon) — top right on iPhone, top of the screen on Android.
3. Type `userinfobot` and tap the result that appears. It should have a blue checkmark next to its name (that means it's the verified, legit one).
4. Tap the **Start** button at the bottom of the chat.
5. It'll immediately send you back a few lines of info. Look for the line that says `Id: 123456789` (your number will be different).
6. **Send me that number.** A screenshot is fine, or just type it out.

That's everything I need from your end.

## 3. Wait for me to add you

Once I have your ID, I'll add it to the printer's allowlist and send you the bot's username. This step exists so random strangers can't print things to my desk.

## 4. Open a chat with the printer bot

When I send you the bot's username (it'll look something like `@filip_friendprinter_bot`):

1. Open Telegram.
2. Tap the search icon again.
3. Paste or type the bot's username.
4. Tap it when it appears in the search results.
5. You'll see a chat screen with a blue **Start** button at the bottom. Tap it.

The bot will reply with a quick hello. That means you're connected.

## 5. Send things

Just send messages like you would to a person. A few notes on what works:

**Text** — Anything up to about 2,000 characters. Apostrophes, dashes, and quotes from your phone's autocorrect get cleaned up for you. Emojis won't actually print though — it's a thermal printer with no colour and no fancy fonts, so they come out blank or as a question mark.

**Photos** — Tap the paperclip icon (iPhone) or attachment icon (Android), pick a photo, send. The printer turns it into a black-and-white dithered version (think old newspaper photos). Looks better than you'd expect.

**Stickers** — Use the sticker keyboard like normal. Only still stickers work — animated ones can't print since paper doesn't move. The bot will tell you if you send a moving one.

The bot replies with a quick acknowledgment when each thing prints. Most things print within a few seconds.

## A few things worth knowing

There are some limits: roughly 30 prints per hour, 200 per day. Plenty for normal use, but the printer will tell you if you hit either, and you can just try again later.

Don't send anything you wouldn't want sitting on my desk where I'll see it. I see every print.

If the bot stops responding entirely, the Pi probably lost power or wifi — message me directly and I'll go poke at it.

That's it. Send whatever, whenever. No need to wait for me to be around.
