# =============================
# FastAPI Player Position Server
# =============================
# This server:
# - Accepts POST /join with {"name": "Player", "coords": {...}}
# - Checks if name exists
# - Stores in memory
# - Returns list of players

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allow all origins (so your Python client can connect)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory player storage
players = {}

@app.post("/join")
async def join(request: Request):
    data = await request.json()
    name = data.get("name")
    coords = data.get("coords")

    if not name or not coords:
        return {"error": "Missing name or coords"}

    # If name already exists
    if name in players:
        return {"error": "Name chosen"}

    # Save player
    players[name] = coords

    # Return updated list
    return {"message": "Joined successfully", "players": players}

@app.get("/players")
async def get_players():
    return {"players": players}
