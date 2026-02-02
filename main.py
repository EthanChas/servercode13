# =========================================
# Enhanced Player Server with Admin Panel, MAC Banning, and Image Support
# =========================================
from fastapi import FastAPI, Request, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import time
import uuid
import base64
import hashlib
from typing import Optional
import os
from pathlib import Path

app = FastAPI()

# Create uploads directory for images
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin credentials (change these!)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = hashlib.sha256("admin123".encode()).hexdigest()  # Change this password!

# Storage
players = {}  # username -> dict(level, coords, frequency, last_update, mac_address)
shared_markers = {}  # marker_id -> dict(username, frequency, level, coords, marker_type, timestamp, expires_at)
chat_messages = {}  # message_id -> dict(username, frequency, message, timestamp, expires_at, image_url, mac_address)
banned_macs = set()  # Set of banned MAC addresses
admin_sessions = {}  # session_id -> dict(username, created_at, last_active)

INACTIVITY_TIMEOUT = 5 * 60  # 5 minutes
MARKER_EXPIRY = 30 * 60  # 30 minutes
CHAT_EXPIRY = 5 * 60  # 5 minutes
SESSION_EXPIRY = 60 * 60  # 1 hour for admin sessions

def get_mac_address(request: Request) -> str:
    """Extract MAC address from request headers or generate fingerprint"""
    # Try to get MAC from custom header
    mac = request.headers.get("X-MAC-Address")
    if mac:
        return mac
    
    # Generate fingerprint from user agent and IP
    user_agent = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else "unknown"
    fingerprint = hashlib.md5(f"{user_agent}{ip}".encode()).hexdigest()
    return fingerprint

def is_banned(mac_address: str) -> bool:
    """Check if MAC address is banned"""
    return mac_address in banned_macs

def verify_admin_session(session_id: str) -> bool:
    """Verify admin session is valid"""
    if session_id not in admin_sessions:
        return False
    
    session = admin_sessions[session_id]
    if time.time() - session["last_active"] > SESSION_EXPIRY:
        del admin_sessions[session_id]
        return False
    
    session["last_active"] = time.time()
    return True

# Middleware to block browsers (except admin panel)
@app.middleware("http")
async def block_browsers(request: Request, call_next):
    # Allow admin panel access
    if request.url.path.startswith("/admin"):
        response = await call_next(request)
        return response
    
    user_agent = request.headers.get("user-agent", "").lower()
    
    browser_keywords = ["mozilla", "chrome", "safari", "firefox", "edge", "opera", "brave"]
    is_browser = any(browser in user_agent for browser in browser_keywords)
    is_python = "python" in user_agent or "requests" in user_agent or "urllib" in user_agent
    
    if is_browser and not is_python:
        return JSONResponse(
            status_code=403,
            content={"error": "Browser access forbidden. Use /admin for admin panel."}
        )
    
    response = await call_next(request)
    return response

@app.post("/join")
async def join(request: Request):
    """Player joins the server"""
    data = await request.json()
    username = data.get("username")
    level = data.get("level")
    coords = data.get("coords")
    frequency = data.get("frequency")
    
    if not all([username, level, coords, frequency is not None]):
        return {"error": "Missing required fields"}
    
    # Check MAC ban
    mac_address = get_mac_address(request)
    if is_banned(mac_address):
        raise HTTPException(status_code=403, detail="Your device has been banned from this server")
    
    current_time = time.time()
    
    if username in players:
        old = players[username]
        if (old["level"] == level and
            old["coords"] == coords and
            old["frequency"] == frequency):
            players[username]["last_update"] = current_time
            players[username]["mac_address"] = mac_address
            return {"message": "Updated timestamp", "status": "no_change"}
        else:
            players[username] = {
                "level": level,
                "coords": coords,
                "frequency": frequency,
                "last_update": current_time,
                "mac_address": mac_address
            }
            return {"message": "Player updated", "status": "updated"}
    else:
        players[username] = {
            "level": level,
            "coords": coords,
            "frequency": frequency,
            "last_update": current_time,
            "mac_address": mac_address
        }
        return {"message": "Player joined", "status": "new"}

@app.get("/players")
async def get_players():
    """Return all current players (without MAC addresses)"""
    safe_players = {}
    for username, data in players.items():
        safe_players[username] = {
            "level": data["level"],
            "coords": data["coords"],
            "frequency": data["frequency"],
            "last_update": data["last_update"]
        }
    return {"players": safe_players}

@app.post("/markers/place")
async def place_marker(request: Request):
    """Place a shared marker on the map"""
    data = await request.json()
    username = data.get("username")
    frequency = data.get("frequency")
    level = data.get("level")
    coords = data.get("coords")
    marker_type = data.get("marker_type")
    expires_in = data.get("expires_in", MARKER_EXPIRY)
    
    if not all([username, frequency is not None, level, coords, marker_type]):
        return {"error": "Missing required fields"}
    
    # Check MAC ban
    mac_address = get_mac_address(request)
    if is_banned(mac_address):
        raise HTTPException(status_code=403, detail="Your device has been banned")
    
    current_time = time.time()
    marker_id = str(uuid.uuid4())
    
    shared_markers[marker_id] = {
        "username": username,
        "frequency": frequency,
        "level": level,
        "coords": coords,
        "marker_type": marker_type,
        "timestamp": current_time,
        "expires_at": current_time + expires_in if expires_in else None
    }
    
    print(f"[MARKER] {username} placed '{marker_type}' at {coords} on frequency {frequency}")
    
    return {
        "message": "Marker placed",
        "marker_id": marker_id,
        "status": "success"
    }

@app.get("/markers/get")
async def get_markers(frequency: float = None, level: str = None):
    """Get all markers, optionally filtered"""
    current_time = time.time()
    
    filtered_markers = {}
    for marker_id, marker in shared_markers.items():
        if marker["expires_at"] and current_time > marker["expires_at"]:
            continue
        if frequency is not None and marker["frequency"] != frequency:
            continue
        if level and marker["level"] != level:
            continue
        
        filtered_markers[marker_id] = marker
    
    return {"markers": filtered_markers}

@app.delete("/markers/remove/{marker_id}")
async def remove_marker(marker_id: str, username: str = None):
    """Remove a marker by ID"""
    if marker_id not in shared_markers:
        return {"error": "Marker not found", "status": "not_found"}
    
    marker = shared_markers[marker_id]
    
    if username and marker["username"] != username:
        return {"error": "Not authorized", "status": "unauthorized"}
    
    del shared_markers[marker_id]
    print(f"[MARKER] Removed marker {marker_id}")
    
    return {"message": "Marker removed", "status": "success"}

@app.delete("/markers/clear")
async def clear_markers(username: str = None, frequency: float = None):
    """Clear markers by username or frequency"""
    if not username and frequency is None:
        return {"error": "Must provide username or frequency"}
    
    to_remove = []
    for marker_id, marker in shared_markers.items():
        if username and marker["username"] == username:
            to_remove.append(marker_id)
        elif frequency is not None and marker["frequency"] == frequency:
            to_remove.append(marker_id)
    
    for marker_id in to_remove:
        del shared_markers[marker_id]
    
    print(f"[MARKER] Cleared {len(to_remove)} markers")
    
    return {"message": f"Cleared {len(to_remove)} markers", "status": "success"}

# ============= CHAT ENDPOINTS (WITH IMAGE SUPPORT) =============

@app.post("/chat/send")
async def send_chat(request: Request):
    """Send a chat message (text or image)"""
    data = await request.json()
    username = data.get("username")
    frequency = data.get("frequency")
    message = data.get("message", "")
    image_data = data.get("image")  # Base64 encoded image
    
    if not all([username, frequency is not None]):
        return {"error": "Missing required fields"}
    
    # Check MAC ban
    mac_address = get_mac_address(request)
    if is_banned(mac_address):
        raise HTTPException(status_code=403, detail="Your device has been banned")
    
    if not message and not image_data:
        return {"error": "Message or image required"}
    
    if len(message) > 500:
        return {"error": "Message too long (max 500 characters)"}
    
    current_time = time.time()
    message_id = str(uuid.uuid4())
    
    image_url = None
    if image_data:
        # Save image
        try:
            # Remove data URL prefix if present
            if "base64," in image_data:
                image_data = image_data.split("base64,")[1]
            
            # Decode and save
            img_bytes = base64.b64decode(image_data)
            img_filename = f"{message_id}.jpg"
            img_path = UPLOAD_DIR / img_filename
            
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            
            image_url = f"/uploads/{img_filename}"
        except Exception as e:
            print(f"Error saving image: {e}")
            return {"error": "Failed to save image"}
    
    chat_messages[message_id] = {
        "username": username,
        "frequency": frequency,
        "message": message,
        "image_url": image_url,
        "timestamp": current_time,
        "expires_at": current_time + CHAT_EXPIRY,
        "mac_address": mac_address
    }
    
    print(f"[CHAT] {username} (F:{frequency}): {message} {f'[IMG: {image_url}]' if image_url else ''}")
    
    return {
        "message": "Chat message sent",
        "message_id": message_id,
        "status": "success"
    }

@app.get("/chat/get")
async def get_chat(frequency: float = None):
    """Get all chat messages, optionally filtered"""
    current_time = time.time()
    
    filtered_messages = {}
    for message_id, msg in chat_messages.items():
        if current_time > msg["expires_at"]:
            continue
        if frequency is not None and msg["frequency"] != frequency:
            continue
        
        age = current_time - msg["timestamp"]
        fade_start = CHAT_EXPIRY - 60
        
        if age >= fade_start:
            fade_progress = (age - fade_start) / 60
        else:
            fade_progress = 0.0
        
        # Don't include MAC address in response
        filtered_messages[message_id] = {
            "username": msg["username"],
            "frequency": msg["frequency"],
            "message": msg["message"],
            "image_url": msg.get("image_url"),
            "timestamp": msg["timestamp"],
            "expires_at": msg["expires_at"],
            "age": age,
            "fade_progress": fade_progress
        }
    
    return {"messages": filtered_messages}

@app.delete("/chat/clear")
async def clear_chat(frequency: float = None):
    """Clear chat messages by frequency"""
    if frequency is None:
        return {"error": "Must provide frequency"}
    
    to_remove = []
    for message_id, msg in chat_messages.items():
        if msg["frequency"] == frequency:
            to_remove.append(message_id)
    
    for message_id in to_remove:
        del chat_messages[message_id]
    
    print(f"[CHAT] Cleared {len(to_remove)} messages")
    
    return {"message": f"Cleared {len(to_remove)} messages", "status": "success"}

# ============= ADMIN PANEL =============

@app.post("/admin/login")
async def admin_login(request: Request):
    """Admin login"""
    data = await request.json()
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Missing credentials")
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    if username == ADMIN_USERNAME and password_hash == ADMIN_PASSWORD_HASH:
        session_id = str(uuid.uuid4())
        admin_sessions[session_id] = {
            "username": username,
            "created_at": time.time(),
            "last_active": time.time()
        }
        return {"session_id": session_id, "status": "success"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/admin/data")
async def get_admin_data(session_id: str):
    """Get all server data for admin panel"""
    if not verify_admin_session(session_id):
        raise HTTPException(status_code=401, detail="Invalid session")
    
    return {
        "players": players,
        "chat_messages": chat_messages,
        "banned_macs": list(banned_macs),
        "markers": shared_markers,
        "stats": {
            "total_players": len(players),
            "total_messages": len(chat_messages),
            "total_banned": len(banned_macs),
            "total_markers": len(shared_markers)
        }
    }

@app.post("/admin/ban")
async def ban_mac(request: Request, session_id: str):
    """Ban a MAC address"""
    if not verify_admin_session(session_id):
        raise HTTPException(status_code=401, detail="Invalid session")
    
    data = await request.json()
    mac_address = data.get("mac_address")
    
    if not mac_address:
        raise HTTPException(status_code=400, detail="MAC address required")
    
    banned_macs.add(mac_address)
    print(f"[ADMIN] Banned MAC: {mac_address}")
    
    return {"message": "MAC address banned", "status": "success"}

@app.post("/admin/unban")
async def unban_mac(request: Request, session_id: str):
    """Unban a MAC address"""
    if not verify_admin_session(session_id):
        raise HTTPException(status_code=401, detail="Invalid session")
    
    data = await request.json()
    mac_address = data.get("mac_address")
    
    if not mac_address:
        raise HTTPException(status_code=400, detail="MAC address required")
    
    if mac_address in banned_macs:
        banned_macs.remove(mac_address)
        print(f"[ADMIN] Unbanned MAC: {mac_address}")
        return {"message": "MAC address unbanned", "status": "success"}
    
    return {"message": "MAC address not found in ban list", "status": "not_found"}

@app.delete("/admin/message/{message_id}")
async def delete_message(message_id: str, session_id: str):
    """Delete a specific message"""
    if not verify_admin_session(session_id):
        raise HTTPException(status_code=401, detail="Invalid session")
    
    if message_id in chat_messages:
        del chat_messages[message_id]
        return {"message": "Message deleted", "status": "success"}
    
    return {"message": "Message not found", "status": "not_found"}

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    """Admin panel interface"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Server Admin Panel</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .login-container {
            max-width: 400px;
            margin: 100px auto;
            background: #2a2a2a;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        
        h1 {
            color: #fff;
            margin-bottom: 30px;
            font-size: 28px;
        }
        
        h2 {
            color: #fff;
            margin: 30px 0 15px;
            font-size: 22px;
            border-bottom: 2px solid #3a3a3a;
            padding-bottom: 10px;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border: 1px solid #3a3a3a;
        }
        
        .stat-value {
            font-size: 36px;
            font-weight: bold;
            color: #4CAF50;
            margin-bottom: 5px;
        }
        
        .stat-label {
            color: #999;
            font-size: 14px;
            text-transform: uppercase;
        }
        
        input[type="text"],
        input[type="password"] {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            background: #1a1a1a;
            border: 1px solid #3a3a3a;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 14px;
        }
        
        input:focus {
            outline: none;
            border-color: #4CAF50;
        }
        
        button {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }
        
        button:hover {
            background: #45a049;
            transform: translateY(-1px);
        }
        
        button.danger {
            background: #f44336;
        }
        
        button.danger:hover {
            background: #da190b;
        }
        
        button.secondary {
            background: #2196F3;
        }
        
        button.secondary:hover {
            background: #0b7dda;
        }
        
        .section {
            background: #2a2a2a;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 8px;
            border: 1px solid #3a3a3a;
        }
        
        .message-item, .player-item, .ban-item {
            background: #1a1a1a;
            padding: 15px;
            margin: 10px 0;
            border-radius: 6px;
            border-left: 4px solid #4CAF50;
        }
        
        .message-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .username {
            font-weight: bold;
            color: #4CAF50;
        }
        
        .timestamp {
            color: #999;
            font-size: 12px;
        }
        
        .message-text {
            color: #e0e0e0;
            margin: 10px 0;
        }
        
        .mac-address {
            font-family: monospace;
            color: #2196F3;
            font-size: 12px;
        }
        
        .frequency {
            background: #3a3a3a;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            color: #FFD700;
        }
        
        .controls {
            margin-top: 10px;
            display: flex;
            gap: 10px;
        }
        
        .controls button {
            padding: 6px 12px;
            font-size: 12px;
        }
        
        .hidden {
            display: none;
        }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #3a3a3a;
        }
        
        .refresh-btn {
            background: #2196F3;
        }
        
        .logout-btn {
            background: #f44336;
        }
        
        img {
            max-width: 300px;
            max-height: 300px;
            border-radius: 6px;
            margin-top: 10px;
        }
        
        .error {
            color: #f44336;
            margin-top: 10px;
            font-size: 14px;
        }
        
        .success {
            color: #4CAF50;
            margin-top: 10px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Login Screen -->
        <div id="loginScreen" class="login-container">
            <h1>🔐 Admin Login</h1>
            <input type="text" id="adminUsername" placeholder="Username" />
            <input type="password" id="adminPassword" placeholder="Password" />
            <button onclick="login()">Login</button>
            <div id="loginError" class="error hidden"></div>
        </div>
        
        <!-- Admin Panel -->
        <div id="adminPanel" class="hidden">
            <div class="header">
                <h1>🛡️ Server Admin Panel</h1>
                <div>
                    <button class="refresh-btn" onclick="loadData()">🔄 Refresh</button>
                    <button class="logout-btn" onclick="logout()">Logout</button>
                </div>
            </div>
            
            <!-- Stats -->
            <div class="stats" id="stats"></div>
            
            <!-- Chat Messages -->
            <div class="section">
                <h2>💬 Chat Messages</h2>
                <div id="messages"></div>
            </div>
            
            <!-- Players -->
            <div class="section">
                <h2>👥 Active Players</h2>
                <div id="players"></div>
            </div>
            
            <!-- Banned MACs -->
            <div class="section">
                <h2>🚫 Banned MAC Addresses</h2>
                <div id="bannedList"></div>
            </div>
        </div>
    </div>
    
    <script>
        let sessionId = null;
        let refreshInterval = null;
        
        async function login() {
            const username = document.getElementById('adminUsername').value;
            const password = document.getElementById('adminPassword').value;
            const errorDiv = document.getElementById('loginError');
            
            try {
                const response = await fetch('/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                
                if (response.ok) {
                    const data = await response.json();
                    sessionId = data.session_id;
                    
                    document.getElementById('loginScreen').classList.add('hidden');
                    document.getElementById('adminPanel').classList.remove('hidden');
                    
                    await loadData();
                    refreshInterval = setInterval(loadData, 5000);
                } else {
                    errorDiv.textContent = 'Invalid credentials';
                    errorDiv.classList.remove('hidden');
                }
            } catch (error) {
                errorDiv.textContent = 'Connection failed';
                errorDiv.classList.remove('hidden');
            }
        }
        
        function logout() {
            sessionId = null;
            clearInterval(refreshInterval);
            document.getElementById('adminPanel').classList.add('hidden');
            document.getElementById('loginScreen').classList.remove('hidden');
            document.getElementById('adminUsername').value = '';
            document.getElementById('adminPassword').value = '';
        }
        
        async function loadData() {
            if (!sessionId) return;
            
            try {
                const response = await fetch(`/admin/data?session_id=${sessionId}`);
                if (!response.ok) {
                    logout();
                    return;
                }
                
                const data = await response.json();
                
                // Update stats
                document.getElementById('stats').innerHTML = `
                    <div class="stat-card">
                        <div class="stat-value">${data.stats.total_players}</div>
                        <div class="stat-label">Active Players</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.stats.total_messages}</div>
                        <div class="stat-label">Messages</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.stats.total_banned}</div>
                        <div class="stat-label">Banned Users</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.stats.total_markers}</div>
                        <div class="stat-label">Markers</div>
                    </div>
                `;
                
                // Update messages
                let messagesHTML = '';
                const sortedMessages = Object.entries(data.chat_messages).sort((a, b) => b[1].timestamp - a[1].timestamp);
                
                for (const [msgId, msg] of sortedMessages) {
                    const date = new Date(msg.timestamp * 1000).toLocaleString();
                    messagesHTML += `
                        <div class="message-item">
                            <div class="message-header">
                                <div>
                                    <span class="username">${msg.username}</span>
                                    <span class="frequency">F: ${msg.frequency}</span>
                                </div>
                                <span class="timestamp">${date}</span>
                            </div>
                            <div class="message-text">${msg.message || '[Image Only]'}</div>
                            ${msg.image_url ? `<img src="${msg.image_url}" alt="User image" />` : ''}
                            <div class="mac-address">MAC: ${msg.mac_address}</div>
                            <div class="controls">
                                <button class="danger" onclick="deleteMessage('${msgId}')">Delete</button>
                                <button class="danger" onclick="banMac('${msg.mac_address}')">Ban User</button>
                            </div>
                        </div>
                    `;
                }
                document.getElementById('messages').innerHTML = messagesHTML || '<p>No messages</p>';
                
                // Update players
                let playersHTML = '';
                for (const [username, player] of Object.entries(data.players)) {
                    const date = new Date(player.last_update * 1000).toLocaleString();
                    playersHTML += `
                        <div class="player-item">
                            <div class="message-header">
                                <div>
                                    <span class="username">${username}</span>
                                    <span class="frequency">F: ${player.frequency}</span>
                                </div>
                                <span class="timestamp">${date}</span>
                            </div>
                            <div class="mac-address">MAC: ${player.mac_address}</div>
                            <div class="controls">
                                <button class="danger" onclick="banMac('${player.mac_address}')">Ban User</button>
                            </div>
                        </div>
                    `;
                }
                document.getElementById('players').innerHTML = playersHTML || '<p>No players</p>';
                
                // Update banned list
                let bannedHTML = '';
                for (const mac of data.banned_macs) {
                    bannedHTML += `
                        <div class="ban-item">
                            <div class="message-header">
                                <span class="mac-address">${mac}</span>
                                <button class="secondary" onclick="unbanMac('${mac}')">Unban</button>
                            </div>
                        </div>
                    `;
                }
                document.getElementById('bannedList').innerHTML = bannedHTML || '<p>No banned users</p>';
                
            } catch (error) {
                console.error('Error loading data:', error);
            }
        }
        
        async function deleteMessage(messageId) {
            if (!confirm('Delete this message?')) return;
            
            try {
                await fetch(`/admin/message/${messageId}?session_id=${sessionId}`, {
                    method: 'DELETE'
                });
                await loadData();
            } catch (error) {
                alert('Error deleting message');
            }
        }
        
        async function banMac(macAddress) {
            if (!confirm(`Ban MAC address ${macAddress}?`)) return;
            
            try {
                await fetch(`/admin/ban?session_id=${sessionId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mac_address: macAddress})
                });
                await loadData();
            } catch (error) {
                alert('Error banning user');
            }
        }
        
        async function unbanMac(macAddress) {
            if (!confirm(`Unban MAC address ${macAddress}?`)) return;
            
            try {
                await fetch(`/admin/unban?session_id=${sessionId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mac_address: macAddress})
                });
                await loadData();
            } catch (error) {
                alert('Error unbanning user');
            }
        }
        
        // Enter key to login
        document.getElementById('adminPassword').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') login();
        });
    </script>
</body>
</html>
    """

# Mount uploads directory
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Background cleanup task
async def cleanup_inactive():
    while True:
        now = time.time()
        
        # Remove inactive players
        to_remove_players = []
        for username, data in players.items():
            if now - data["last_update"] > INACTIVITY_TIMEOUT:
                to_remove_players.append(username)
        
        for username in to_remove_players:
            del players[username]
            print(f"[CLEANUP] Removed inactive player: {username}")
        
        # Remove expired markers
        to_remove_markers = []
        for marker_id, marker in shared_markers.items():
            if marker["expires_at"] and now > marker["expires_at"]:
                to_remove_markers.append(marker_id)
        
        for marker_id in to_remove_markers:
            del shared_markers[marker_id]
            print(f"[CLEANUP] Removed expired marker: {marker_id}")
        
        # Remove expired chat messages
        to_remove_chat = []
        for message_id, msg in chat_messages.items():
            if now > msg["expires_at"]:
                to_remove_chat.append(message_id)
        
        for message_id in to_remove_chat:
            # Delete image file if exists
            msg = chat_messages[message_id]
            if msg.get("image_url"):
                img_path = UPLOAD_DIR / msg["image_url"].split("/")[-1]
                if img_path.exists():
                    img_path.unlink()
            
            del chat_messages[message_id]
            print(f"[CLEANUP] Removed expired chat: {message_id}")
        
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_inactive())

@app.get("/")
async def root():
    return {
        "message": "Server running", 
        "note": "API access only - use /admin for admin panel",
        "endpoints": {
            "players": "/players",
            "join": "/join",
            "place_marker": "/markers/place",
            "get_markers": "/markers/get",
            "remove_marker": "/markers/remove/{marker_id}",
            "clear_markers": "/markers/clear",
            "send_chat": "/chat/send",
            "get_chat": "/chat/get",
            "clear_chat": "/chat/clear",
            "admin_panel": "/admin"
        }
    }
