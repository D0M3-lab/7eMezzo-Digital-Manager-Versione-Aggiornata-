import random, string
from fastapi import FastAPI, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import Column, Integer, String, Float, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ---------- DATABASE ----------
engine = create_engine("sqlite:///./sette_e_mezzo.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    balance = Column(Float, default=100.0)

Base.metadata.create_all(bind=engine)

# ---------- APP ----------
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------- MAZZO ----------
CARDS = [1,2,3,4,5,6,7,8,9,10] * 4
CARD_VALUES = {1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:0.5,9:0.5,10:0.5}

def score(hand):
    total = 0
    matta = False
    for c in hand:
        if c == 10:
            matta = True
        else:
            total += CARD_VALUES[c]

    if matta:
        needed = 7.5 - total
        if needed > 7:
            needed = 7
        if needed > 0:
            total += needed

    return total

# ---------- TAVOLI ----------
tables = {}

def new_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def new_table(bet):
    deck = CARDS.copy()
    random.shuffle(deck)
    return {
        "deck": deck,
        "dealer": [deck.pop()],
        "bet": bet,
        "players": {},
        "turn": None,
        "phase": "waiting"
    }

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- HOME ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, table: str = "", player: int = 0, db: Session = Depends(get_db)):
    if table in tables and player in tables[table]["players"]:
        t = tables[table]
        p = t["players"][player]

        dealer_cards = t["dealer"] if t["phase"] in ["dealer", "end"] else [t["dealer"][0]]

        return templates.TemplateResponse("index.html", {
            "request": request,
            "view": "game",
            "table": table,
            "player": db.query(Player).get(player),
            "player_hand": p["hand"],
            "dealer_hand": dealer_cards,
            "player_score": score(p["hand"]),
            "game_over": t["phase"] == "end",
            "result_message": p.get("result", ""),
            "bet": t["bet"],
            "turn": t["turn"]
        })

    players = db.query(Player).all()
    leaderboard = db.query(Player).order_by(Player.balance.desc()).limit(5).all()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "view": "menu",
        "players": players,
        "leaderboard": leaderboard
    })

# ---------- CREA PLAYER ----------
@app.post("/add-player")
def add_player(username: str = Form(...), db: Session = Depends(get_db)):
    if not db.query(Player).filter(Player.username == username).first():
        db.add(Player(username=username, balance=100))
        db.commit()
    return RedirectResponse("/", 303)

# ---------- CREA TAVOLO ----------
@app.post("/start-game")
def start_game(player_id: int = Form(...), bet: float = Form(...), db: Session = Depends(get_db)):
    player = db.query(Player).get(player_id)
    if not player or player.balance < bet:
        return RedirectResponse("/", 303)

    player.balance -= bet
    db.commit()

    code = new_code()
    tables[code] = new_table(bet)

    tables[code]["players"][player_id] = {
        "hand": [tables[code]["deck"].pop()],
        "done": False
    }

    tables[code]["turn"] = player_id

    return RedirectResponse(f"/?table={code}&player={player_id}", 303)

# ---------- JOIN ----------
@app.post("/join")
def join(code: str = Form(...), player_id: int = Form(...), db: Session = Depends(get_db)):
    if code not in tables or len(tables[code]["players"]) >= 2:
        return RedirectResponse("/", 303)

    t = tables[code]
    player = db.query(Player).get(player_id)

    if not player or player.balance < t["bet"]:
        return RedirectResponse("/", 303)

    player.balance -= t["bet"]
    db.commit()

    t["players"][player_id] = {
        "hand": [t["deck"].pop()],
        "done": False
    }

    if len(t["players"]) == 2:
        t["phase"] = "players"

    return RedirectResponse(f"/?table={code}&player={player_id}", 303)

# ---------- HIT ----------
@app.post("/hit")
def hit(table: str = Form(...), player: int = Form(...)):
    t = tables[table]
    if t["turn"] != player:
        return RedirectResponse(f"/?table={table}&player={player}", 303)

    t["players"][player]["hand"].append(t["deck"].pop())

    if score(t["players"][player]["hand"]) > 7.5:
        t["players"][player]["done"] = True
        next_turn(t)

    return RedirectResponse(f"/?table={table}&player={player}", 303)

# ---------- STAY ----------
@app.post("/stay")
def stay(table: str = Form(...), player: int = Form(...)):
    t = tables[table]
    if t["turn"] == player:
        t["players"][player]["done"] = True
        next_turn(t)

    return RedirectResponse(f"/?table={table}&player={player}", 303)

# ---------- TURNO E BANCO ----------
def next_turn(t):
    for pid, data in t["players"].items():
        if not data["done"]:
            t["turn"] = pid
            return

    t["phase"] = "dealer"

    while score(t["dealer"]) < 6:
        t["dealer"].append(t["deck"].pop())

    dscore = score(t["dealer"])
    db = SessionLocal()

    for pid, data in t["players"].items():
        pscore = score(data["hand"])
        player = db.query(Player).get(pid)

        if pscore <= 7.5 and (dscore > 7.5 or pscore > dscore):
            data["result"] = "HAI VINTO!"
            player.balance += t["bet"] * 2
        elif pscore == dscore:
            data["result"] = "PAREGGIO"
            player.balance += t["bet"]
        else:
            data["result"] = "HAI PERSO!"

    db.commit()
    db.close()
    t["phase"] = "end"
