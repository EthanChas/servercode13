# =========================================
# Enhanced Player Server with Inactivity Check
# =========================================
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import time

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
# username -> dict(level=int, coords=dict, frequency=float, last_update=float)
players = {}
INACTIVITY_TIMEOUT = 5 * 60  # 5 minutes

# Middleware to block browsers
@app.middleware("http")
async def block_browsers(request: Request, call_next):
    user_agent = request.headers.get("user-agent", "").lower()
    
    # Block all common browsers
    browser_keywords = ["mozilla", "chrome", "safari", "firefox", "edge", "opera", "brave"]
    
    # Check if it's a browser (and not python-requests)
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
        "level": 1,
        "coords": {"x": 10, "y": 20, "z": 5},
        "frequency": 123.4
    }
    """
    data = await request.json()
    username = data.get("username")
    level = data.get("level")
    coords = data.get("coords")
    frequency = data.get("frequency")
    
    if not all([username, level is not None, coords, frequency is not None]):
        return {"error": "Missing required fields"}
    
    current_time = time.time()
    
    # Check if name is taken and update or create
    if username in players:
        old = players[username]
        # Check if nothing changed
        if (old["level"] == level and
            old["coords"] == coords and
            old["frequency"] == frequency):
            # No changes, just update timestamp
            players[username]["last_update"] = current_time
            return {"message": "Updated timestamp for inactivity", "status": "no_change"}
        else:
            # Update fields
            players[username] = {
                "level": level,
                "coords": coords,
                "frequency": frequency,
                "last_update": current_time
            }
            return {"message": "Player updated", "status": "updated"}
    else:
        # New player
        players[username] = {
            "level": level,
            "coords": coords,
            "frequency": frequency,
            "last_update": current_time
        }
        return {"message": "Player joined", "status": "new"}

@app.get("/players")
async def get_players():
    """
    Return all current players
    """
    return {"players": players}

# Background task to remove inactive players
async def cleanup_inactive_players():
    while True:
        now = time.time()
        to_remove = []
        for username, data in players.items():
            if now - data["last_update"] > INACTIVITY_TIMEOUT:
                to_remove.append(username)
        for username in to_remove:
            del players[username]
            print(f"[CLEANUP] Removed inactive player: {username}")
        await asyncio.sleep(60)  # check every 60 seconds

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_inactive_players())

# Optional root endpoint
@app.get("/")
async def root():
    return {"message": "Server running", "note": "API access only - browsers blocked"}
