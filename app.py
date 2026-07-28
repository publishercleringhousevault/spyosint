import os
import json
import time
import random
import threading
import subprocess
import re
import csv
from io import StringIO
import requests
from flask import Flask, render_template, request, jsonify, Response, session
from flask_session import Session
from bs4 import BeautifulSoup
from telegram import Bot, Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ============================================
# CONFIG
# ============================================
TELEGRAM_BOT_TOKEN = "8498078774:AAEu_CDDExBDICnA84rV_CWrL0p0Q5bFZU4"
ADMIN_CHAT_ID = 8673303375
ACCESS_KEYS_FILE = "access_keys.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ============================================
# ACCESS KEY MANAGEMENT
# ============================================
def load_keys():
    if os.path.exists(ACCESS_KEYS_FILE):
        with open(ACCESS_KEYS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_keys(keys):
    with open(ACCESS_KEYS_FILE, 'w') as f:
        json.dump(keys, f, indent=2)

def generate_key():
    import secrets
    return secrets.token_urlsafe(16)

def is_valid_key(key):
    keys = load_keys()
    return key in keys

# ============================================
# FLASK APP
# ============================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

PUBLIC_URL = None

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
    }

def format_phone(phone):
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:10]}"
    elif len(digits) == 11 and digits.startswith('1'):
        return f"{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"
    return digits

# ---------- SCRAPERS ----------
def scrape_usphonebook(phone):
    formatted = format_phone(phone)
    url = f"https://www.usphonebook.com/{formatted}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for card in soup.select('.person-card, .result-card, .phone-record, .card'):
            name_elem = card.select_one('.name, h2, h3, .card-title, .person-name')
            name = name_elem.text.strip() if name_elem else ''
            addr_elem = card.select_one('.address, .location, address')
            addr = addr_elem.text.strip() if addr_elem else ''
            phone_type_elem = card.select_one('.phone-type, .carrier')
            phone_type = phone_type_elem.text.strip() if phone_type_elem else ''
            if name:
                details = []
                if addr: details.append(addr)
                if phone_type: details.append(f"Type: {phone_type}")
                results.append({
                    'name': name,
                    'address': addr,
                    'details': ' | '.join(details) if details else 'Phone owner found',
                    'source': 'USPhoneBook'
                })
        if not results:
            headings = soup.select('h1, h2, h3')
            for h in headings:
                text = h.text.strip()
                if len(text) > 3 and not any(x in text.lower() for x in ['phone', 'search', 'free']):
                    results.append({'name': 'USPhoneBook', 'address': '', 'details': text, 'source': 'USPhoneBook'})
                    break
        return results
    except:
        return []

def scrape_truepeoplesearch(phone):
    digits = re.sub(r'\D', '', phone)
    url = f"https://www.truepeoplesearch.com/resultphone?phoneno={digits}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for card in soup.select('.card-summary, .card, .result-card, .person-card'):
            name_elem = card.select_one('.h4, h4, .name, .card-title')
            name = name_elem.text.strip() if name_elem else ''
            addr_elem = card.select_one('.address, .location, .content-value')
            addr = addr_elem.text.strip() if addr_elem else ''
            if name:
                results.append({
                    'name': name,
                    'address': addr,
                    'details': addr if addr else 'Phone match found',
                    'source': 'TruePeopleSearch'
                })
        if not results:
            body = soup.find('body')
            if body and ('Age' in body.text or 'Lives in' in body.text):
                text = ' '.join(body.text.split()[:30])
                results.append({'name': 'TruePeopleSearch Result', 'address': '', 'details': text[:250], 'source': 'TruePeopleSearch'})
        return results
    except:
        return []

def scrape_fastpeoplesearch(phone):
    formatted = format_phone(phone)
    url = f"https://www.fastpeoplesearch.com/{formatted}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for card in soup.select('.detail-box, .card, .result-item, .person-detail'):
            name_elem = card.select_one('h2, h3, .owner-name, .name')
            name = name_elem.text.strip() if name_elem else ''
            addr_elem = card.select_one('.address, .detail-box-address, address')
            addr = addr_elem.text.strip() if addr_elem else ''
            age_elem = card.select_one('.age, .detail-box-age')
            age = age_elem.text.strip() if age_elem else ''
            if name:
                details = []
                if addr: details.append(addr)
                if age: details.append(f"Age: {age}")
                results.append({
                    'name': name,
                    'address': addr,
                    'details': ' | '.join(details) if details else 'Phone owner found',
                    'source': 'FastPeopleSearch'
                })
        if not results:
            headings = soup.select('h1, h2, .phone-owner')
            for h in headings:
                text = h.text.strip()
                if len(text) > 3 and not any(x in text.lower() for x in ['search', 'free']):
                    results.append({'name': 'FastPeopleSearch', 'address': '', 'details': text[:200], 'source': 'FastPeopleSearch'})
                    break
        return results
    except:
        return []

def scrape_whitepages(phone):
    digits = re.sub(r'\D', '', phone)
    url = f"https://www.whitepages.com/phone/{digits}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        name_selectors = ['h2.name', 'span.name', '.person-name', '[data-testid="person-name"]', 'h1.title', '.full-name']
        name = ''
        for sel in name_selectors:
            elem = soup.select_one(sel)
            if elem:
                name = elem.text.strip()
                break
        addr = ''
        addr_selectors = ['.address', '.current-address', '[data-testid="address"]', '.location']
        for sel in addr_selectors:
            elem = soup.select_one(sel)
            if elem:
                addr = elem.text.strip()
                break
        if name or addr:
            title = f"Whitepages: {name}" if name else "Whitepages Result"
            snippet = addr if addr else (f"Phone registered to: {name}" if name else "Phone record found")
            results.append({
                'name': name if name else 'Whitepages',
                'address': addr,
                'details': snippet,
                'source': 'Whitepages'
            })
        else:
            for card in soup.select('.listing, .result-card, .person-card'):
                text = ' '.join(card.text.split()[:20])
                if len(text) > 10:
                    results.append({'name': 'Whitepages Listing', 'address': '', 'details': text[:200], 'source': 'Whitepages'})
        return results
    except:
        return []

# ---------- SEARCH AGGREGATOR ----------
def search_all_sources(phone, first_name='', last_name='', city='', state='', sources=None):
    if sources is None:
        sources = ['usphonebook', 'truepeoplesearch', 'fastpeoplesearch', 'whitepages']
    all_results = []
    scraper_map = {
        'usphonebook': scrape_usphonebook,
        'truepeoplesearch': scrape_truepeoplesearch,
        'fastpeoplesearch': scrape_fastpeoplesearch,
        'whitepages': scrape_whitepages,
    }
    for key in sources:
        if key in scraper_map:
            try:
                res = scraper_map[key](phone)
                all_results.extend(res)
            except:
                pass
            time.sleep(random.uniform(0.5, 1.5))
    # Filter by name, city, state
    filtered = []
    for r in all_results:
        name = r.get('name', '')
        addr = r.get('address', '')
        if first_name and first_name.lower() not in name.lower():
            continue
        if last_name and last_name.lower() not in name.lower():
            continue
        if city and city.lower() not in addr.lower():
            continue
        if state and state.lower() not in addr.lower():
            continue
        filtered.append(r)
    return filtered

# ---------- FLASK ROUTES ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    key = request.form.get('access_key', '').strip()
    if is_valid_key(key):
        session['authenticated'] = True
        return jsonify({'success': True, 'backend_url': PUBLIC_URL or 'http://localhost:5000'})
    return jsonify({'success': False, 'error': 'Invalid access key'}), 401

@app.route('/search', methods=['POST'])
def search():
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    phone = request.form.get('phone', '').strip()
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    city = request.form.get('city', '').strip()
    state = request.form.get('state', '').strip()
    sources = request.form.getlist('sources')
    if not phone:
        return jsonify({'error': 'Phone number is required'}), 400
    if not sources:
        sources = ['usphonebook', 'truepeoplesearch', 'fastpeoplesearch', 'whitepages']
    results = search_all_sources(phone, first_name, last_name, city, state, sources)
    return jsonify({'results': results, 'total': len(results)})

@app.route('/download_csv')
def download_csv():
    if not session.get('authenticated'):
        return "Not authenticated", 401
    phone = request.args.get('phone', '')
    first_name = request.args.get('first_name', '')
    last_name = request.args.get('last_name', '')
    city = request.args.get('city', '')
    state = request.args.get('state', '')
    sources = request.args.getlist('sources')
    if not phone:
        return "Phone number required", 400
    if not sources:
        sources = ['usphonebook', 'truepeoplesearch', 'fastpeoplesearch', 'whitepages']
    results = search_all_sources(phone, first_name, last_name, city, state, sources)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Address', 'Details', 'Source'])
    for r in results:
        writer.writerow([r.get('name', ''), r.get('address', ''), r.get('details', ''), r.get('source', '')])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=osint_results_{phone}.csv'})

@app.route('/send_csv', methods=['POST'])
def send_csv():
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    phone = request.form.get('phone', '')
    first_name = request.form.get('first_name', '')
    last_name = request.form.get('last_name', '')
    city = request.form.get('city', '')
    state = request.form.get('state', '')
    sources = request.form.getlist('sources')
    if not phone:
        return jsonify({'error': 'Phone number required'}), 400
    if not sources:
        sources = ['usphonebook', 'truepeoplesearch', 'fastpeoplesearch', 'whitepages']
    results = search_all_sources(phone, first_name, last_name, city, state, sources)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Address', 'Details', 'Source'])
    for r in results:
        writer.writerow([r.get('name', ''), r.get('address', ''), r.get('details', ''), r.get('source', '')])
    csv_data = output.getvalue()
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        import io
        file = io.BytesIO(csv_data.encode('utf-8'))
        file.name = f'osint_results_{phone}.csv'
        bot.send_document(chat_id=ADMIN_CHAT_ID, document=InputFile(file), caption=f"📊 OSINT Results for {phone}")
        return jsonify({'success': True, 'message': 'CSV sent to Telegram!'})
    except Exception as e:
        return jsonify({'error': f'Failed to send: {str(e)}'}), 500

# ============================================
# TELEGRAM BOT (for key management)
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *Kut Milz OSINT Bot*\n\nCommands:\n/start - Show this\n/genkey - Generate a new access key\n/listkeys - List all keys\n/revoke <key> - Revoke a key", parse_mode='Markdown')

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    new_key = generate_key()
    keys = load_keys()
    keys[new_key] = {"created": time.time(), "created_by": update.effective_user.username or "admin"}
    save_keys(keys)
    await update.message.reply_text(f"🔑 *New Access Key:* `{new_key}`\n\nShare this key with the user to access the OSINT tool.", parse_mode='Markdown')

async def listkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    keys = load_keys()
    if not keys:
        await update.message.reply_text("No keys generated yet.")
        return
    msg = "📋 *Access Keys:*\n"
    for k, v in keys.items():
        msg += f"• `{k}` (created: {time.ctime(v['created'])})\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /revoke <key>")
        return
    key = args[0]
    keys = load_keys()
    if key in keys:
        del keys[key]
        save_keys(keys)
        await update.message.reply_text(f"✅ Key `{key}` revoked.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Key not found.")

def run_telegram():
    app_bot = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("genkey", genkey))
    app_bot.add_handler(CommandHandler("listkeys", listkeys))
    app_bot.add_handler(CommandHandler("revoke", revoke))
    app_bot.run_polling()

# ============================================
# TUNNEL & STARTUP
# ============================================
def start_tunnel():
    global PUBLIC_URL
    # Try cloudflared first
    try:
        subprocess.run(["cloudflared", "--version"], capture_output=True, check=True)
        print("🌐 Starting Cloudflare Tunnel...")
        proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://localhost:5000"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            if "https://" in line:
                match = re.search(r'https://[a-zA-Z0-9\-\.]+\.trycloudflare\.com', line)
                if match:
                    url = match.group(0)
                    PUBLIC_URL = url
                    print(f"✅ Cloudflare Tunnel URL: {PUBLIC_URL}")
                    return proc
            if "ERR" in line or "error" in line.lower():
                break
        print("⚠️ Cloudflared didn't return URL, falling back to ngrok...")
        proc.terminate()
    except:
        print("⚠️ Cloudflared not found, falling back to ngrok...")

    # Ngrok fallback
    try:
        from pyngrok import ngrok
        public_url = ngrok.connect(5000).public_url
        PUBLIC_URL = public_url
        print(f"✅ Ngrok Tunnel URL: {public_url}")
        return None
    except ImportError:
        print("❌ pyngrok not installed. Install with: pip install pyngrok")
        return None

if __name__ == "__main__":
    print("="*60)
    print("Kut Milz OSINT - Flask Backend")
    print("="*60)
    ios = input("Access from iOS? (y/n): ").strip().lower()
    tunnel_proc = None
    if ios == 'y':
        tunnel_proc = start_tunnel()
        if PUBLIC_URL:
            print(f"🌍 Share this URL on your iOS device: {PUBLIC_URL}")
        else:
            print("❌ Failed to create tunnel. Starting local server only.")
    # Start Telegram bot in background
    t = threading.Thread(target=run_telegram, daemon=True)
    t.start()
    print("🤖 Telegram bot started.")
    app.run(debug=False, host='0.0.0.0', port=5000)