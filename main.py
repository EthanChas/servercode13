# =========================================
# Enhanced Player Server with Inactivity Check
# =========================================
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
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
    return {"message": "Server running"}
