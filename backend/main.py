import os
import sys
import json
import random
import io
import time
import uuid
import logging
from datetime import datetime, timedelta
from threading import Thread
import asyncio
import socket
import ssl

# Fix for SSL/TLS on Render
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except:
    pass

from flask import Flask, render_template, jsonify, request, send_from_directory, send_file, Response
from flask_cors import CORS
import aiohttp
import discord
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pymongo import MongoClient
import psutil
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Ensure UTF-8 output encoding for Windows terminals
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ============ CONFIGURATION ============
# MongoDB URI with new credentials
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://dace1111zin_db_user:Si18hD9ebhlcFzEY@cluster0.kxpnzpk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
SECRET_KEY = os.getenv("SECRET_KEY", "bot_bro_secret_key_2026")
PORT = int(os.getenv("PORT", 8080))

# MongoDB Connection — Secure connection with certifi
def _try_mongo_connect(uri):
    """Connect to MongoDB Atlas securely using certifi"""
    try:
        print("🔄 Connecting MongoDB Atlas...")
        
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            tls=True,
            tlsCAFile=certifi.where()
        )
        
        # Test connection
        client.admin.command("ping")
        
        print("✅ MongoDB Atlas Connected!")
        return client, True
        
    except Exception as e:
        print(f"❌ MongoDB Error: {e}")
        return None, False

try:
    _mc, mongo_connected = _try_mongo_connect(MONGO_URI)
    if mongo_connected and _mc is not None:
        mongo_client = _mc
        db = mongo_client["bot_bro_db"]
        config_col = db["bot_config"]
        logs_col = db["activity_logs"]
        analytics_col = db["analytics"]
        print("✅ Connected to MongoDB Atlas successfully!")
    else:
        raise ConnectionError("MongoDB connection failed")
except Exception as e_mongo:
    mongo_connected = False
    print(f"⚠️ MongoDB Connection warning: {e_mongo}")
    print("⚠️ Continuing with local storage fallback...")
    db = None
    config_col = None
    logs_col = None
    analytics_col = None


current_dir = os.path.dirname(os.path.abspath(__file__))
frontend_dir = os.path.join(current_dir, '..', 'frontend')
UPLOAD_FOLDER = os.path.join(current_dir, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BOT_START_TIME = datetime.now()

# In-memory config fallback if Mongo offline
local_config_store = {}
local_logs_store = []
local_analytics_store = {"welcome_cards_sent": 0, "joins_today": 0, "leaves_today": 0}

# Default Fallback Images
DEFAULT_BG_1 = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=1200&auto=format&fit=crop"
DEFAULT_BG_2 = "https://images.unsplash.com/photo-1579546929518-9e396f3cc809?q=80&w=1200&auto=format&fit=crop"

# ============ CONFIG HELPERS ============
def get_default_config():
    return {
        "_id": "main_config",
        "bot_token": DISCORD_TOKEN,
        "server_id": "",
        "welcome_channel_id": "",
        "welcome_text": "🎉 Welcome {mention} to **{server}**! You are member #{count}",
        "embed_color": "#3498db",
        "auto_role_id": "",
        "auto_nickname": "",
        "language": "km",
        "background_images": [
            {
                "id": "def_1",
                "name": "Abstract Purple Wave",
                "url": DEFAULT_BG_1,
                "is_default": True,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            {
                "id": "def_2",
                "name": "Neon Gradient",
                "url": DEFAULT_BG_2,
                "is_default": False,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        ],
        "selected_welcome_image": "",
        "use_random": True,
        "no_repeat_mode": True,
        "last_used_bg": "",
        "card_font_size": 32,
        "card_font_color": "#FFFFFF",
        "card_avatar_size": 180,
        "card_avatar_pos_x": 360,
        "card_avatar_pos_y": 70,
        "card_avatar_border_color": "#00E5FF",
        "card_avatar_border_width": 4,
        "card_avatar_glow_color": "#FF3B9A",
        "card_avatar_glow_size": 14,
        "card_shadow_opacity": 0.5,
        "card_blur_radius": 0,
        "card_gradient_overlay": "rgba(0,0,0,0.3)",
        "card_text_pos_x": 450,
        "card_text_pos_y": 410,
        "show_discord_logo": True
    }


def normalize_backgrounds(bg_list):
    normalized = []
    if not isinstance(bg_list, list):
        return normalized
    for idx, item in enumerate(bg_list):
        if isinstance(item, str):
            clean_str = item.strip()
            if clean_str:
                normalized.append({
                    "id": f"bg_str_{idx}",
                    "name": clean_str.split('/')[-1] or f"Background {idx+1}",
                    "url": clean_str,
                    "is_default": (idx == 0),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        elif isinstance(item, dict):
            normalized.append(item)
    return normalized

def load_config():
    global local_config_store
    if mongo_connected and config_col is not None:
        try:
            config = config_col.find_one({"_id": "main_config"})
            if config:
                defaults = get_default_config()
                for k, v in defaults.items():
                    if k not in config:
                        config[k] = v
                config["background_images"] = normalize_backgrounds(config.get("background_images", []))
                return config
            else:
                defaults = get_default_config()
                config_col.insert_one(defaults)
                return defaults
        except Exception as e:
            print(f"Error loading config from MongoDB: {e}")
    
    if not local_config_store:
        local_config_store = get_default_config()
    local_config_store["background_images"] = normalize_backgrounds(local_config_store.get("background_images", []))
    return local_config_store


def save_config(data):
    global local_config_store
    data["_id"] = "main_config"
    if mongo_connected and config_col is not None:
        try:
            config_col.replace_one({"_id": "main_config"}, data, upsert=True)
        except Exception as e:
            print(f"Error saving config to MongoDB: {e}")
    local_config_store = data

def log_activity(action_type, title, details="", user="System"):
    log_entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%d %b %Y %H:%M:%S"),
        "type": action_type,
        "title": title,
        "details": details,
        "user": user
    }
    if mongo_connected and logs_col is not None:
        try:
            logs_col.insert_one(log_entry)
        except Exception as e:
            print(f"Error saving log: {e}")
    else:
        local_logs_store.insert(0, log_entry)
        if len(local_logs_store) > 200:
            local_logs_store.pop()

def increment_analytic(key, count=1):
    if mongo_connected and analytics_col is not None:
        try:
            analytics_col.update_one({"_id": "stats"}, {"$inc": {key: count}}, upsert=True)
        except Exception as e:
            print(f"Error incrementing analytics: {e}")
    else:
        local_analytics_store[key] = local_analytics_store.get(key, 0) + count

def get_analytics():
    if mongo_connected and analytics_col is not None:
        try:
            data = analytics_col.find_one({"_id": "stats"})
            if data:
                data.pop("_id", None)
                return data
        except Exception as e:
            print(f"Error fetching analytics: {e}")
    return local_analytics_store

# ============ DISCORD BOT SETUP ============
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

client = discord.Client(intents=intents)
bot_loop = None

def run_async(coro):
    """Bridge sync Flask calls to async Discord loop safely"""
    if bot_loop and bot_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, bot_loop)
        try:
            return future.result(timeout=10)
        except Exception as e:
            print(f"Async execution error: {e}")
            return {"error": str(e)}
    return {"error": "Bot loop is not running"}

def safe_int(val, default):
    try:
        if val is None or val == "":
            return default
        return int(val)
    except (ValueError, TypeError):
        return default

IMAGE_CACHE = {}

async def fetch_image_cached(url):
    if not url:
        return None
    if url in IMAGE_CACHE:
        try:
            return IMAGE_CACHE[url].copy()
        except:
            pass
    try:
        if url.startswith("http"):
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=3) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        img = Image.open(io.BytesIO(content)).convert("RGBA")
                        IMAGE_CACHE[url] = img
                        return img.copy()
        elif url.startswith("/uploads/"):
            local_p = os.path.join(current_dir, url.lstrip('/'))
            if os.path.exists(local_p):
                img = Image.open(local_p).convert("RGBA")
                IMAGE_CACHE[url] = img
                return img.copy()
    except Exception as e:
        print(f"Error caching image ({url}): {e}")
    return None

# ============ PILLOW WELCOME CARD GENERATOR ============
async def generate_welcome_card(member_name, avatar_url, server_name, member_count, config_override=None):
    """
    Generates a 900x500 HD Welcome Card using Pillow
    """
    config = config_override or load_config()
    
    bg_list = config.get("background_images", [])
    selected_id = config.get("selected_welcome_image", "")
    use_random = config.get("use_random", True)
    no_repeat = config.get("no_repeat_mode", True)
    last_used = config.get("last_used_bg", "")

    # Pick background URL
    chosen_bg_url = DEFAULT_BG_1
    
    if bg_list:
        if not use_random and selected_id:
            found = next((bg for bg in bg_list if isinstance(bg, dict) and (bg.get("id") == selected_id or bg.get("url") == selected_id)), None)
            if found:
                chosen_bg_url = found.get("url")
            else:
                chosen_bg_url = bg_list[0].get("url") if isinstance(bg_list[0], dict) else str(bg_list[0])
        else:
            # Random Mode
            valid_bgs = [bg.get("url") for bg in bg_list if isinstance(bg, dict) and bg.get("url")]
            if len(valid_bgs) > 1 and no_repeat and last_used in valid_bgs:
                candidates = [url for url in valid_bgs if url != last_used]
                chosen_bg_url = random.choice(candidates)
            elif valid_bgs:
                chosen_bg_url = random.choice(valid_bgs)
    
    # Save last used
    config["last_used_bg"] = chosen_bg_url
    save_config(config)

    # Fetch/Load Background Image with Cache
    bg_image = await fetch_image_cached(chosen_bg_url)
    if not bg_image:
        bg_image = Image.new("RGBA", (900, 500), (30, 20, 50, 255))
        draw_fallback = ImageDraw.Draw(bg_image)
        for y in range(500):
            r = int(20 + (y / 500) * 40)
            g = int(15 + (y / 500) * 20)
            b = int(50 + (y / 500) * 80)
            draw_fallback.line([(0, y), (900, y)], fill=(r, g, b, 255))

    # Resize background to 900x500
    bg_image = ImageOps.fit(bg_image, (900, 500), centering=(0.5, 0.5))

    # Optional Blur
    blur_r = float(config.get("card_blur_radius", 0))
    if blur_r > 0:
        bg_image = bg_image.filter(ImageFilter.GaussianBlur(blur_r))

    # Dark Gradient Overlay
    overlay = Image.new("RGBA", (900, 500), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), (900, 500)], fill=(10, 10, 25, 90))
    bg_image = Image.alpha_composite(bg_image, overlay)

    # Fetch/Load Avatar with Cache
    avatar_img = await fetch_image_cached(avatar_url)
    if not avatar_img:
        avatar_img = Image.new("RGBA", (200, 200), (100, 100, 250, 255))
        d_av = ImageDraw.Draw(avatar_img)
        d_av.ellipse((10, 10, 190, 190), fill=(255, 59, 154, 255))

    # Process Circular Avatar with Glow & Border
    avatar_size = safe_int(config.get("card_avatar_size"), 180)
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

    # Circular mask
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)

    # Composite canvas for card
    card_canvas = bg_image.copy()

    # Calculate avatar position
    default_av_x = (900 - avatar_size) // 2
    av_x = safe_int(config.get("card_avatar_pos_x"), default_av_x)
    av_y = safe_int(config.get("card_avatar_pos_y"), 70)

    # Draw Glow Effect behind avatar
    glow_size = safe_int(config.get("card_avatar_glow_size"), 14)
    if glow_size > 0:
        glow_color = config.get("card_avatar_glow_color", "#FF3B9A")
        glow_canvas = Image.new("RGBA", (900, 500), (0, 0, 0, 0))
        d_glow = ImageDraw.Draw(glow_canvas)
        try:
            glow_hex = glow_color.lstrip('#')
            r, g, b = tuple(int(glow_hex[i:i+2], 16) for i in (0, 2, 4))
        except:
            r, g, b = (255, 59, 154)

        pad = glow_size * 2
        d_glow.ellipse((av_x - pad, av_y - pad, av_x + avatar_size + pad, av_y + avatar_size + pad), fill=(r, g, b, 180))
        glow_canvas = glow_canvas.filter(ImageFilter.GaussianBlur(glow_size))
        card_canvas = Image.alpha_composite(card_canvas, glow_canvas)

    # Paste Avatar
    card_canvas.paste(avatar_img, (av_x, av_y), mask)

    # Draw Avatar Ring / Border
    border_w = safe_int(config.get("card_avatar_border_width"), 4)
    if border_w > 0:
        border_color = config.get("card_avatar_border_color", "#00E5FF")
        try:
            b_hex = border_color.lstrip('#')
            br, bg, bb = tuple(int(b_hex[i:i+2], 16) for i in (0, 2, 4))
        except:
            br, bg, bb = (0, 229, 255)
        
        ring_canvas = Image.new("RGBA", (900, 500), (0, 0, 0, 0))
        d_ring = ImageDraw.Draw(ring_canvas)
        d_ring.ellipse((av_x - border_w, av_y - border_w, av_x + avatar_size + border_w, av_y + avatar_size + border_w), outline=(br, bg, bb, 255), width=border_w)
        card_canvas = Image.alpha_composite(card_canvas, ring_canvas)

    # Draw Text
    draw_text = ImageDraw.Draw(card_canvas)
    
    pos_x = safe_int(config.get("card_text_pos_x"), 450)
    pos_y = safe_int(config.get("card_text_pos_y"), 320)
    font_size = safe_int(config.get("card_font_size"), 32)

    font_color_hex = config.get("card_font_color", "#FFFFFF")

    # Font handling
    font_main = ImageFont.load_default()
    font_sub = ImageFont.load_default()
    try:
        font_path = "arial.ttf"
        if os.name == 'nt':
            font_path = "C:\\Windows\\Fonts\\arial.ttf"
        font_main = ImageFont.truetype(font_path, font_size)
        font_sub = ImageFont.truetype(font_path, int(font_size * 0.7))
    except:
        pass

    # Title: WELCOME
    title_str = "WELCOME TO THE SERVER!"
    draw_text.text((pos_x, pos_y), title_str, fill=(255, 215, 0, 255), anchor="mm", font=font_sub)

    # Username
    user_str = str(member_name)
    draw_text.text((pos_x, pos_y + 40), user_str, fill=(255, 255, 255, 255), anchor="mm", font=font_main)

    # Subtext (Member Count & Server)
    sub_str = f"Member #{member_count} • {server_name}"
    draw_text.text((pos_x, pos_y + 85), sub_str, fill=(180, 220, 255, 230), anchor="mm", font=font_sub)

    # Save to BytesIO
    buf = io.BytesIO()
    card_canvas.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf

# ============ FLASK WEB DASHBOARD ============
app = Flask(__name__, template_folder=frontend_dir)
CORS(app, origins=[
    "https://bot-bro-flax.vercel.app",
    "https://bot-bro-l2vf.onrender.com",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# --- SYSTEM STATS & HEALTH ---
@app.route('/api/stats')
def api_stats():
    is_ready = client.is_ready() if client else False
    ping = 0
    guilds_count = 0
    total_members = 0
    humans_count = 0
    bots_count = 0
    channels_count = 0
    roles_count = 0

    if is_ready:
        try:
            latency = client.latency
            ping = 0 if latency == float('inf') else round(latency * 1000)
            guilds_count = len(client.guilds)
            for g in client.guilds:
                total_members += g.member_count or 0
                channels_count += len(g.channels)
                roles_count += len(g.roles)
                for m in g.members:
                    if m.bot:
                        bots_count += 1
                    else:
                        humans_count += 1
        except Exception as e:
            print(f"Stats calculation error: {e}")

    # System Usage
    cpu_usage = psutil.cpu_percent(interval=None)
    ram_usage = psutil.virtual_memory().percent

    uptime_delta = datetime.now() - BOT_START_TIME
    hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    return jsonify({
        "status": "ONLINE" if is_ready else "OFFLINE",
        "ping": ping,
        "uptime": uptime_str,
        "server_count": guilds_count,
        "total_members": total_members,
        "humans_count": humans_count,
        "bots_count": bots_count,
        "channels_count": channels_count,
        "roles_count": roles_count,
        "cpu_usage": cpu_usage,
        "ram_usage": ram_usage,
        "mongo_connected": mongo_connected
    })

@app.route('/api/server_info')
def api_server_info():
    config = load_config()
    server_id = config.get("server_id", "").strip()
    if not server_id or not client.is_ready():
        return jsonify({"error": "No Server ID configured or Bot is Offline"})
    try:
        guild = client.get_guild(int(server_id))
        if guild:
            icon_url = guild.icon.url if guild.icon else f"https://ui-avatars.com/api/?name={guild.name}&background=random"
            return jsonify({
                "id": str(guild.id),
                "name": guild.name,
                "icon": icon_url,
                "member_count": guild.member_count,
                "roles_count": len(guild.roles),
                "channels_count": len(guild.channels)
            })
        return jsonify({"error": "Bot is not in specified Server ID"})
    except Exception as e:
        return jsonify({"error": f"Invalid Server ID: {e}"})

# --- CONFIG API ---
@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        data = request.json or {}
        existing = load_config()
        for k, v in data.items():
            existing[k] = v
        save_config(existing)
        log_activity("settings", "Bot Settings Updated", "Owner updated dashboard settings.", "Owner")
        return jsonify({"message": "Settings updated successfully!", "config": existing})
    
    config = load_config()
    config.pop("_id", None)
    return jsonify(config)

# --- BACKGROUND GALLERY API ---
@app.route('/api/backgrounds', methods=['GET'])
def api_backgrounds():
    config = load_config()
    return jsonify({
        "backgrounds": config.get("background_images", []),
        "selected_id": config.get("selected_welcome_image", ""),
        "use_random": config.get("use_random", True),
        "no_repeat_mode": config.get("no_repeat_mode", True)
    })

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'files' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    files = request.files.getlist('files')
    uploaded_items = []
    config = load_config()
    bg_list = config.get("background_images", [])

    allowed_exts = ('.png', '.jpg', '.jpeg', '.webp')
    for file in files:
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_exts:
                continue
            
            new_id = f"bg_{uuid.uuid4().hex[:8]}"
            clean_name = os.path.basename(file.filename)
            save_name = f"{new_id}{ext}"
            file_path = os.path.join(UPLOAD_FOLDER, save_name)
            file.save(file_path)

            url = f"/uploads/{save_name}"
            item = {
                "id": new_id,
                "name": clean_name,
                "url": url,
                "is_default": False,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            bg_list.append(item)
            uploaded_items.append(item)

    config["background_images"] = bg_list
    save_config(config)
    log_activity("upload", "Background Uploaded", f"Uploaded {len(uploaded_items)} new background images.", "Owner")

    return jsonify({"message": f"Successfully uploaded {len(uploaded_items)} images!", "uploaded": uploaded_items})

@app.route('/api/background/<bg_id>', methods=['DELETE'])
def api_delete_background(bg_id):
    config = load_config()
    bg_list = config.get("background_images", [])
    
    target = next((bg for bg in bg_list if bg.get("id") == bg_id), None)
    if not target:
        return jsonify({"error": "Background not found"}), 404
    
    # Remove file if local upload
    url = target.get("url", "")
    if url.startswith("/uploads/"):
        filename = url.replace("/uploads/", "")
        file_p = os.path.join(UPLOAD_FOLDER, filename)
        if os.path.exists(file_p):
            try:
                os.remove(file_p)
            except Exception as e:
                print(f"Error deleting file: {e}")

    bg_list = [bg for bg in bg_list if bg.get("id") != bg_id]
    config["background_images"] = bg_list
    if config.get("selected_welcome_image") == bg_id:
        config["selected_welcome_image"] = ""
    save_config(config)

    log_activity("delete", "Background Deleted", f"Deleted background: {target.get('name')}", "Owner")
    return jsonify({"message": "Background deleted successfully"})

@app.route('/api/background/rename', methods=['POST'])
def api_rename_background():
    data = request.json or {}
    bg_id = data.get("id")
    new_name = data.get("name", "").strip()
    if not bg_id or not new_name:
        return jsonify({"error": "Invalid request"}), 400
    
    config = load_config()
    bg_list = config.get("background_images", [])
    for bg in bg_list:
        if bg.get("id") == bg_id:
            bg["name"] = new_name
            break
    config["background_images"] = bg_list
    save_config(config)
    return jsonify({"message": "Renamed background successfully"})

@app.route('/api/background/set_default', methods=['POST'])
def api_set_default_background():
    data = request.json or {}
    bg_id = data.get("id")
    config = load_config()
    bg_list = config.get("background_images", [])
    for bg in bg_list:
        bg["is_default"] = (bg.get("id") == bg_id)
    config["background_images"] = bg_list
    config["selected_welcome_image"] = bg_id
    save_config(config)
    return jsonify({"message": "Default background updated!"})

# --- LIVE PREVIEW WELCOME CARD ---
@app.route('/api/preview', methods=['POST', 'GET'])
def api_preview():
    config = load_config()
    if request.method == 'POST':
        override = request.json or {}
        for k, v in override.items():
            config[k] = v

    # Transient overrides from GET query params
    int_keys = ['card_font_size', 'card_avatar_size', 'card_avatar_pos_x', 'card_avatar_pos_y', 'card_avatar_border_width', 'card_avatar_glow_size', 'card_text_pos_x', 'card_text_pos_y']
    str_keys = ['card_font_color', 'card_avatar_border_color', 'card_avatar_glow_color']
    
    for key in int_keys:
        val = request.args.get(key)
        if val is not None:
            try: config[key] = int(val)
            except: pass
    for key in str_keys:
        val = request.args.get(key)
        if val is not None and val.strip():
            config[key] = str(val).strip()

    sample_name = request.args.get("name", "DiscordUser#1234")
    sample_avatar = request.args.get("avatar", "https://cdn.discordapp.com/embed/avatars/0.png")
    sample_server = request.args.get("server", "Awesome Discord Community")
    sample_count = request.args.get("count", "1,248")

    # Run generator sync inside loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        card_buf = loop.run_until_complete(
            generate_welcome_card(sample_name, sample_avatar, sample_server, sample_count, config_override=config)
        )
        loop.close()
        return Response(card_buf.getvalue(), mimetype='image/png')
    except Exception as e:
        print(f"Error producing preview: {e}")
        return jsonify({"error": str(e)}), 500

# --- MEMBERS MANAGEMENT ---
@app.route('/api/members')
def api_members():
    config = load_config()
    server_id = config.get("server_id", "").strip()
    query = request.args.get("search", "").strip().lower()

    if not server_id or not client.is_ready():
        return jsonify([])
    try:
        guild = client.get_guild(int(server_id))
        if not guild:
            return jsonify([])
        
        members_data = []
        for m in guild.members:
            if query and not (query in m.name.lower() or query in str(m.id)):
                continue
            
            joined_str = m.joined_at.strftime("%Y-%m-%d") if m.joined_at else "Unknown"
            roles_list = [{"id": str(r.id), "name": r.name, "color": str(r.color)} for r in m.roles if r.name != "@everyone"]

            members_data.append({
                "id": str(m.id),
                "name": str(m.name),
                "display_name": m.display_name,
                "bot": m.bot,
                "avatar": m.display_avatar.url if m.display_avatar else f"https://ui-avatars.com/api/?name={m.name}",
                "joined_at": joined_str,
                "roles": roles_list
            })
        return jsonify(members_data)
    except Exception as e:
        print(f"Error fetching members: {e}")
        return jsonify([])

@app.route('/api/member/action', methods=['POST'])
def api_member_action():
    data = request.json or {}
    action = data.get("action")
    user_id = data.get("user_id")
    config = load_config()
    server_id = config.get("server_id", "").strip()

    if not client.is_ready() or not server_id:
        return jsonify({"error": "Bot is offline or Server ID not configured"}), 400

    async def _perform():
        guild = client.get_guild(int(server_id))
        if not guild:
            return {"error": "Guild not found"}
        
        member = guild.get_member(int(user_id))
        if not member and action != 'ban':
            return {"error": "Member not found in server"}
        
        if action == 'kick':
            reason = data.get("reason", "Kicked via Owner Dashboard")
            await guild.kick(member, reason=reason)
            log_activity("moderation", f"Kicked Member: {member.name}", f"Reason: {reason}", "Owner")
            return {"message": f"Successfully kicked {member.name}"}

        elif action == 'ban':
            reason = data.get("reason", "Banned via Owner Dashboard")
            user_obj = member or await client.fetch_user(int(user_id))
            await guild.ban(user_obj, reason=reason)
            log_activity("moderation", f"Banned User: {user_obj.name}", f"Reason: {reason}", "Owner")
            return {"message": f"Successfully banned {user_obj.name}"}

        elif action == 'timeout':
            minutes = int(data.get("duration_minutes", 10))
            duration = timedelta(minutes=minutes)
            await member.timeout(duration, reason="Dashboard timeout")
            log_activity("moderation", f"Timeout Member: {member.name}", f"Duration: {minutes} minutes", "Owner")
            return {"message": f"Timed out {member.name} for {minutes}m"}

        elif action == 'add_role':
            role_id = int(data.get("role_id"))
            role = guild.get_role(role_id)
            if role:
                await member.add_roles(role)
                return {"message": f"Added role {role.name} to {member.name}"}
            return {"error": "Role not found"}

        elif action == 'remove_role':
            role_id = int(data.get("role_id"))
            role = guild.get_role(role_id)
            if role:
                await member.remove_roles(role)
                return {"message": f"Removed role {role.name} from {member.name}"}
            return {"error": "Role not found"}

        elif action == 'send_dm':
            message_text = data.get("message", "").strip()
            if not message_text:
                return {"error": "Message body is empty"}
            await member.send(content=message_text)
            log_activity("dm", f"Sent Direct Message to {member.name}", message_text, "Owner")
            return {"message": f"Sent DM to {member.name}"}

        return {"error": "Unknown action"}

    res = run_async(_perform())
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)

# --- LOGS API ---
@app.route('/api/logs')
def api_logs():
    limit = int(request.args.get("limit", 50))
    if mongo_connected and logs_col is not None:
        try:
            logs = list(logs_col.find({}, {"_id": 0}).sort("_id", -1).limit(limit))
            return jsonify(logs)
        except Exception as e:
            print(f"Error loading logs from DB: {e}")
    return jsonify(local_logs_store[:limit])

# --- ANALYTICS API ---
@app.route('/api/analytics')
def api_analytics():
    stats = get_analytics()
    return jsonify({
        "welcome_cards_sent": stats.get("welcome_cards_sent", 0),
        "joins_today": stats.get("joins_today", 0),
        "leaves_today": stats.get("leaves_today", 0),
        "growth_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "growth_data": [12, 19, 15, 25, 32, 40, 48],
        "welcome_data": [10, 18, 14, 22, 30, 38, 45]
    })

# --- BACKUP & RESTORE API ---
@app.route('/api/backup')
def api_backup():
    config = load_config()
    config.pop("_id", None)
    stats = get_analytics()
    backup_data = {
        "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": config,
        "analytics": stats
    }
    return Response(
        json.dumps(backup_data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-disposition": f"attachment; filename=bot_bro_backup_{int(time.time())}.json"}
    )

@app.route('/api/restore', methods=['POST'])
def api_restore():
    if 'backup_file' not in request.files:
        return jsonify({"error": "No backup file uploaded"}), 400
    
    file = request.files['backup_file']
    try:
        content = json.load(file)
        if "config" in content:
            save_config(content["config"])
            log_activity("restore", "Restored Configuration", "Owner restored settings from JSON backup file.", "Owner")
            return jsonify({"message": "Configuration successfully restored!"})
        return jsonify({"error": "Invalid backup file structure"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to parse backup file: {e}"}), 400

# ============ DISCORD BOT EVENTS ============
@client.event
async def on_ready():
    global bot_loop
    bot_loop = asyncio.get_running_loop()
    print("=" * 60)
    print(f"🤖 Bot Online: {client.user} (ID: {client.user.id})")
    print(f"🌐 Connected Guilds: {len(client.guilds)}")
    print("=" * 60)
    log_activity("bot", "Bot Ready & Online", f"Bot {client.user} is connected and operational.", "Bot")

@client.event
async def on_member_join(member):
    config = load_config()
    server_id = config.get("server_id", "").strip()
    
    if str(member.guild.id) == server_id:
        increment_analytic("joins_today")
        log_activity("join", f"Member Joined: {member.name}", f"Joined {member.guild.name}", member.name)

        # Auto Role
        auto_role_id = config.get("auto_role_id", "").strip()
        if auto_role_id and auto_role_id.isdigit():
            role = member.guild.get_role(int(auto_role_id))
            if role:
                try:
                    await member.add_roles(role)
                except Exception as e:
                    print(f"Error giving auto role: {e}")

        # Welcome Card & Channel Message
        ch_id_str = config.get("welcome_channel_id", "").strip()
        if ch_id_str.isdigit():
            channel = member.guild.get_channel(int(ch_id_str))
            if channel:
                try:
                    avatar_url = member.display_avatar.url if member.display_avatar else ""
                    card_buf = await generate_welcome_card(
                        member.name, avatar_url, member.guild.name, member.guild.member_count, config_override=config
                    )
                    
                    raw_text = config.get("welcome_text", "Welcome {mention} to {server}!")
                    msg_content = raw_text.replace("{mention}", member.mention)\
                                          .replace("{username}", member.name)\
                                          .replace("{server}", member.guild.name)\
                                          .replace("{count}", str(member.guild.member_count))\
                                          .replace("{userid}", str(member.id))

                    color_hex = config.get("embed_color", "#3498db").lstrip('#')
                    try:
                        embed_color = int(color_hex, 16)
                    except:
                        embed_color = 0x3498DB

                    embed = discord.Embed(description=msg_content, color=embed_color)
                    embed.set_image(url="attachment://welcome.png")
                    embed.set_footer(text=f"Member #{member.guild.member_count}")
                    
                    await channel.send(file=discord.File(card_buf, filename="welcome.png"), embed=embed)
                    increment_analytic("welcome_cards_sent")
                    log_activity("welcome", f"Welcome Card Sent to {member.name}", f"Channel: #{channel.name}", "Bot")
                except Exception as e:
                    print(f"Error sending welcome card: {e}")
                    log_activity("error", f"Failed to send welcome card: {e}", "", "Bot")

@client.event
async def on_member_remove(member):
    config = load_config()
    server_id = config.get("server_id", "").strip()
    if str(member.guild.id) == server_id:
        increment_analytic("leaves_today")
        log_activity("leave", f"Member Left: {member.name}", f"Left {member.guild.name}", member.name)

@client.event
async def on_message(message):
    if message.author == client.user or not message.guild:
        return
    
    if message.content.strip() in ['!test', '!welcome']:
        config = load_config()
        avatar_url = message.author.display_avatar.url if message.author.display_avatar else ""
        card_buf = await generate_welcome_card(
            message.author.name, avatar_url, message.guild.name, message.guild.member_count, config_override=config
        )
        
        raw_text = config.get("welcome_text", "Welcome {mention} to {server}!")
        msg_content = raw_text.replace("{mention}", message.author.mention)\
                              .replace("{username}", message.author.name)\
                              .replace("{server}", message.guild.name)\
                              .replace("{count}", str(message.guild.member_count))\
                              .replace("{userid}", str(message.author.id))

        color_hex = config.get("embed_color", "#3498db").lstrip('#')
        try:
            embed_color = int(color_hex, 16)
        except:
            embed_color = 0x3498DB

        embed = discord.Embed(description=msg_content, color=embed_color)
        embed.set_image(url="attachment://welcome.png")
        embed.set_footer(text=f"Test Welcome Card • Member #{message.guild.member_count}")
        
        await message.channel.send(file=discord.File(card_buf, filename="welcome.png"), embed=embed)
        log_activity("test", f"Command {message.content.strip()} used by {message.author.name}", f"Channel: #{message.channel.name}", message.author.name)


# ============ BOT & FLASK RUNNER ============
def run_bot_thread():
    """Run the Discord bot in a background daemon thread."""
    config = load_config()
    token = config.get("bot_token", "").strip() or DISCORD_TOKEN
    if token:
        try:
            print("🚀 Starting Discord Bot client...")
            client.run(token)
        except Exception as e:
            print(f"❌ Failed to launch Discord Bot: {e}")
    else:
        print("⚠️ No DISCORD_TOKEN set — bot will not start. Flask API is still running.")

if __name__ == '__main__':
    # Start Discord bot in a DAEMON background thread
    bot_thread = Thread(target=run_bot_thread, daemon=True)
    bot_thread.start()
    print(f"🌐 Web Dashboard running on http://0.0.0.0:{PORT}")

    # Run Flask in the MAIN thread
    import logging as _logging
    _wz_log = _logging.getLogger('werkzeug')
    _wz_log.setLevel(_logging.ERROR)
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
