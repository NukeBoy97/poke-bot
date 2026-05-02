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
cooldowns = {}
stable_counts = {}

CACHE_FILE = "page_cache.json"
CHECK_INTERVAL_SECONDS = 12
COOLDOWN_SECONDS = 120
REQUIRED_STABLE_CHECKS = 2


def can_alert(url, alert_type):
    now = time.time()
    key = f"{url}_{alert_type}"

    if key not in cooldowns:
        cooldowns[key] = now
        return True

    if now - cooldowns[key] >= COOLDOWN_SECONDS:
        cooldowns[key] = now
        return True

    return False


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
        "too much traffic",
    ]
    return any(word in text for word in traffic_words)


def has_real_queue_access(text):
    real_queue_words = [
        "sign in to join the line",
        "join the line",
        "you are in line",
        "estimated wait",
        "wait time",
        "waiting room",
        "line is paused",
        "queue-it",
        "queue it",
    ]
    return any(word in text for word in real_queue_words)


def has_weak_queue_signal(text):
    weak_words = [
        "queue",
        "high traffic",
        "traffic is high",
        "please wait",
        "traffic",
    ]
    return any(word in text for word in weak_words)


def check_stock(url, text):
    url_lower = url.lower()

    if "target.com" in url_lower and is_target_traffic_spike(text):
        return "TARGET_TRAFFIC_SPIKE"

    if has_real_queue_access(text):
        return "REAL_QUEUE"

    if has_weak_queue_signal(text):
        return "WEAK_QUEUE"

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
        pc_out_words = [
            "out of stock",
            "sold out",
            "unavailable",
            "not available",
            "notify me",
        ]

        if any(word in text for word in pc_out_words):
            return "OUT_OF_STOCK"

        pc_in_words = [
            "add to cart",
            "add to bag",
            "addtocart",
            "add-to-cart",
        ]

        if any(word in text for word in pc_in_words):
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
        "coming soon",
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

    if "pc etb" in p or "pokemon center elite trainer" in p or "pokémon center etb" in p:
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


def is_good_price(price_status):
    return "MSRP_OR_CLOSE" in price_status


def format_restock_alert(store, product, status, price_status, url):
    return (
        f"🔥 **PokéPulse-Alerts | ITEM LIVE**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product:** {product}\n"
        f"📊 **Status:** {status}\n"
        f"💰 **Price:** {price_status}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 **Buy Link:**\n{url}\n\n"
        f"⚠️ Be signed in and checkout manually."
    )


def format_target_traffic_alert(store, product, price_status, url):
    return (
        f"🎯 **Monitor Feed | Target Traffic Spike**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product:** {product}\n"
        f"💰 **Price Check:** {price_status}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Traffic/cart error detected.\n"
        f"This is useful data, but not a confirmed drop.\n\n"
        f"🔗 **Link:**\n{url}"
    )


def format_real_queue_alert(store, product, url):
    return (
        f"🚨 **REAL QUEUE LIVE — ENTER NOW**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product:** {product}\n"
        f"⏳ **Status:** Real queue access detected\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👉 **Join immediately:**\n{url}\n\n"
        f"⚠️ Be signed in already.\n"
        f"⚠️ Do not refresh if you enter the line."
    )


def format_predrop_warning(store, product, url):
    return (
        f"⚠️ **PRE-DROP / QUEUE SIGNAL**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product:** {product}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Weak queue/high traffic signal detected.\n"
        f"This is NOT confirmed queue access yet.\n\n"
        f"🔗 **Link:**\n{url}"
    )


def format_monitor_alert(store, product, old_signal, new_signal, url):
    return (
        f"🔵 **PokéPulse Monitor Feed | Signal Change**\n\n"
        f"🏪 **Store:** {store}\n"
        f"📦 **Product/Search:** {product}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"**Previous Signals:**\n{clean_signal(old_signal)}\n\n"
        f"**Current Signals:**\n{clean_signal(new_signal)}\n\n"
        f"🔗 **Link:**\n{url}\n\n"
        f"ℹ️ Useful for pattern tracking, not always actionable."
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

        if status == "TARGET_TRAFFIC_SPIKE":
            if can_alert(url, "TARGET_TRAFFIC_SPIKE"):
                print(f"🎯 TARGET TRAFFIC SPIKE: {store} - {product}")
                send_discord_alert(
                    format_target_traffic_alert(store, product, price_status, url),
                    channel="monitor",
                )

        if status == "REAL_QUEUE":
            if can_alert(url, "REAL_QUEUE"):
                print(f"🚨 REAL QUEUE CONFIRMED: {store} - {product}")
                send_discord_alert(
                    format_real_queue_alert(store, product, url),
                    channel="restocks",
                )

        if status == "WEAK_QUEUE":
            if can_alert(url, "WEAK_QUEUE"):
                print(f"⚠️ WEAK QUEUE SIGNAL: {store} - {product}")
                send_discord_alert(
                    format_predrop_warning(store, product, url),
                    channel="monitor",
                )

        current_signal = get_stock_signal(text)
        previous_signal = last_page_content.get(url, "")

        if previous_signal and current_signal != previous_signal:
            print(f"⚡ SIGNAL CHANGED: {store} - {product}")
            if can_alert(url, "SIGNAL_CHANGE"):
                send_discord_alert(
                    format_monitor_alert(store, product, previous_signal, current_signal, url),
                    channel="monitor",
                )

        last_page_content[url] = current_signal
        save_page_cache(last_page_content)

        if status == "IN_STOCK":
            stable_counts[url] = stable_counts.get(url, 0) + 1

            if stable_counts[url] >= REQUIRED_STABLE_CHECKS:
                if previous_status.get(url) != "IN_STOCK":
                    if is_good_price(price_status):
                        if can_alert(url, "IN_STOCK"):
                            send_discord_alert(
                                format_restock_alert(store, product, status, price_status, url),
                                channel="restocks",
                            )

                            send_discord_alert(
                                f"🧾 **Drop Logged**\n\n"
                                f"🏪 Store: {store}\n"
                                f"📦 Product: {product}\n"
                                f"💰 Price: {price_status}\n"
                                f"🕒 Time: {date} {time_now}\n"
                                f"🔗 Link: {url}",
                                channel="logs",
                            )
        else:
            stable_counts[url] = 0

        previous_status[url] = status

        print(f"{store} - {product}: {status} | {price_status}")

    print(f"Cycle complete. Waiting {CHECK_INTERVAL_SECONDS} seconds...\n")
    time.sleep(CHECK_INTERVAL_SECONDS)