import pandas as pd
import time
import os
import json
import requests
import subprocess
from dotenv import load_dotenv
from datetime import datetime
from playwright.sync_api import sync_playwright

print('BOT STARTING')
subprocess.run(['playwright', 'install', 'chromium'], check=True)

load_dotenv('.env')

WEBHOOK_RESTOCKS = os.getenv('DISCORD_WEBHOOK_RESTOCKS') or os.getenv('DISCORD_WEBHOOK')
WEBHOOK_MONITOR = os.getenv('DISCORD_WEBHOOK_MONITOR') or WEBHOOK_RESTOCKS
WEBHOOK_LOGS = os.getenv('DISCORD_WEBHOOK_LOGS') or WEBHOOK_RESTOCKS

print('Restock webhook loaded:', bool(WEBHOOK_RESTOCKS))
print('Monitor webhook loaded:', bool(WEBHOOK_MONITOR))
print('Logs webhook loaded:', bool(WEBHOOK_LOGS))

products = pd.read_csv('products.csv')

previous_status = {}
cooldowns = {}
stable_counts = {}
weak_queue_hits = {}

CACHE_FILE = 'page_cache.json'
COOLDOWN_SECONDS = 120
REQUIRED_STABLE_CHECKS = 3
WEAK_QUEUE_COOLDOWN = 600
WEAK_QUEUE_MIN_HITS = 2
BROWSER_RESTART_EVERY = 50


def can_alert(url, alert_type):
    now = time.time()
    key = url + '_' + alert_type
    if key not in cooldowns:
        cooldowns[key] = now
        return True
    if now - cooldowns[key] >= COOLDOWN_SECONDS:
        cooldowns[key] = now
        return True
    return False


def load_page_cache():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


def save_page_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f)


last_page_content = load_page_cache()


def send_discord_alert(message, channel='restocks'):
    try:
        webhook = WEBHOOK_RESTOCKS
        if channel == 'monitor':
            webhook = WEBHOOK_MONITOR
        elif channel == 'logs':
            webhook = WEBHOOK_LOGS
        if webhook:
            response = requests.post(webhook, json={'content': message}, timeout=8)
            print('Discord ' + channel + ' response:', response.status_code)
        else:
            print('Discord webhook missing for ' + channel)
    except Exception as e:
        print('Discord error:', e)


def create_browser(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 800},
    )
    return browser, context


def get_page_text(context, url):
    page = context.new_page()
    try:
        page.goto(url, timeout=10000, wait_until='domcontentloaded')
        time.sleep(1)
        content = page.content().lower()
        page.close()
        return content
    except Exception as e:
        print('Page load error:', e)
        try:
            page.close()
        except:
            pass
        return ''


def is_target_traffic_spike(text):
    traffic_words = [
        'a little busier than we expected',
        'busier than we expected',
        'try again soon',
        'something went wrong',
        'please try again',
        'cart is unavailable',
        'unable to add to cart',
        'too much traffic',
    ]
    return any(word in text for word in traffic_words)


def has_real_queue_access(text):
    strong_signals = [
        'you are in line',
        'estimated wait',
        'wait time',
        'waiting room',
        'your turn is coming',
        'line is paused',
        'queue-it',
    ]
    if any(signal in text for signal in strong_signals):
        return 'STRONG'
    return None


def has_weak_queue_signal(text):
    weak_words = [
        'high traffic',
        'traffic is high',
        'sign in to join the line',
        'join the line',
    ]
    return any(word in text for word in weak_words)


def check_stock(url, text):
    url_lower = url.lower()

    if 'queue-it.net' in url_lower or 'queueit' in url_lower:
        return 'REAL_QUEUE'

    if 'target.com' in url_lower and is_target_traffic_spike(text):
        return 'TARGET_TRAFFIC_SPIKE'

    queue_signal = has_real_queue_access(text)
    if queue_signal == 'STRONG':
        return 'REAL_QUEUE'

    if has_weak_queue_signal(text):
        return 'WEAK_QUEUE'

    search_page_words = [
        'searchpage.jsp',
        '/search?',
        '/s?searchterm=',
        '/s?keyword=',
        'search?q=',
    ]
    if any(word in url_lower for word in search_page_words):
        return 'SEARCH_PAGE_CHECK'

    out_stock_words = [
        'out of stock',
        'sold out',
        'currently unavailable',
        'temporarily unavailable',
        'not available',
        'unavailable',
        'notify me when available',
        'this item is not available',
        'item is unavailable',
        'no longer available',
    ]
    if any(word in text for word in out_stock_words):
        return 'OUT_OF_STOCK'

    if 'target.com' in url_lower:
        target_out_words = [
            'out of stock',
            'sold out',
            'currently unavailable',
            'not available',
            'unavailable',
            'notify me',
        ]
        if any(word in text for word in target_out_words):
            return 'OUT_OF_STOCK'
        target_in_words = [
            'add to cart',
            'ship it',
            'pick up',
            'ready within',
            'available to ship',
        ]
        hits = sum(1 for word in target_in_words if word in text)
        if hits >= 2:
            return 'IN_STOCK'
        return 'OUT_OF_STOCK'

    if 'walmart.com' in url_lower:
        walmart_out_words = [
            'out of stock',
            'sold out',
            'unavailable',
            'not available',
            'notify me',
            'get in-stock alert',
        ]
        if any(word in text for word in walmart_out_words):
            return 'OUT_OF_STOCK'
        walmart_in_words = [
            'add to cart',
            'add to registry',
            'checkout',
            'buy now',
        ]
        if any(word in text for word in walmart_in_words):
            return 'IN_STOCK'
        return 'UNKNOWN'

    if 'pokemoncenter.com' in url_lower:
        pc_out_words = [
            'out of stock',
            'sold out',
            'unavailable',
            'not available',
            'notify me',
        ]
        if any(word in text for word in pc_out_words):
            return 'OUT_OF_STOCK'
        pc_in_words = [
            'add to cart',
            'add to bag',
            'addtocart',
            'add-to-cart',
        ]
        if any(word in text for word in pc_in_words):
            return 'IN_STOCK'
        if 'coming soon' in text:
            return 'COMING_SOON'
        return 'UNKNOWN'

    if 'add to cart' in text or 'add to bag' in text:
        return 'IN_STOCK'

    return 'UNKNOWN'


def get_stock_signal(text):
    keywords = [
        'add to cart',
        'add to bag',
        'out of stock',
        'sold out',
        'coming soon',
        'ship it',
        'pickup',
        'available',
        'delivery',
        'in stock',
        'queue',
        'waiting room',
        'high traffic',
        'sign in to join the line',
        'busier than we expected',
        'try again soon',
        'unable to add to cart',
    ]
    found = []
    for keyword in keywords:
        if keyword in text:
            found.append(keyword)
    return '|'.join(found)


def get_price_range(product):
    p = product.lower()
    if 'booster bundle' in p:
        return 26, 32
    if 'pc etb' in p or 'pokemon center elite trainer' in p:
        return 60, 75
    if 'etb' in p or 'elite trainer' in p:
        return 45, 65
    if 'mini tin' in p:
        return 8, 13
    if 'tin' in p:
        return 18, 30
    if '3-pack blister' in p:
        return 12, 18
    if '2-pack blister' in p:
        return 9, 14
    if 'single blister' in p or 'sleeved booster' in p or 'booster pack' in p:
        return 4, 8
    if 'ex box' in p:
        return 18, 30
    if 'premium collection' in p or 'poster collection' in p:
        return 35, 65
    if 'sticker' in p:
        return 10, 18
    if 'deluxe pin' in p or 'pin collection' in p:
        return 20, 35
    if 'collection' in p or 'box' in p:
        return 18, 50
    return None, None


def classify_price(product, status):
    if status != 'IN_STOCK':
        return 'N/A'
    low, high = get_price_range(product)
    if low is not None:
        mid = (low + high) / 2
        return 'MSRP_ASSUMED ($' + str(mid) + ')'
    return 'MSRP_UNKNOWN'


def is_good_price(price_status):
    return 'MSRP_ASSUMED' in price_status or 'MSRP_OR_CLOSE' in price_status


def format_restock_alert(store, product, status, price_status, url):
    return (
        'POKEPULSE ALERT - ITEM LIVE\n\n'
        'Store: ' + store + '\n'
        'Product: ' + product + '\n'
        'Status: ' + status + '\n'
        'Price: ' + price_status + '\n\n'
        '==================\n\n'
        'Buy Link:\n' + url + '\n\n'
        'Be signed in and checkout manually.'
    )


def format_target_traffic_alert(store, product, url):
    return (
        'Monitor Feed - Target Traffic Spike\n\n'
        'Store: ' + store + '\n'
        'Product: ' + product + '\n\n'
        '==================\n\n'
        'Traffic/cart error detected.\n'
        'This is useful data, but not a confirmed drop.\n\n'
        'Link:\n' + url
    )


def format_real_queue_alert(store, product, url):
    return (
        'REAL QUEUE LIVE - ENTER NOW\n\n'
        'Store: ' + store + '\n'
        'Product: ' + product + '\n'
        'Status: Strong queue access detected\n\n'
        '==================\n\n'
        'Join immediately:\n' + url + '\n\n'
        'Be signed in already.\n'
        'Do not refresh if you enter the line.'
    )


def format_weak_queue_alert(store, product, url):
    return (
        'Monitor Feed - Weak Traffic Signal\n\n'
        'Store: ' + store + '\n'
        'Product: ' + product + '\n\n'
        '==================\n\n'
        'High traffic signal detected.\n'
        'This is NOT confirmed queue access yet.\n\n'
        'Link:\n' + url
    )


cycle_count = 0

with sync_playwright() as playwright:
    browser, context = create_browser(playwright)

    while True:
        cycle_count += 1

        if cycle_count % BROWSER_RESTART_EVERY == 0:
            print('Restarting browser to clear memory...')
            try:
                context.close()
                browser.close()
            except:
                pass
            browser, context = create_browser(playwright)
            print('Browser restarted cleanly.')

        print('Starting check cycle ' + str(cycle_count) + '...')

        for _, row in products.iterrows():
            store = row['store']
            product = row['product']
            url = row['url']

            print('Checking ' + store + ' - ' + product + '...')

            try:
                text = get_page_text(context, url)
                status = check_stock(url, text)
                price_status = classify_price(product, status)
            except Exception as e:
                print('Error checking ' + store + ' - ' + product + ':', e)
                text = ''
                status = 'ERROR'
                price_status = 'UNKNOWN_PRICE'

            now = datetime.now()
            date = now.strftime('%Y-%m-%d')
            time_now = now.strftime('%H:%M:%S')

            with open('restock_log.csv', 'a', encoding='utf-8') as f:
                f.write(date + ',' + time_now + ',' + store + ',' + product + ',' + status + ',' + price_status + ',' + url + '\n')

            if status == 'TARGET_TRAFFIC_SPIKE':
                if previous_status.get(url) != 'TARGET_TRAFFIC_SPIKE':
                    if can_alert(url, 'TARGET_TRAFFIC_SPIKE'):
                        print('TARGET TRAFFIC SPIKE: ' + store + ' - ' + product)
                        send_discord_alert(format_target_traffic_alert(store, product, url), channel='monitor')

            if status == 'REAL_QUEUE':
                if previous_status.get(url) != 'REAL_QUEUE':
                    if can_alert(url, 'REAL_QUEUE'):
                        print('REAL QUEUE CONFIRMED: ' + store + ' - ' + product)
                        send_discord_alert(format_real_queue_alert(store, product, url), channel='restocks')

            if status == 'WEAK_QUEUE':
                weak_queue_hits[url] = weak_queue_hits.get(url, 0) + 1
                if weak_queue_hits[url] >= WEAK_QUEUE_MIN_HITS:
                    if previous_status.get(url) != 'WEAK_QUEUE':
                        key = url + '_WEAK_QUEUE'
                        now_time = time.time()
                        last = cooldowns.get(key, 0)
                        if now_time - last >= WEAK_QUEUE_COOLDOWN:
                            cooldowns[key] = now_time
                            print('WEAK TRAFFIC SIGNAL: ' + store + ' - ' + product)
                            send_discord_alert(format_weak_queue_alert(store, product, url), channel='monitor')
            else:
                weak_queue_hits[url] = 0

            current_signal = get_stock_signal(text)
            last_page_content[url] = current_signal
            save_page_cache(last_page_content)

            if status == 'IN_STOCK':
                stable_counts[url] = stable_counts.get(url, 0) + 1
                if stable_counts[url] >= REQUIRED_STABLE_CHECKS:
                    if previous_status.get(url) != 'IN_STOCK':
                        if is_good_price(price_status):
                            if can_alert(url, 'IN_STOCK'):
                                send_discord_alert(
                                    format_restock_alert(store, product, status, price_status, url),
                                    channel='restocks',
                                )
                                send_discord_alert(
                                    'Drop Logged\n\n'
                                    'Store: ' + store + '\n'
                                    'Product: ' + product + '\n'
                                    'Price: ' + price_status + '\n'
                                    'Time: ' + date + ' ' + time_now + '\n'
                                    'Link: ' + url,
                                    channel='logs',
                                )
            else:
                stable_counts[url] = 0

            previous_status[url] = status
            print(store + ' - ' + product + ': ' + status + ' | ' + price_status)

        print('Cycle ' + str(cycle_count) + ' complete. Waiting 3 seconds...')
        time.sleep(3)

    browser.close()