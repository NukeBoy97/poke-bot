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
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")

print("Webhook loaded:", bool(WEBHOOK_URL))

products = pd.read_csv("products.csv")
previous_status = {}
alerted_urls = {}

CACHE_FILE = "page_cache.json"


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


def send_discord_alert(message):
    try:
        if WEBHOOK_URL:
            response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=8)
            print("Discord response:", response.status_code, response.text)
        else:
            print("Discord webhook not loaded")
    except Exception as e:
        print(f"Discord error: {e}")


def get_page_text(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=8)
    return response.text.lower()


def check_stock(url, text):
    url_lower = url.lower()

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
        "not sold in stores",
        "no longer available",
    ]

    if any(word in text for word in out_stock_words):
        return "OUT_OF_STOCK"

    if "target.com" in url_lower:
        if "add to cart" in text and "ship it" in text:
            return "IN_STOCK"
        return "OUT_OF_STOCK"

    if "pokemoncenter.com" in url_lower:
        if (
            "out of stock" in text
            or "sold out" in text
            or "unavailable" in text
            or "unavailableitem" in text
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
        "queue",
        "waiting room",
        "high traffic",
    ]

    found = []

    for keyword in keywords:
        if keyword in text:
            found.append(keyword)

    return "|".join(found)


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


def classify_price(product, prices):
    if not prices:
        return "UNKNOWN_PRICE"

    lowest_price = min(prices)
    product_lower = product.lower()

    if "booster bundle" in product_lower:
        if lowest_price <= 35:
            return f"MSRP_OR_CLOSE (${lowest_price})"
        return f"OVERPRICED (${lowest_price})"

    if "etb" in product_lower or "elite trainer" in product_lower:
        if lowest_price <= 65:
            return f"MSRP_OR_CLOSE (${lowest_price})"
        return f"OVERPRICED (${lowest_price})"

    if "tin" in product_lower:
        if lowest_price <= 30:
            return f"MSRP_OR_CLOSE (${lowest_price})"
        return f"OVERPRICED (${lowest_price})"

    return f"PRICE_FOUND (${lowest_price})"


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

        # Queue alert with cooldown
        if status == "QUEUE_DETECTED":
            if alerted_urls.get(url) != "QUEUE":
                print(f"⚠️ QUEUE DETECTED: {store} - {product}")

                send_discord_alert(
                    f"⚠️ **PokéPulse-Alerts**\n\n"
                    f"⏳ **Queue Detected**\n"
                    f"🏪 **Store:** {store}\n"
                    f"📦 **Product:** {product}\n\n"
                    f"🔗 **Link:**\n{url}"
                )

                alerted_urls[url] = "QUEUE"

        current_signal = get_stock_signal(text)
        previous_signal = last_page_content.get(url, "")

        if previous_signal and current_signal != previous_signal:
            print(f"⚡ STOCK SIGNAL CHANGED: {store} - {product}")
            send_discord_alert(
                f"⚡ **PokéPulse-Alerts**\n\n"
                f"📊 **Stock Signal Changed**\n"
                f"🏪 **Store:** {store}\n"
                f"📦 **Product:** {product}\n"
                f"Old: {previous_signal}\n"
                f"New: {current_signal}\n\n"
                f"🔗 **Link:**\n{url}"
            )

        last_page_content[url] = current_signal
        save_page_cache(last_page_content)

        # Restock alert with cooldown
        if url in previous_status:
            if previous_status[url] == "OUT_OF_STOCK" and status == "IN_STOCK":
                if "OVERPRICED" not in price_status:
                    if alerted_urls.get(url) != "IN_STOCK":
                        message = (
                            f"🔥 **PokéPulse-Alerts**\n\n"
                            f"🏪 **Store:** {store}\n"
                            f"📦 **Product:** {product}\n"
                            f"📊 **Status:** {status}\n"
                            f"💰 **Price:** {price_status}\n\n"
                            f"🔗 **Link:**\n{url}"
                        )

                        send_discord_alert(message)
                        alerted_urls[url] = "IN_STOCK"

        previous_status[url] = status

        print(f"{store} - {product}: {status} | {price_status}")

    print("Cycle complete. Waiting 30 seconds...\n")
    time.sleep(30)