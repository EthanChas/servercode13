# =========================================
# Enhanced Player Server with Shared Markers/Pings
# =========================================
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import time
import uuid

app = FastAPI()

# Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Player storage
# username -> dict(level=str, coords=dict, frequency=float, last_update=float)
players = {}

# Shared markers storage
# marker_id -> dict(
#     username=str, 
#     frequency=float, 
#     level=str, 
#     coords=dict, 
#     marker_type=str, 
#     timestamp=float,
#     expires_at=float or None
# )
shared_markers = {}

INACTIVITY_TIMEOUT = 5 * 60  # 5 minutes
MARKER_EXPIRY = 30 * 60  # 30 minutes for markers

# Middleware to block browsers
@app.middleware("http")
async def block_browsers(request: Request, call_next):
    user_agent = request.headers.get("user-agent", "").lower()
    
    browser_keywords = ["mozilla", "chrome", "safari", "firefox", "edge", "opera", "brave"]
    is_browser = any(browser in user_agent for browser in browser_keywords)
    is_python = "python" in user_agent or "requests" in user_agent or "urllib" in user_agent
    
    if is_browser and not is_python:
        return JSONResponse(
            status_code=403,
            content={"error": "Browser access forbidden. API access only."}
        )
    
    response = await call_next(request)
    return response

@app.post("/join")
async def join(request: Request):
    """
    Player sends:
    {
        "username": "Ethan",
        "level": "Level1",
        "coords": {"x": 10, "y": 20, "z": 5},
        "frequency": 123.4
    }
    """
    data = await request.json()
    username = data.get("username")
    level = data.get("level")
    coords = data.get("coords")
    frequency = data.get("frequency")
    
    if not all([username, level, coords, frequency is not None]):
        return {"error": "Missing required fields"}
    
    current_time = time.time()
    
    if username in players:
        old = players[username]
        if (old["level"] == level and
            old["coords"] == coords and
            old["frequency"] == frequency):
            players[username]["last_update"] = current_time
            return {"message": "Updated timestamp", "status": "no_change"}
        else:
            players[username] = {
                "level": level,
                "coords": coords,
                "frequency": frequency,
                "last_update": current_time
            }
            return {"message": "Player updated", "status": "updated"}
    else:
        players[username] = {
            "level": level,
            "coords": coords,
            "frequency": frequency,
            "last_update": current_time
        }
        return {"message": "Player joined", "status": "new"}

@app.get("/players")
async def get_players():
    """Return all current players"""
    return {"players": players}

@app.post("/markers/place")
async def place_marker(request: Request):
    """
    Place a shared marker on the map
    {
        "username": "Ethan",
        "frequency": 123.4,
        "level": "Level1",
        "coords": {"x": 10, "y": 20, "z": 5},
        "marker_type": "Monster1",
        "expires_in": 1800  # optional, seconds until expiry (default 30 min)
    }
    """
    data = await request.json()
    username = data.get("username")
    frequency = data.get("frequency")
    level = data.get("level")
    coords = data.get("coords")
    marker_type = data.get("marker_type")
    expires_in = data.get("expires_in", MARKER_EXPIRY)
    
    if not all([username, frequency is not None, level, coords, marker_type]):
        return {"error": "Missing required fields"}
    
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
    """
    Get all markers, optionally filtered by frequency and level
    Query params: ?frequency=123.4&level=Level1
    """
    current_time = time.time()
    
    # Filter markers
    filtered_markers = {}
    for marker_id, marker in shared_markers.items():
        # Check expiry
        if marker["expires_at"] and current_time > marker["expires_at"]:
            continue
        
        # Filter by frequency
        if frequency is not None and marker["frequency"] != frequency:
            continue
        
        # Filter by level
        if level and marker["level"] != level:
            continue
        
        filtered_markers[marker_id] = marker
    
    return {"markers": filtered_markers}

@app.delete("/markers/remove/{marker_id}")
async def remove_marker(marker_id: str, username: str = None):
    """
    Remove a marker by ID
    Optional: username to verify ownership
    """
    if marker_id not in shared_markers:
        return {"error": "Marker not found", "status": "not_found"}
    
    marker = shared_markers[marker_id]
    
    # If username provided, check ownership
    if username and marker["username"] != username:
        return {"error": "Not authorized to remove this marker", "status": "unauthorized"}
    
    del shared_markers[marker_id]
    print(f"[MARKER] Removed marker {marker_id}")
    
    return {"message": "Marker removed", "status": "success"}

@app.delete("/markers/clear")
async def clear_markers(username: str = None, frequency: float = None):
    """
    Clear markers by username or frequency
    Query params: ?username=Ethan or ?frequency=123.4
    """
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

# Background task to remove inactive players and expired markers
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
        
        await asyncio.sleep(60)  # check every 60 seconds

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_inactive())

@app.get("/")
async def root():
    return {
        "message": "Server running", 
        "note": "API access only - browsers blocked",
        "endpoints": {
            "players": "/players",
            "join": "/join",
            "place_marker": "/markers/place",
            "get_markers": "/markers/get",
            "remove_marker": "/markers/remove/{marker_id}",
            "clear_markers": "/markers/clear"
        }
    }
