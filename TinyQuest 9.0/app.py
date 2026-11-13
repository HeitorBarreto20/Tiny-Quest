"""TinyQuest - site de mini jogos de navegador (Flask + SQLite)."""
import json
import os
import re
import time
import random
import secrets
import sqlite3
import unicodedata
from datetime import datetime, timezone

from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   session, url_for, flash)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TINYQUEST_DB", os.path.join(BASE_DIR, "tinyquest.db"))
SECRET_PATH = os.path.join(BASE_DIR, "secret.key")
MAX_TRIES = 6
WORD_LEN = 5


def _load_secret():
    env = os.environ.get("TINYQUEST_SECRET")
    if env:
        return env
    if not os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "w") as f:
            f.write(secrets.token_hex(32))
    with open(SECRET_PATH) as f:
        return f.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_secret(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


# --------------------------------------------------------------------------
# Palavras
# --------------------------------------------------------------------------
def norm(text):
    """Remove acentos e coloca em maiúsculas (cação -> CACAO)."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").upper()


def load_words():
    words, seen = [], set()
    with open(os.path.join(BASE_DIR, "words.txt"), encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            key = norm(w)
            if len(key) == WORD_LEN and key.isalpha() and key not in seen:
                seen.add(key)
                words.append(w.capitalize())
    return words


WORDS = load_words()

# --------------------------------------------------------------------------
# Quem sou eu? - dados dos famosos
# --------------------------------------------------------------------------
FAMOUS_PATH = os.path.join(BASE_DIR, "data", "quem_sou_eu.md")
MAX_HINTS = 5
SHOW_CATEGORY = True   # mostra "Escritor(a)", "Cantor(a)"... junto das dicas
CATEGORY_LABELS = {
    "ESCRITORES(AS)": "Escritor(a)",
    "ESPORTISTAS": "Esportista",
    "CANTORES(AS)": "Cantor(a)",
    "ATORES E ATRIZES": "Ator ou atriz",
    "DUBLADORES(AS) BRASILEIROS(AS)": "Dublador(a)",
}


def parse_famous():
    out, cat, cur = [], "", None
    with open(FAMOUS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.match(r"^## CATEGORIA \d+ . (.+)$", line)
            if m:
                raw = m.group(1).strip()
                cat = CATEGORY_LABELS.get(raw, raw.title())
                continue
            m = re.match(r"^### (\d+)\. (.+)$", line)
            if m:
                cur = {"id": int(m.group(1)), "name": m.group(2).strip(), "category": cat, "hints": []}
                out.append(cur)
                continue
            m = re.match(r"^(\d)\. (.+)$", line)
            if m and cur is not None:
                cur["hints"].append(m.group(2).strip())
    return [p for p in out if len(p["hints"]) == MAX_HINTS]


def sync_famous(con):
    for p in parse_famous():
        con.execute(
            "INSERT INTO famous (id, name, category) VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, category = excluded.category",
            (p["id"], p["name"], p["category"]))
        con.execute("DELETE FROM hints WHERE famous_id = ?", (p["id"],))
        con.executemany("INSERT INTO hints (famous_id, position, text) VALUES (?,?,?)",
                        [(p["id"], i + 1, t) for i, t in enumerate(p["hints"])])


def answer_key(text):
    """Ignora maiúsculas, acentos, espaços e pontuação (J.K. Rowling == jk rowling)."""
    return "".join(c for c in norm(text) if c.isalnum())


def evaluate(secret, guess):
    """Retorna string de 5 chars: c = lugar certo, p = existe noutro lugar, a = não tem."""
    s, gs = norm(secret), norm(guess)
    result = ["a"] * WORD_LEN
    remaining = {}
    for i in range(WORD_LEN):
        if gs[i] == s[i]:
            result[i] = "c"
        else:
            remaining[s[i]] = remaining.get(s[i], 0) + 1
    for i in range(WORD_LEN):
        if result[i] == "a" and remaining.get(gs[i], 0) > 0:
            result[i] = "p"
            remaining[gs[i]] -= 1
    return "".join(result)


# --------------------------------------------------------------------------
# Banco de dados (SQLite)
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    game        TEXT NOT NULL DEFAULT 'termo',
    secret      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'playing',   -- playing | won | lost
    score       INTEGER NOT NULL DEFAULT 0,
    started_at  REAL,
    elapsed     REAL,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS guesses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id  INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    word     TEXT NOT NULL,
    result   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_user ON games(user_id, game, id);
CREATE INDEX IF NOT EXISTS idx_guesses_game ON guesses(game_id, position);

-- Quem sou eu?: 100 famosos, 5 dicas cada (sincronizado de data/quem_sou_eu.md)
CREATE TABLE IF NOT EXISTS famous (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hints (
    famous_id INTEGER NOT NULL REFERENCES famous(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (famous_id, position)
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(games)")]
    for col, ddl in (("score", "INTEGER NOT NULL DEFAULT 0"), ("started_at", "REAL"), ("elapsed", "REAL")):
        if col not in cols:
            con.execute(f"ALTER TABLE games ADD COLUMN {col} {ddl}")
    # partidas antigas ganhas antes do sistema de pontos
    for gid, kind, n in con.execute(
            "SELECT g.id, g.game, (SELECT COUNT(*) FROM guesses x WHERE x.game_id = g.id) "
            "FROM games g WHERE g.status = 'won' AND g.score = 0").fetchall():
        con.execute("UPDATE games SET score = ? WHERE id = ?", (score_for(kind, "won", n), gid))
    sync_famous(con)
    con.commit()
    con.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Jogos, pontuação e emblemas
# --------------------------------------------------------------------------
KINDS = [
    {"kind": "termo", "name": "Termo", "endpoint": "termo", "size": MAX_TRIES,
     "dist_label": "Vitórias por tentativa"},
    {"kind": "quem", "name": "Quem Sou Eu?", "endpoint": "quem", "size": MAX_HINTS,
     "dist_label": "Vitórias por dica"},
    {"kind": "caca", "name": "Caça-Palavras", "endpoint": "caca", "size": 5, "dist_label": ""},
    {"kind": "robo", "name": "Código Robótico", "endpoint": "robo", "size": 3, "dist_label": ""},
    {"kind": "tetris", "name": "Tetris", "endpoint": "tetris", "size": 5, "dist_label": ""},
    {"kind": "memoria", "name": "Memória Avançada", "endpoint": "memoria", "size": 3, "dist_label": ""},
]


def score_for(kind, status, tries):
    """Pontos de uma partida. tries = nº de chutes (Termo) ou da dica em que acertou (Quem sou eu?)."""
    if status != "won":
        return 0
    if kind == "caca":                   # tries = segundos até completar
        return 100 if tries < 60 else (75 if tries <= 90 else (50 if tries <= 120 else 25))
    if kind == "robo":                   # tries = nº de batidas
        return {0: 100, 1: 75, 2: 50, 3: 25}.get(tries, 0)
    if kind == "memoria":                # tries = nº de erros
        return {0: 100, 1: 75, 2: 50, 3: 25}.get(tries, 0)
    if kind == "tetris":                 # tries = pontos feitos no jogo
        for need, pts in ((50000, 100), (40000, 75), (30000, 50), (20000, 25), (10000, 10)):
            if tries >= need:
                return pts
        return 0
    if kind == "termo":
        return 100 if tries <= 4 else (66 if tries == 5 else 33)
    return max(0, 120 - 20 * tries)      # dica 1 = 100 ... dica 5 = 20


TIERS = [(1, "Começando"), (5, "Iniciante"), (15, "Experiente"), (25, "Veterano"), (50, "Mestre")]


def _svg(inner):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>')


BADGE_ICONS = {
    "termo": _svg('<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2" fill="currentColor"/>'
                  '<rect x="3" y="13" width="8" height="8" rx="2" fill="currentColor"/><rect x="13" y="13" width="8" height="8" rx="2"/>'),
    "quem": _svg('<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1.1.9-1.1 1.7"/>'
                 '<circle cx="12" cy="16.8" r=".7" fill="currentColor"/>'),
    "caca": _svg('<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/><path d="M8 13l2.5-5 2.5 5M8.9 11.4h3.2"/>'),
    "robo": _svg('<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 8V5"/><circle cx="12" cy="4" r="1.2"/>'
                 '<circle cx="9" cy="13" r="1.3" fill="currentColor"/><circle cx="15" cy="13" r="1.3" fill="currentColor"/>'
                 '<path d="M9.5 16.5h5M3 12v4M21 12v4"/>'),
    "tetris": _svg('<rect x="2" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="8.75" y="4" width="6.5" height="6.5" rx="1.6"/>'
                   '<rect x="15.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="8.75" y="11.5" width="6.5" height="6.5" rx="1.6" fill="currentColor"/>'),
    "memoria": _svg('<path d="M9 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 2.8 3 3 0 0 0 1 2.4 3 3 0 0 0 1.5 4.3A3 3 0 0 0 9 19.5a2.5 2.5 0 0 0 3-2.4V6.9A2.5 2.5 0 0 0 9 4.5z"/>'
                    '<path d="M15 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 2.8 3 3 0 0 1-1 2.4 3 3 0 0 1-1.5 4.3A3 3 0 0 1 15 19.5a2.5 2.5 0 0 1-3-2.4V6.9A2.5 2.5 0 0 1 15 4.5z"/>'
                    '<path d="M9.5 8.8C8 8.8 7 9.7 7 11.2M9.5 15.3C8 15.3 7 14.4 6.9 13.2M14.5 8.8C16 8.8 17 9.7 17 11.2M14.5 15.3C16 15.3 17 14.4 17.1 13.2"/>'),
    "geral": _svg('<path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3"/>'
                  '<path d="M12 14v4M9 18h6M8 21h8"/>'),
}


def _build_badges():
    out = []
    for k in KINDS:
        for tier, (n, title) in enumerate(TIERS, 1):
            name = f"{title} no {k['name']}" if n == 1 else f"{title} do {k['name']}"
            out.append({"id": f"{k['kind']}-{n}", "name": name, "game": k["kind"], "need": n, "tier": tier,
                        "desc": f"Vença o {k['name']} {n} {'vez' if n == 1 else 'vezes'}.",
                        "icon": BADGE_ICONS[k["kind"]]})
    for tier, (n, name) in zip((3, 4, 5), [(1, "Colecionador de Mini-Games"),
                                           (10, "Rei dos Mini-Games"), (30, "Deus dos Mini-Games")]):
        out.append({"id": f"geral-{n}", "name": name, "game": None, "need": n, "tier": tier,
                    "desc": f"Vença todos os mini-games {n} {'vez' if n == 1 else 'vezes'}.",
                    "icon": BADGE_ICONS["geral"]})
    return out


BADGES = _build_badges()


def win_counts(uid):
    wins = {k["kind"]: 0 for k in KINDS}
    for game, n in get_db().execute(
            "SELECT game, COUNT(*) FROM games WHERE user_id = ? AND status = 'won' GROUP BY game", (uid,)):
        if game in wins:
            wins[game] = n
    return wins


def badge_progress(badge, wins):
    return wins[badge["game"]] if badge["game"] else min(wins.values())


def finish_game(db, game, kind, status, tries):
    """Fecha a partida, grava a pontuação e devolve (pontos, emblemas novos)."""
    elapsed = time.time() - game["started_at"] if game["started_at"] else None
    score = score_for(kind, status, elapsed if kind == "caca" and elapsed is not None else tries)
    db.execute("UPDATE games SET status = ?, finished_at = ?, score = ?, elapsed = ? WHERE id = ?",
               (status, now(), score, elapsed, game["id"]))
    db.commit()
    new = []
    if game["user_id"] and status == "won":
        after = win_counts(game["user_id"])
        before = dict(after)
        before[kind] -= 1
        new = [{"name": b["name"], "desc": b["desc"], "tier": b["tier"], "game": b["game"], "icon": b["icon"]}
               for b in BADGES
               if badge_progress(b, after) >= b["need"] and badge_progress(b, before) < b["need"]]
    return score, new


# --------------------------------------------------------------------------
# Usuário atual
# --------------------------------------------------------------------------
@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT id, username, email, created_at FROM users WHERE id = ?",
                                  (uid,)).fetchone()
        if g.user is None:
            session.clear()


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------
GAMES = [
    {"endpoint": "termo", "name": "Termo", "tag": "Palavras", "icon": "grid",
     "desc": "Descubra a palavra de 5 letras em 6 tentativas."},
    {"endpoint": "quem", "name": "Quem sou eu?", "tag": "Dedução", "icon": "person",
     "desc": "Adivinhe o famoso com até 5 dicas. A cada erro, uma nova pista."},
    {"endpoint": "caca", "name": "Caça-Palavras", "tag": "Palavras", "icon": "search",
     "desc": "Ache 5 palavras escondidas no tabuleiro antes que o tempo acabe."},
    {"endpoint": "robo", "name": "Código Robótico", "tag": "Lógica", "icon": "robot",
     "desc": "Programe o robô com comandos e guie-o até a bandeira sem bater."},
    {"endpoint": "tetris", "name": "Tetris", "tag": "Puzzle", "icon": "blocks",
     "desc": "Encaixe as peças, complete linhas e colunas e some pontos em 5 minutos."},
    {"endpoint": "memoria", "name": "Memória Avançada", "tag": "Memória", "icon": "brain",
     "desc": "Memorize os emojis e suas posições e depois recoloque cada um no lugar."},
]


@app.route("/")
def index():
    return render_template("index.html", games=GAMES)


@app.route("/quem-sou-eu")
def quem():
    abandon_current("quem")
    return render_template("quem.html", max_hints=MAX_HINTS)


@app.route("/tetris")
def tetris():
    abandon_current("tetris")
    return render_template("tetris.html", limit=TETRIS_TIME, line_points=TETRIS_LINE_POINTS)


@app.route("/memoria-avancada")
def memoria():
    abandon_current("memoria")
    return render_template("memoria.html", look_time=MEM_LOOK, max_errors=MEM_MAX_ERRORS)


@app.route("/codigo-robotico")
def robo():
    abandon_current("robo")
    return render_template("robo.html", max_crashes=ROBO_MAX_CRASHES)


@app.route("/caca-palavras")
def caca():
    abandon_current("caca")
    return render_template("caca.html", size=CACA_SIZE, count=CACA_WORDS_PER_GAME, limit=CACA_TIME)


@app.route("/termo")
def termo():
    abandon_current("termo")
    return render_template("termo.html", max_tries=MAX_TRIES, word_len=WORD_LEN)


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route("/cadastro", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = None
        if not USERNAME_RE.match(username):
            error = "Usuário: 3 a 20 caracteres (letras, números e _)."
        elif not EMAIL_RE.match(email):
            error = "E-mail inválido."
        elif len(password) < 6:
            error = "A senha precisa ter pelo menos 6 caracteres."
        elif password != confirm:
            error = "As senhas não coincidem."
        if error is None:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (username, email, password_hash, created_at) VALUES (?,?,?,?)",
                    (username, email, generate_password_hash(password), now()))
                db.commit()
            except sqlite3.IntegrityError:
                error = "Esse usuário ou e-mail já está em uso."
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                flash("Conta criada! Bem-vindo ao TinyQuest.", "ok")
                return redirect(url_for("index"))
        flash(error, "erro")
        return render_template("register.html", username=username, email=email), 400
    return render_template("register.html")


@app.route("/entrar", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        ident = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ? OR email = ?", (ident, ident)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("Usuário ou senha incorretos.", "erro")
        return render_template("login.html", identifier=ident), 401
    return render_template("login.html")


@app.route("/sair", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/perfil")
def profile():
    if not g.user:
        return redirect(url_for("login"))
    return render_profile(g.user, True)


@app.route("/jogador/<username>")
def player(username):
    user = get_db().execute(
        "SELECT id, username, email, created_at FROM users WHERE username = ?", (username,)).fetchone()
    if user is None:
        abort(404)
    return render_profile(user, bool(g.user and g.user["id"] == user["id"]))


@app.route("/ranking")
def ranking_page():
    kind = request.args.get("jogo", "termo")
    cur = next((k for k in KINDS if k["kind"] == kind), KINDS[0])
    by_pts, by_wins = ranking(cur["kind"])
    me = g.user["id"] if g.user else None
    top = 50
    return render_template(
        "ranking.html", kinds=KINDS, cur=cur, me=me, top=top,
        by_pts=by_pts[:top], by_wins=by_wins[:top],
        my_pts=next((r for r in by_pts if r["id"] == me), None),
        my_wins=next((r for r in by_wins if r["id"] == me), None))


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


def with_pos(rows, key):
    """Posição no ranking (empates dividem a mesma posição)."""
    pos, prev = 0, None
    for i, r in enumerate(rows, 1):
        if r[key] != prev:
            pos, prev = i, r[key]
        r["pos"] = pos
    return rows


def ranking(kind):
    """Rankings globais (só quem tem conta): total de pontos e total de vitórias."""
    rows = [dict(r) for r in get_db().execute(
        """SELECT u.id, u.username, COALESCE(SUM(g.score), 0) AS pts,
                  SUM(CASE WHEN g.status = 'won' THEN 1 ELSE 0 END) AS wins, COUNT(*) AS played
           FROM games g JOIN users u ON u.id = g.user_id
           WHERE g.game = ? AND g.status IN ('won', 'lost') GROUP BY u.id""", (kind,))]
    by_pts = sorted((dict(r) for r in rows if r["pts"] > 0),
                    key=lambda r: (-r["pts"], -r["wins"], r["username"].lower()))
    by_wins = sorted((dict(r) for r in rows if r["wins"] > 0),
                     key=lambda r: (-r["wins"], -r["pts"], r["username"].lower()))
    return with_pos(by_pts, "pts"), with_pos(by_wins, "wins")


def build_stats(uid, kind):
    row = get_db().execute(
        """SELECT COUNT(*) AS played,
                  COALESCE(SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END), 0) AS wins,
                  COALESCE(SUM(score), 0) AS points,
                  COALESCE(MAX(score), 0) AS best_score
           FROM games WHERE user_id = ? AND game = ? AND status IN ('won', 'lost')""", (uid, kind)).fetchone()
    return dict(row)


def render_profile(user, is_me):
    uid = user["id"]
    wins = win_counts(uid)
    games = [{**k, "stats": build_stats(uid, k["kind"])} for k in KINDS]
    badges = []
    for b in BADGES:
        cur = min(badge_progress(b, wins), b["need"])
        badges.append({**b, "current": cur, "earned": cur >= b["need"],
                       "pct": round(100 * cur / b["need"])})
    groups = []
    for key, name in [(k["kind"], k["name"]) for k in KINDS] + [("geral", "Gerais")]:
        items = [b for b in badges if (b["game"] or "geral") == key]
        groups.append({"key": key, "name": name, "badges": items,
                       "earned": sum(1 for b in items if b["earned"]), "total": len(items)})
    since = ""
    if user["created_at"]:
        y, m, d = user["created_at"][:10].split("-")
        since = f"{d}/{m}/{y}"
    return render_template("profile.html", p=user, is_me=is_me, games=games, groups=groups,
                           earned=sum(1 for b in badges if b["earned"]), total=len(badges), since=since)


# --------------------------------------------------------------------------
# API do Termo (a palavra secreta nunca vai ao navegador até o fim da partida)
# --------------------------------------------------------------------------
def new_secret(kind):
    if kind == "memoria":
        return new_memoria_secret()
    if kind == "tetris":
        return new_tetris_secret()
    if kind == "robo":
        return new_robo_secret()
    if kind == "caca":
        return json.dumps(make_caca())
    if kind == "termo":
        return random.choice(WORDS)
    # Quem sou eu?: sorteia um famoso que a pessoa ainda não jogou (até acabarem)
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM famous")]
    if g.user:
        seen = {int(r[0]) for r in db.execute(
            "SELECT secret FROM games WHERE user_id = ? AND game = 'quem'", (g.user["id"],))}
    else:
        seen = set(session.get("quem_seen", []))
    fresh = [i for i in ids if i not in seen]
    if not fresh:
        fresh, seen = ids, set()
    pick = random.choice(fresh)
    if not g.user:
        session["quem_seen"] = sorted(seen | {pick})
    return str(pick)


def current_game(kind="termo", create=False):
    db = get_db()
    uid = g.user["id"] if g.user else None
    key = kind + "_game"
    gid = session.get(key)
    game = None
    if gid:
        game = db.execute("SELECT * FROM games WHERE id = ? AND game = ?", (gid, kind)).fetchone()
        if game is not None and game["user_id"] != uid:
            game = None
    if game is None and create:
        cur = db.execute("INSERT INTO games (user_id, game, secret, created_at, started_at) VALUES (?,?,?,?,?)",
                         (uid, kind, new_secret(kind), now(), time.time()))
        db.commit()
        session[key] = cur.lastrowid
        game = db.execute("SELECT * FROM games WHERE id = ?", (cur.lastrowid,)).fetchone()
    return game


def game_payload(game):
    rows = get_db().execute(
        "SELECT word, result FROM guesses WHERE game_id = ? ORDER BY position", (game["id"],)
    ).fetchall()
    data = {
        "status": game["status"],
        "guesses": [{"word": r["word"], "result": r["result"]} for r in rows],
        "max_tries": MAX_TRIES,
    }
    if game["status"] != "playing":
        data["answer"] = game["secret"]
        data["score"] = game["score"]
    return data


@app.route("/api/termo/state")
def api_state():
    return jsonify(game_payload(current_game(create=True)))


@app.route("/api/termo/new", methods=["POST"])
def api_new():
    game = current_game()
    if game is not None and game["status"] == "playing":
        return jsonify(game_payload(game))
    session.pop("termo_game", None)
    return jsonify(game_payload(current_game(create=True)))


@app.route("/api/termo/guess", methods=["POST"])
def api_guess():
    game = current_game()
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    word = norm((request.get_json(silent=True) or {}).get("word", ""))
    if len(word) != WORD_LEN or not word.isalpha() or not word.isascii():
        return jsonify(error="Digite uma palavra de 5 letras."), 400
    db = get_db()
    tries = db.execute("SELECT COUNT(*) FROM guesses WHERE game_id = ?", (game["id"],)).fetchone()[0]
    result = evaluate(game["secret"], word)
    db.execute("INSERT INTO guesses (game_id, position, word, result) VALUES (?,?,?,?)",
               (game["id"], tries, word, result))
    tries += 1
    status = "playing"
    if result == "c" * WORD_LEN:
        status = "won"
    elif tries >= MAX_TRIES:
        status = "lost"
    out = {"result": result, "status": status}
    if status != "playing":
        out["score"], out["new_badges"] = finish_game(db, game, "termo", status, tries)
        out["answer"] = game["secret"]
    else:
        db.commit()
    return jsonify(out)


# --------------------------------------------------------------------------
# API do Quem sou eu?
# --------------------------------------------------------------------------
def quem_payload(game):
    db = get_db()
    fam = db.execute("SELECT * FROM famous WHERE id = ?", (int(game["secret"]),)).fetchone()
    guesses = db.execute("SELECT word, result FROM guesses WHERE game_id = ? ORDER BY position",
                         (game["id"],)).fetchall()
    n = len(guesses)
    shown = min(n + 1, MAX_HINTS) if game["status"] == "playing" else min(max(n, 1), MAX_HINTS)
    texts = [r["text"] for r in db.execute(
        "SELECT text FROM hints WHERE famous_id = ? AND position <= ? ORDER BY position",
        (fam["id"], shown))]
    data = {
        "status": game["status"],
        "hints": texts,
        "wrong": [r["word"] for r in guesses if r["result"] == "w"],
        "total": MAX_HINTS,
    }
    if SHOW_CATEGORY:
        data["category"] = fam["category"]
    if game["status"] != "playing":
        data["answer"] = fam["name"]
        data["score"] = game["score"]
    return data


@app.route("/api/quem/state")
def api_quem_state():
    return jsonify(quem_payload(current_game("quem", create=True)))


@app.route("/api/quem/new", methods=["POST"])
def api_quem_new():
    game = current_game("quem")
    if game is not None and game["status"] == "playing":
        return jsonify(quem_payload(game))
    session.pop("quem_game", None)
    return jsonify(quem_payload(current_game("quem", create=True)))


@app.route("/api/quem/guess", methods=["POST"])
def api_quem_guess():
    game = current_game("quem")
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    raw = str((request.get_json(silent=True) or {}).get("guess", "")).strip()[:80]
    key = answer_key(raw)
    if not key:
        return jsonify(error="Digite um nome."), 400
    db = get_db()
    fam = db.execute("SELECT name FROM famous WHERE id = ?", (int(game["secret"]),)).fetchone()
    n = db.execute("SELECT COUNT(*) FROM guesses WHERE game_id = ?", (game["id"],)).fetchone()[0]
    correct = key == answer_key(fam["name"])
    db.execute("INSERT INTO guesses (game_id, position, word, result) VALUES (?,?,?,?)",
               (game["id"], n, raw, "c" if correct else "w"))
    n += 1
    status = "won" if correct else ("lost" if n >= MAX_HINTS else "playing")
    new = []
    if status != "playing":
        _score, new = finish_game(db, game, "quem", status, n)
    else:
        db.commit()
    data = quem_payload(db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone())
    data["correct"] = correct
    data["new_badges"] = new
    return jsonify(data)


# --------------------------------------------------------------------------
# Caça-Palavras (tabuleiro 8x8, 5 palavras, 2 minutos)
# --------------------------------------------------------------------------
CACA_SIZE = 8
CACA_WORDS_PER_GAME = 5
CACA_TIME = 180                      # segundos
CACA_DIRS = [(0, 1), (1, 0), (1, 1)]  # horizontal, vertical, diagonal (nunca de trás pra frente)
CACA_FILL = "AAAAAEEEEIIIOOOUURRSSTTNNMMLLDDCCPPBBGFVHQJZXKWY"
CACA_PATH = os.path.join(BASE_DIR, "data", "caca_palavras.txt")


def load_caca_words():
    out = []
    with open(CACA_PATH, encoding="utf-8") as f:
        for line in f:
            w = norm(line.strip())
            if w.isalpha() and 4 <= len(w) <= CACA_SIZE and w not in out:
                out.append(w)
    return out


CACA_WORDS = load_caca_words()


def _caca_place(grid, word):
    n = CACA_SIZE
    spots = {}
    for dr, dc in CACA_DIRS:
        for r in range(n):
            for c in range(n):
                if r + dr * (len(word) - 1) >= n or c + dc * (len(word) - 1) >= n:
                    continue
                if all(grid[(r + dr * i) * n + c + dc * i] in (None, word[i]) for i in range(len(word))):
                    spots.setdefault((dr, dc), []).append((r, c))
    if not spots:
        return False
    (dr, dc) = random.choice(list(spots))
    r, c = random.choice(spots[(dr, dc)])
    for i, ch in enumerate(word):
        grid[(r + dr * i) * n + c + dc * i] = ch
    return True


def make_caca():
    for _ in range(300):
        words = random.sample(CACA_WORDS, CACA_WORDS_PER_GAME)
        if any(a != b and a in b for a in words for b in words):
            continue
        grid = [None] * (CACA_SIZE * CACA_SIZE)
        if all(_caca_place(grid, w) for w in sorted(words, key=len, reverse=True)):
            grid = [ch or random.choice(CACA_FILL) for ch in grid]
            return {"grid": "".join(grid), "words": words}
    raise RuntimeError("Não foi possível gerar o caça-palavras")


def caca_expire(game):
    """Se o tempo acabou, encerra a partida como derrota."""
    if game["status"] == "playing" and time.time() - (game["started_at"] or 0) >= CACA_TIME:
        db = get_db()
        finish_game(db, game, "caca", "lost", 0)
        game = db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone()
    return game


def caca_payload(game):
    db = get_db()
    data = json.loads(game["secret"])
    rows = db.execute("SELECT word, result FROM guesses WHERE game_id = ? ORDER BY position",
                      (game["id"],)).fetchall()
    found = [{"word": r["word"], "cells": [int(x) for x in r["result"].split(",")]} for r in rows]
    out = {"status": game["status"], "grid": data["grid"], "words": data["words"],
           "found": found, "limit": CACA_TIME}
    if game["status"] == "playing":
        out["remaining"] = round(max(0.0, CACA_TIME - (time.time() - game["started_at"])), 2)
    else:
        out["elapsed"] = round(game["elapsed"] or 0, 1)
        out["score"] = game["score"]
        done = {f["word"] for f in found}
        out["missing"] = [w for w in data["words"] if w not in done]
    return out


@app.route("/api/caca/state")
def api_caca_state():
    game = caca_expire(current_game("caca", create=True))
    return jsonify(caca_payload(game))


@app.route("/api/caca/new", methods=["POST"])
def api_caca_new():
    game = current_game("caca")
    if game is not None:
        game = caca_expire(game)
        if game["status"] == "playing":
            return jsonify(caca_payload(game))
    session.pop("caca_game", None)
    return jsonify(caca_payload(current_game("caca", create=True)))


@app.route("/api/caca/check", methods=["POST"])
def api_caca_check():
    game = current_game("caca")
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    game = caca_expire(game)
    if game["status"] != "playing":                      # tempo esgotado
        data = caca_payload(game)
        data.update(ok=False, reason="tempo", new_badges=[])
        return jsonify(data)

    cells = (request.get_json(silent=True) or {}).get("cells")
    total = CACA_SIZE * CACA_SIZE
    if (not isinstance(cells, list) or not 2 <= len(cells) <= CACA_SIZE
            or not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < total for i in cells)
            or len(set(cells)) != len(cells)):
        return jsonify(error="Seleção inválida."), 400

    db = get_db()
    data = json.loads(game["secret"])
    cells = sorted(cells)
    pts = [(i // CACA_SIZE, i % CACA_SIZE) for i in cells]
    step = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    straight = step in CACA_DIRS and all(
        (b[0] - a[0], b[1] - a[1]) == step for a, b in zip(pts, pts[1:]))
    letters = "".join(data["grid"][i] for i in cells)
    found = [r["word"] for r in db.execute("SELECT word FROM guesses WHERE game_id = ?", (game["id"],))]

    reason = None
    if not straight or letters not in data["words"]:
        reason = "errada"
    elif letters in found:
        reason = "repetida"
    if reason:
        out = caca_payload(game)
        out.update(ok=False, reason=reason, new_badges=[])
        return jsonify(out)

    db.execute("INSERT INTO guesses (game_id, position, word, result) VALUES (?,?,?,?)",
               (game["id"], len(found), letters, ",".join(str(i) for i in cells)))
    new = []
    if len(found) + 1 == len(data["words"]):
        _score, new = finish_game(db, game, "caca", "won", 0)
    else:
        db.commit()
    out = caca_payload(db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone())
    out.update(ok=True, word=letters, cells=cells, new_badges=new)
    return jsonify(out)


# --------------------------------------------------------------------------
# Código Robótico (3 fases: fácil 4x4, médio 5x5, difícil 6x6)
# --------------------------------------------------------------------------
ROBO_PATH = os.path.join(BASE_DIR, "data", "robo_maps.json")
ROBO_LEVELS = [("easy", "Fácil"), ("medium", "Médio"), ("hard", "Difícil")]
ROBO_MAX_CRASHES = 4
ROBO_MAX_CMDS = 60
ROBO_DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]   # cima, direita, baixo, esquerda


def load_robo_maps():
    with open(ROBO_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    maps = {}
    for level, _ in ROBO_LEVELS:
        maps[level] = []
        for m in raw[level]:
            start = flag = None
            for r, row in enumerate(m["grid"]):
                for c, ch in enumerate(row):
                    if ch == "R":
                        start = (r, c)
                    elif ch == "F":
                        flag = (r, c)
            maps[level].append({"id": m["id"], "grid": [row.replace("R", ".") for row in m["grid"]],
                                "start": start, "flag": flag})
    return maps


ROBO_MAPS = load_robo_maps()
ROBO_BY_ID = {m["id"]: m for lvl in ROBO_MAPS.values() for m in lvl}


def new_robo_secret():
    """Sorteia um mapa por fase, diferente dos usados na partida anterior, e a direção inicial."""
    prev = None
    if g.user:
        row = get_db().execute("SELECT secret FROM games WHERE user_id = ? AND game = 'robo' "
                               "ORDER BY id DESC LIMIT 1", (g.user["id"],)).fetchone()
        prev = json.loads(row[0]) if row else None
    else:
        prev = session.get("robo_last")
    maps = []
    for i, (level, _) in enumerate(ROBO_LEVELS):
        options = [m["id"] for m in ROBO_MAPS[level]]
        if prev and i < len(prev.get("maps", [])):
            options = [x for x in options if x != prev["maps"][i]] or options
        maps.append(random.choice(options))
    secret = {"maps": maps, "dirs": [random.randrange(4) for _ in ROBO_LEVELS]}
    if not g.user:
        session["robo_last"] = secret
    return json.dumps(secret)


def robo_simulate(m, d, program):
    """Executa o programa (E = esquerda, D = direita, A = andar) a partir do início do mapa."""
    rows, cols = len(m["grid"]), len(m["grid"][0])
    r, c = m["start"]
    steps = []
    for i, cmd in enumerate(program):
        if cmd == "E":
            d = (d + 3) % 4
        elif cmd == "D":
            d = (d + 1) % 4
        else:
            nr, nc = r + ROBO_DIRS[d][0], c + ROBO_DIRS[d][1]
            if not (0 <= nr < rows and 0 <= nc < cols) or m["grid"][nr][nc] == "W":
                return {"outcome": "crash", "steps": steps, "crash_at": i, "dir": d}
            r, c = nr, nc
        steps.append({"r": r, "c": c, "d": d, "cmd": cmd})
        if (r, c) == m["flag"]:
            return {"outcome": "goal", "steps": steps}
    return {"outcome": "end", "steps": steps}


def robo_progress(game):
    rows = get_db().execute("SELECT result FROM guesses WHERE game_id = ? ORDER BY position",
                            (game["id"],)).fetchall()
    return (sum(1 for r in rows if r["result"] == "goal"),
            sum(1 for r in rows if r["result"] == "crash"), len(rows))


def robo_payload(game):
    data = json.loads(game["secret"])
    phase, crashes, _ = robo_progress(game)
    out = {"status": game["status"], "phase": phase, "phases": len(ROBO_LEVELS),
           "crashes": crashes, "max_crashes": ROBO_MAX_CRASHES}
    if game["status"] == "playing":
        m = ROBO_BY_ID[data["maps"][phase]]
        out.update(level=ROBO_LEVELS[phase][1], grid=m["grid"], size=len(m["grid"]),
                   start={"r": m["start"][0], "c": m["start"][1]},
                   flag={"r": m["flag"][0], "c": m["flag"][1]}, dir=data["dirs"][phase])
    else:
        out["score"] = game["score"]
    return out


@app.route("/api/robo/state")
def api_robo_state():
    return jsonify(robo_payload(current_game("robo", create=True)))


@app.route("/api/robo/new", methods=["POST"])
def api_robo_new():
    game = current_game("robo")
    if game is not None and game["status"] == "playing":
        return jsonify(robo_payload(game))
    session.pop("robo_game", None)
    return jsonify(robo_payload(current_game("robo", create=True)))


@app.route("/api/robo/run", methods=["POST"])
def api_robo_run():
    game = current_game("robo")
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    program = (request.get_json(silent=True) or {}).get("program")
    if (not isinstance(program, str) or not 1 <= len(program) <= ROBO_MAX_CMDS
            or any(ch not in "EDA" for ch in program)):
        return jsonify(error="Programa inválido."), 400

    db = get_db()
    data = json.loads(game["secret"])
    phase, crashes, count = robo_progress(game)
    sim = robo_simulate(ROBO_BY_ID[data["maps"][phase]], data["dirs"][phase], program)
    db.execute("INSERT INTO guesses (game_id, position, word, result) VALUES (?,?,?,?)",
               (game["id"], count, program, sim["outcome"]))
    if sim["outcome"] == "goal":
        phase += 1
    elif sim["outcome"] == "crash":
        crashes += 1
    status = "lost" if crashes >= ROBO_MAX_CRASHES else ("won" if phase >= len(ROBO_LEVELS) else "playing")
    new = []
    if status != "playing":
        _score, new = finish_game(db, game, "robo", status, crashes)
    else:
        db.commit()
    out = robo_payload(db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone())
    out.update(outcome=sim["outcome"], steps=sim["steps"], new_badges=new)
    if sim["outcome"] == "crash":
        out["crash_dir"] = sim["dir"]
    return jsonify(out)


def abandon_current(kind):
    """Ao entrar de novo num jogo, a partida em andamento é descartada (começa uma nova)."""
    gid = session.pop(kind + "_game", None)
    if gid:
        db = get_db()
        uid = g.user["id"] if g.user else None
        db.execute("UPDATE games SET status = 'abandoned', finished_at = ? "
                   "WHERE id = ? AND game = ? AND status = 'playing' AND user_id IS ?",
                   (now(), gid, kind, uid))
        db.commit()


# --------------------------------------------------------------------------
# Tetris (estilo Block Bash): tabuleiro 8x8, 3 peças por vez, sem girar, 5 minutos
# --------------------------------------------------------------------------
TETRIS_N = 8
TETRIS_TIME = 300                    # segundos
TETRIS_LINE_POINTS = 1500            # por linha ou coluna completada
TETRIS_WIN_MIN = 10000               # abaixo disso: 0 pontos de ranking (derrota)
TETRIS_SHAPES = [                    # as 19 peças dos esboços
    ["#"],
    ["##", "#."],
    [".#", "##"],
    ["##", "##"],
    ["###", "###", "###"],
    ["###", "..#"],
    ["##", ".#"],
    ["#.", "##"],
    ["###", "#..", "#.."],
    ["###", "..#", "..#"],
    ["#..", "###"],
    ["###", ".#."],
    [".#.", "###"],
    ["#..", "#..", "###"],
    ["..#", "..#", "###"],
    [".#", ".#", "##"],
    ["##", "#.", "#."],
    [".#.", "##.", ".#."],
    ["#.", "##", "#."],
]
TETRIS_PIECES = [
    {"id": i,
     "cells": [(r, c) for r, row in enumerate(shape) for c, ch in enumerate(row) if ch == "#"],
     "h": len(shape), "w": len(shape[0]), "color": i % 6 + 1}
    for i, shape in enumerate(TETRIS_SHAPES)
]


def tetris_fits(board, piece, r, c):
    n = TETRIS_N
    return all(0 <= r + dr < n and 0 <= c + dc < n and board[(r + dr) * n + c + dc] == "."
               for dr, dc in piece["cells"])


def tetris_has_move(board, tray):
    for pid in tray:
        if pid is None:
            continue
        p = TETRIS_PIECES[pid]
        if any(tetris_fits(board, p, r, c)
               for r in range(TETRIS_N - p["h"] + 1) for c in range(TETRIS_N - p["w"] + 1)):
            return True
    return False


def new_tetris_secret():
    return json.dumps({"board": "." * (TETRIS_N * TETRIS_N), "points": 0, "lines": 0,
                       "tray": [random.randrange(len(TETRIS_PIECES)) for _ in range(3)]})


def tetris_finish(db, game, st, reason):
    st["reason"] = reason
    db.execute("UPDATE games SET secret = ? WHERE id = ?", (json.dumps(st), game["id"]))
    status = "won" if st["points"] >= TETRIS_WIN_MIN else "lost"
    return finish_game(db, game, "tetris", status, st["points"])


def tetris_expire(game):
    if game["status"] == "playing" and time.time() - (game["started_at"] or 0) >= TETRIS_TIME:
        db = get_db()
        tetris_finish(db, game, json.loads(game["secret"]), "tempo")
        game = db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone()
    return game


def tetris_payload(game):
    st = json.loads(game["secret"])
    tray = []
    for pid in st["tray"]:
        if pid is None:
            tray.append(None)
        else:
            p = TETRIS_PIECES[pid]
            tray.append({"id": pid, "cells": [list(x) for x in p["cells"]], "w": p["w"], "h": p["h"],
                         "color": p["color"]})
    out = {"status": game["status"], "board": st["board"], "tray": tray, "points": st["points"],
           "lines": st["lines"], "limit": TETRIS_TIME, "line_points": TETRIS_LINE_POINTS}
    if game["status"] == "playing":
        out["remaining"] = round(max(0.0, TETRIS_TIME - (time.time() - game["started_at"])), 2)
    else:
        out["score"] = game["score"]
        out["reason"] = st.get("reason")
    return out


@app.route("/api/tetris/state")
def api_tetris_state():
    return jsonify(tetris_payload(tetris_expire(current_game("tetris", create=True))))


@app.route("/api/tetris/new", methods=["POST"])
def api_tetris_new():
    game = current_game("tetris")
    if game is not None:
        game = tetris_expire(game)
        if game["status"] == "playing":
            return jsonify(tetris_payload(game))
    session.pop("tetris_game", None)
    return jsonify(tetris_payload(current_game("tetris", create=True)))


@app.route("/api/tetris/move", methods=["POST"])
def api_tetris_move():
    game = current_game("tetris")
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    game = tetris_expire(game)
    if game["status"] != "playing":                       # tempo esgotado
        out = tetris_payload(game)
        out.update(ok=False, new_badges=[])
        return jsonify(out)

    body = request.get_json(silent=True) or {}
    slot, r, c = body.get("piece"), body.get("r"), body.get("c")
    if (not all(isinstance(x, int) and not isinstance(x, bool) for x in (slot, r, c))
            or slot not in (0, 1, 2)):
        return jsonify(error="Jogada inválida."), 400
    st = json.loads(game["secret"])
    pid = st["tray"][slot]
    if pid is None:
        return jsonify(error="Essa peça já foi usada."), 400
    piece = TETRIS_PIECES[pid]
    board = list(st["board"])
    if not tetris_fits(board, piece, r, c):
        return jsonify(error="A peça não cabe aí."), 400

    n = TETRIS_N
    placed = [[r + dr, c + dc] for dr, dc in piece["cells"]]
    for pr, pc in placed:
        board[pr * n + pc] = str(piece["color"])
    rows = [i for i in range(n) if all(board[i * n + j] != "." for j in range(n))]
    cols = [j for j in range(n) if all(board[i * n + j] != "." for i in range(n))]
    for i in rows:
        for j in range(n):
            board[i * n + j] = "."
    for j in cols:
        for i in range(n):
            board[i * n + j] = "."
    gained = (len(rows) + len(cols)) * TETRIS_LINE_POINTS
    st.update(board="".join(board), points=st["points"] + gained, lines=st["lines"] + len(rows) + len(cols))
    st["tray"][slot] = None
    if all(x is None for x in st["tray"]):
        st["tray"] = [random.randrange(len(TETRIS_PIECES)) for _ in range(3)]

    db = get_db()
    new = []
    if tetris_has_move(board, st["tray"]):
        db.execute("UPDATE games SET secret = ? WHERE id = ?", (json.dumps(st), game["id"]))
        db.commit()
    else:                                                   # preso: sem onde encaixar
        _score, new = tetris_finish(db, game, st, "sem_jogadas")
    out = tetris_payload(db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone())
    out.update(ok=True, placed=placed, cleared={"rows": rows, "cols": cols}, gained=gained, new_badges=new)
    return jsonify(out)


# --------------------------------------------------------------------------
# Memória Avançada (o servidor só envia as posições durante a fase de memorização)
# --------------------------------------------------------------------------
MEM_LOOK = 5                                  # segundos para memorizar
MEM_MAX_ERRORS = 4                            # com 4 erros a partida acaba
MEM_PHASES = [("Fácil", 3, 3), ("Médio", 4, 4), ("Difícil", 5, 5)]   # nome, lado do tabuleiro, nº de objetos
MEM_EMOJIS = [
    "🍕", "🍔", "🍟", "🌭", "🍿", "🥪", "🌮", "🌯", "🍝", "🍜", "🍣", "🍱", "🍩", "🍪", "🎂", "🍰", "🧁", "🍫",
    "🍓", "🍉", "🍇", "🍍", "🍎", "🥑", "🍒", "📦", "📱", "💻", "⌚", "📷", "🎧", "🎮", "💡", "🔦", "📚",
    "✏️", "🖊️", "🎒", "🕰️", "🔑", "🔒", "🪑", "🛋️", "🪞", "🧸", "🎁", "🧹", "🪣", "🧯", "🪜", "🧩",
]


def new_memoria_secret():
    pool = random.sample(MEM_EMOJIS, sum(n for _, _, n in MEM_PHASES))
    phases = []
    for _, size, n in MEM_PHASES:
        emojis, pool = pool[:n], pool[n:]
        spots = random.sample([(r, c) for r in range(size) for c in range(size)], n)
        items = [[e, r, c] for e, (r, c) in zip(emojis, spots)]
        tray = emojis[:]
        random.shuffle(tray)
        phases.append({"size": size, "items": items, "tray": tray})
    return json.dumps({"phases": phases, "phase": 0, "errors": 0, "mode": "look", "look_at": time.time()})


def memoria_payload(game, data=None):
    data = data or json.loads(game["secret"])
    out = {"status": game["status"], "phase": data["phase"], "phases": len(MEM_PHASES),
           "errors": data["errors"], "max_errors": MEM_MAX_ERRORS, "look_time": MEM_LOOK}
    if game["status"] != "playing":
        out["score"] = game["score"]
        return out
    ph = data["phases"][data["phase"]]
    out.update(level=MEM_PHASES[data["phase"]][0], size=ph["size"], count=len(ph["items"]))
    if data["mode"] == "look":
        remaining = MEM_LOOK - (time.time() - data["look_at"])
        if remaining > -1.5:           # passou do tempo (com folga): volta a esconder
            out.update(mode="look", items=ph["items"], remaining=max(0.0, remaining))
            return out
    out.update(mode="place", tray=ph["tray"])
    return out


def memoria_save(db, game, data):
    db.execute("UPDATE games SET secret = ? WHERE id = ?", (json.dumps(data), game["id"]))


@app.route("/api/memoria/state")
def api_memoria_state():
    game = current_game("memoria", create=True)
    data = json.loads(game["secret"])
    if game["status"] == "playing" and data["mode"] == "look" and time.time() - data["look_at"] > MEM_LOOK + 1.5:
        data["mode"] = "place"                       # recarregou a página durante a fase: não vê de novo
        memoria_save(get_db(), game, data)
        get_db().commit()
    return jsonify(memoria_payload(game, data))


@app.route("/api/memoria/new", methods=["POST"])
def api_memoria_new():
    game = current_game("memoria")
    if game is not None and game["status"] == "playing":
        return jsonify(memoria_payload(game))
    session.pop("memoria_game", None)
    return jsonify(memoria_payload(current_game("memoria", create=True)))


@app.route("/api/memoria/hide", methods=["POST"])
def api_memoria_hide():
    """O navegador avisa que os 5 segundos acabaram; o servidor confere o relógio."""
    game = current_game("memoria")
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    data = json.loads(game["secret"])
    if data["mode"] == "look" and time.time() - data["look_at"] >= MEM_LOOK - 0.5:
        data["mode"] = "place"
        memoria_save(get_db(), game, data)
        get_db().commit()
    return jsonify(memoria_payload(game, data))


@app.route("/api/memoria/check", methods=["POST"])
def api_memoria_check():
    game = current_game("memoria")
    if game is None or game["status"] != "playing":
        return jsonify(error="Nenhuma partida em andamento."), 409
    db = get_db()
    data = json.loads(game["secret"])
    if data["mode"] != "place":
        return jsonify(error="Ainda é hora de memorizar."), 409
    ph = data["phases"][data["phase"]]
    size = ph["size"]
    placed = (request.get_json(silent=True) or {}).get("placed")
    try:
        guess = {(str(e), int(r), int(c)) for e, r, c in placed}
        if len(guess) != len(ph["items"]) or any(not (0 <= r < size and 0 <= c < size) for _, r, c in guess):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error="Coloque todos os objetos no tabuleiro."), 400
    truth = {(e, r, c) for e, r, c in ph["items"]}
    ok = guess == truth
    wrong = [] if ok else [[r, c] for e, r, c in guess if (e, r, c) not in truth]
    new = []
    status = "playing"
    if ok:
        data["phase"] += 1
        if data["phase"] >= len(MEM_PHASES):
            status = "won"
        else:
            data["mode"], data["look_at"] = "look", time.time()
    else:
        data["errors"] += 1
        if data["errors"] >= MEM_MAX_ERRORS:
            status = "lost"
        else:
            data["mode"], data["look_at"] = "look", time.time()   # mais 5 segundos na mesma fase
    if status != "playing":
        _score, new = finish_game(db, game, "memoria", status, data["errors"])
    else:
        memoria_save(db, game, data)
        db.commit()
    game = db.execute("SELECT * FROM games WHERE id = ?", (game["id"],)).fetchone()
    out = memoria_payload(game, data)
    out.update(outcome="ok" if ok else "wrong", wrong=wrong, new_badges=new)
    return jsonify(out)


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
