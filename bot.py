import requests
import pandas as pd
import time
import os
import json
import re
from dotenv import load_dotenv
from datetime import datetime

print("🚨 BOT STARTING")

load_dotenv(".env")

WEBHOOK_RESTOCKS = os.getenv("DISCORD_WEBHOOK_RESTOCKS") or os.getenv("DISCORD_WEBHOOK")
WEBHOOK_MONITOR = os.getenv("DISCORD_WEBHOOK_MONITOR") or WEBHOOK_RESTOCKS
WEBHOOK_LOGS = os.getenv("DISCORD_WEBHOOK_LOGS") or WEBHOOK_RESTOCKS

print("Restock webhook loaded:", bool(WEBHOOK_RESTOCKS))
print("Monitor webhook loaded:", bool(WEBHOOK_MONITOR))
print("Logs webhook loaded:", bool(WEBHOOK_LOGS))

products = pd.read_csv("products.csv")
previous_status = {}
alerted_urls = {}

CACHE_FILE = "page_cache.json"
CHECK_INTERVAL_SECONDS = 15


def load_page_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_page_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


last_page_content = load_page_cache()


def send_discord_alert(message, channel="restocks"):
    try:
        webhook = WEBHOOK_RESTOCKS

        if channel == "monitor":
            webhook = WEBHOOK_MONITOR
        elif channel == "logs":
            webhook = WEBHOOK_LOGS

        if webhook:
            response = requests.post(webhook, json={"content": message}, timeout=8)
            print(f"Discord {channel} response:", response.status_code)
        else:
            print(f"Discord webhook missing for {channel}")

    except Exception as e:
        print(f"Discord error: {e}")


def get_page_text(url):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(url, headers=headers, timeout=8)
    return response.text.lower()


def is_target_traffic_spike(text):
    traffic_words = [
        "a little busier than we expected",
        "busier than we expected",
        "try again soon",
        "something went wrong",
        "please try again",
        "cart is unavailable",
        "unable to add to cart",
        "high traffic",
        "too much traffic",
    ]
    return any(word in text for word in traffic_words)


def is_real_queue(text):
    strong_queue_signals = [
        "you are in line",
        "estimated wait",
        "wait time",
        "please wait while we verify",
        "queue-it",
        "line is paused",
        "high traffic",
        "waiting room",
        "sign in to join the line",
        "join the line",
    ]

    weak_signals = [
        "queue",
        "traffic",
    ]

    strong = any(s in text for s in strong_queue_signals)
    weak = any(w in text for w in weak_signals)

    return strong or (weak and "add to cart" not in text)


def check_stock(url, text):
    url_lower = url.lower()

    if "target.com" in url_lower and is_target_traffic_spike(text):
        return "TARGET_TRAFFIC_SPIKE"

    queue_words = [
        "queue",
        "waiting room",
        "please wait",
        "you are in line",
        "high traffic",
        "traffic is high",
        "estimated wait",
        "wait time",
        "line is paused",
        "sign in to join the line",
        "join the line",
    ]

    if any(word in text for word in queue_words):
        return "QUEUE_DETECTED"

    search_page_words = [
        "searchpage.jsp",
        "/search?",
        "/s?searchterm=",
        "/s?keyword=",
        "search?q=",
    ]

    if any(word in url_lower for word in search_page_words):
        return "SEARCH_PAGE_CHECK"

    out_stock_words = [
        "out of stock",
        "sold out",
        "currently unavailable",
        "temporarily unavailable",
        "not available",
        "unavailable",
        "coming soon",
        "notify me when available",
        "this item is not available",
        "item is unavailable",
        "no longer available",
    ]

    if any(word in text for word in out_stock_words):
        return "OUT_OF_STOCK"

    if "target.com" in url_lower:
        target_stock_words = [
            "add to cart",
            "ship it",
            "in stock",
            "delivery",
            "pickup",
            "available to ship",
            "ready within",
        ]

        if any(word in text for word in target_stock_words):
            return "IN_STOCK"

        return "OUT_OF_STOCK"

    if "pokemoncenter.com" in url_lower:
        if (
            "out of stock" in text
            or "sold out" in text
            or "unavailable" in text
            or "not available" in text
            or "notify me" in text
        ):
            return "OUT_OF_STOCK"

        if (
            "add to cart" in text
            or "add to bag" in text
            or "addtocart" in text
            or "add-to-cart" in text
        ):
            return "IN_STOCK"

        if "coming soon" in text:
            return "COMING_SOON"

        return "UNKNOWN"

    if "add to cart" in text or "add to bag" in text:
        return "IN_STOCK"

    return "UNKNOWN"


def get_stock_signal(text):
    keywords = [
        "add to cart",
        "add to bag",
        "out of stock",
        "sold out",
        "currently unavailable",
        "temporarily unavailable",
        "not available",
        "coming soon",
        "notify me when available",
        "ship it",
        "pickup",
        "available",
        "delivery",
        "in stock",
        "queue",
        "waiting room",
        "high traffic",
        "sign in to join the line",
        "busier than we expected",
        "try again soon",
        "unable to add to cart",
    ]

    found = []

    for keyword in keywords:
        if keyword in text:
            found.append(keyword)

    return "|".join(found)


def clean_signal(signal):
    if not signal:
        return "No major signal detected"

    parts = signal.split("|")
    return "\n".join([f"• {part.title()}" for part in parts if part.strip()])


def extract_prices(text):
    prices = re.findall(r"\$\d+(?:\.\d{2})?", text)
    clean_prices = []

    for price in prices:
        try:
            number = float(price.replace("$", ""))
            clean_prices.append(number)
        except:
            pass

    return clean_prices


def get_price_range(product):
    p = product.lower()

    if "booster bundle" in p:
        return 26, 32

    if "pc etb" in p or "pokemon center elite trainer" in p:
        return 60, 75

    if "etb" in p or "elite trainer" in p:
        return 45, 65

    if "mini tin" in p:
        return 8, 13

    if "tin" in p:
        return 18, 30

    if "3-pack blister" in p:
        return 12, 18

    if "2-pack blister" in p:
        return 9, 14

    if "single blister" in p or "sleeved booster" in p or "booster pack" in p:
        return 4, 8

    if "ex box" in p:
        return 18, 30

    if "premium collection" in p or "poster collection" in p:
        return 35, 65

    if "sticker" in p:
        return 10, 18

    if "collection" in p or "box" in p:
        return 18, 50

    return None, None


def classify_price(product, prices):
    if not prices:
        return "UNKNOWN_PRICE"

    low, high = get_price_range(product)

    if low is None:
        lowest_price = min(prices)
        return f"PRICE_FOUND (${lowest_price})"

    matching_prices = [p for p in prices if low <= p <= high]

    if matching_prices:
        best_price = min(matching_prices)
        return f"MSRP_OR_CLOSE (${best_price})"

    lowest_price = min(prices)

    if lowest_price > high:
        return f"OVERPRICED (${lowest_price})"

    if lowest_price < low:
        return f"PRICE_SUSPICIOUS (${lowest_price})"

    return f"PRICE_SUSPICIOUS (${lowest_price})"


def format_restock_alert(store, product, status, price_status, url):
    return (
        f"🔥 **PokéPulse-Alerts | Item Live**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product:** {product}\n"
        f"📊 **Status:** {status}\n"
        f"💰 **Price:** {price_status}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 **Buy Link:**\n{url}\n\n"
        f"⚠️ Be signed in and checkout manually."
    )


def format_target_traffic_alert(store, product, url):
    return (
        f"🎯 **TARGET TRAFFIC SPIKE DETECTED**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product:** {product}\n"
        f"📊 **Signal:** Target traffic/cart error detected\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 **Action:** Stay on page and keep trying.\n"
        f"Target may be getting hammered during a real drop.\n\n"
        f"🔗 **Link:**\n{url}"
    )


def format_real_queue_alert(store, product, url):
    return (
        f"🚨 **QUEUE LIVE — ENTER NOW**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product/Search:** {product}\n"
        f"⏳ **Status:** Queue Open / High Traffic\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👉 **Join immediately:**\n{url}\n\n"
        f"⚠️ Be signed in already.\n"
        f"⚠️ Stay ready — drops may follow shortly."
    )


def format_predrop_warning(store, product, url):
    return (
        f"⚠️ **PRE-DROP WARNING**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product/Search:** {product}\n"
        f"⏳ **Signal:** Queue / traffic activity detected\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🚨 **Action:** Sign in now and be ready.\n"
        f"🕒 Possible drop window may be opening soon.\n\n"
        f"🔗 **Link:**\n{url}"
    )


def format_weak_queue_alert(store, product, url):
    return (
        f"🔵 **Queue Signal Detected — Unconfirmed**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product/Search:** {product}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Signal detected, but no confirmed queue access.\n"
        f"This is being routed to monitor-feed only.\n\n"
        f"🔗 **Link:**\n{url}"
    )


def format_monitor_alert(store, product, old_signal, new_signal, url):
    return (
        f"🔵 **PokéPulse Monitor Feed | Search Activity**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product/Search:** {product}\n"
        f"📊 **Signal Change Detected**\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"**Previous Signals:**\n{clean_signal(old_signal)}\n\n"
        f"**Current Signals:**\n{clean_signal(new_signal)}\n\n"
        f"🔗 **Link:**\n{url}\n\n"
        f"ℹ️ This may be preorder, third-party, or search-page movement."
    )


while True:
    print("Starting check cycle...")

    for _, row in products.iterrows():
        store = row["store"]
        product = row["product"]
        url = row["url"]

        print(f"Checking {store} - {product}...")

        try:
            text = get_page_text(url)
            status = check_stock(url, text)
            prices = extract_prices(text)
            price_status = classify_price(product, prices)
        except Exception as e:
            print(f"Error checking {store} - {product}: {e}")
            text = ""
            status = "ERROR"
            price_status = "UNKNOWN_PRICE"

        now = datetime.now()
        date = now.strftime("%Y-%m-%d")
        time_now = now.strftime("%H:%M:%S")

        with open("restock_log.csv", "a", encoding="utf-8") as f:
            f.write(f"{date},{time_now},{store},{product},{status},{price_status},{url}\n")

        # Target traffic spike alert
        if status == "TARGET_TRAFFIC_SPIKE":
            if alerted_urls.get(url) != "TARGET_TRAFFIC_SPIKE":
                print(f"🎯 TARGET TRAFFIC SPIKE: {store} - {product}")
                send_discord_alert(
                    format_target_traffic_alert(store, product, url),
                    channel="restocks",
                )
                alerted_urls[url] = "TARGET_TRAFFIC_SPIKE"

        # Queue system
        if status == "QUEUE_DETECTED":
            if alerted_urls.get(url) != "QUEUE":
                if is_real_queue(text):
                    print(f"🚨 REAL QUEUE CONFIRMED: {store} - {product}")

                    send_discord_alert(
                        format_predrop_warning(store, product, url),
                        channel="restocks",
                    )

                    send_discord_alert(
                        format_real_queue_alert(store, product, url),
                        channel="restocks",
                    )

                    alerted_urls[url] = "QUEUE"
                else:
                    print(f"🔵 Weak queue signal: {store} - {product}")
                    send_discord_alert(
                        format_weak_queue_alert(store, product, url),
                        channel="monitor",
                    )
                    alerted_urls[url] = "WEAK_QUEUE"

        current_signal = get_stock_signal(text)
        previous_signal = last_page_content.get(url, "")

        # Signal changes go to monitor-feed only
        if previous_signal and current_signal != previous_signal:
            print(f"⚡ STOCK SIGNAL CHANGED: {store} - {product}")
            send_discord_alert(
                format_monitor_alert(store, product, previous_signal, current_signal, url),
                channel="monitor",
            )

        last_page_content[url] = current_signal
        save_page_cache(last_page_content)

        # Clean restock alert
        if url in previous_status:
            if previous_status[url] == "OUT_OF_STOCK" and status == "IN_STOCK":
                if "OVERPRICED" not in price_status and "PRICE_SUSPICIOUS" not in price_status:
                    if alerted_urls.get(url) != "IN_STOCK":
                        send_discord_alert(
                            format_restock_alert(store, product, status, price_status, url),
                            channel="restocks",
                        )
                        alerted_urls[url] = "IN_STOCK"

                        send_discord_alert(
                            f"🧾 **Drop Logged**\n\n"
                            f"🏪 Store: {store}\n"
                            f"📦 Product: {product}\n"
                            f"💰 Price: {price_status}\n"
                            f"🕒 Time: {date} {time_now}\n"
                            f"🔗 Link: {url}",
                            channel="logs",
                        )

        previous_status[url] = status

        print(f"{store} - {product}: {status} | {price_status}")

    print(f"Cycle complete. Waiting {CHECK_INTERVAL_SECONDS} seconds...\n")
    time.sleep(CHECK_INTERVAL_SECONDS)
