# src/ytm_taste/main.py
import html
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from ytm_taste import db, google_oauth, sync, youtube_client

load_dotenv()

# This app's redirect URI is plain HTTP (http://127.0.0.1:8000/auth/callback)
# since it's local-only by design (no deployment/hosting this cycle). Google's
# oauthlib refuses to process a non-HTTPS authorization_response URL unless
# this is set — the standard, documented approach for local OAuth development.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

app = FastAPI(title="ytm-taste")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"])

REDIRECT_URI = "http://127.0.0.1:8000/auth/callback"

DB_PATH = "data/ytm_taste.db"

BASE_STYLES = """
:root{--bg:#0c0a14;--surface:#171130;--surface-2:#1e1740;--primary:#7c3aed;
  --primary-glow:#a855f7;--fg:#f5f3ff;--muted:#a29dc4;--border:rgba(255,255,255,.08)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:'Poppins',system-ui,sans-serif;line-height:1.6}
.container{width:70%;max-width:1400px;margin:0 auto;padding:2.5rem 1.25rem}
h1{font-family:'Righteous',system-ui,cursive;font-weight:400;font-size:2rem;margin:0 0 .5rem;
  background:linear-gradient(90deg,var(--primary-glow),#e9d5ff);
  -webkit-background-clip:text;background-clip:text;color:transparent}
a{color:var(--primary-glow);text-decoration:none}
a:hover{text-decoration:underline}
.sub{color:var(--muted);margin:0 0 1.5rem}
.artists{list-style:none;padding:0;margin:1.5rem 0}
.artists li{display:flex;align-items:center;gap:1rem;padding:.75rem 1rem;margin-bottom:.6rem;
  background:var(--surface);border:1px solid var(--border);border-radius:14px}
.rank{font-family:'Righteous',cursive;color:var(--primary-glow);width:1.5rem}
.count{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}
.empty{color:var(--muted)}
.recs{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
  gap:1.25rem;list-style:none;padding:0;margin:1.5rem 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:1rem;text-align:center;cursor:pointer;transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-4px);box-shadow:0 0 24px rgba(124,58,237,.45)}
.cover-wrap{position:relative;width:120px;height:120px;margin:0 auto .75rem}
.cover{width:100%;height:100%;border-radius:12px;object-fit:cover;
  transition:border-radius .3s;background:var(--surface-2)}
.card:hover .cover{border-radius:50%;animation:spin 3s linear infinite}
.cover-wrap::after{content:"";position:absolute;top:50%;left:50%;width:14px;height:14px;
  margin:-7px;border-radius:50%;background:var(--bg);box-shadow:0 0 0 3px rgba(255,255,255,.15);
  opacity:0;transition:opacity .3s;pointer-events:none}
.card:hover .cover-wrap::after{opacity:1}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion: reduce){.card:hover .cover{animation:none}}
.card .artist{font-weight:600;font-size:.95rem}
.card .track{color:var(--muted);font-size:.85rem}
.hidden{display:none}
.more-btn{display:block;margin:1.75rem auto 0;padding:.7rem 1.5rem;background:var(--primary);
  color:#fff;border:none;border-radius:999px;font-family:'Poppins';font-weight:600;
  cursor:pointer;transition:background .2s,box-shadow .2s}
.more-btn:hover{background:var(--primary-glow);box-shadow:0 0 18px rgba(168,85,247,.5)}
.profiles{list-style:none;padding:0;margin:1.5rem 0;display:flex;flex-direction:column;gap:1rem}
.profile{position:relative;display:flex;align-items:center;gap:1.25rem;background:var(--surface);
  background-size:cover;background-position:center;
  border:1px solid var(--border);border-radius:20px;padding:1.25rem 1.5rem}
.profile:nth-child(even){flex-direction:row-reverse;text-align:right}
.profile.linkable{cursor:pointer;transition:transform .2s,box-shadow .2s,border-color .2s}
.profile.linkable:hover{transform:translateY(-3px);border-color:var(--primary-glow);
  box-shadow:0 0 22px rgba(124,58,237,.4)}
.card-link{position:absolute;inset:0;border-radius:20px;z-index:1}
.avatar{width:84px;height:84px;border-radius:50%;object-fit:cover;flex:0 0 auto;
  background:var(--surface-2);border:2px solid var(--primary-glow)}
.avatar-ph{display:flex;align-items:center;justify-content:center;
  font-family:'Righteous',cursive;font-size:2rem;color:var(--primary-glow)}
.p-body{flex:1;min-width:0}
.p-name{font-family:'Righteous',cursive;font-size:1.25rem;color:var(--fg);margin:0 0 .15rem}
.p-genre{color:var(--primary-glow);font-size:.85rem;text-transform:uppercase;
  letter-spacing:.04em;margin:0 0 .4rem}
.p-bio{color:var(--muted);font-size:.9rem;margin:0 0 .4rem}
.p-fact{color:var(--muted);font-size:.8rem;opacity:.8;margin:0}
"""


def _html_page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n"
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?"
        "family=Poppins:wght@300;400;500;600;700&family=Righteous&display=swap\">\n"
        f"<style>{BASE_STYLES}</style>\n"
        "</head>\n<body>\n<div class=\"container\">\n"
        f"{body}\n</div>\n</body>\n</html>"
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "ytm-taste"}


def render_results_page(artists) -> str:
    if not artists:
        body = (
            "<h1>Your Top Artists</h1>"
            '<p class="empty">No liked music synced yet — if you just logged in, '
            "give it a few seconds and refresh.</p>"
            '<p><a href="/recommendations">Songs you might like &rarr;</a></p>'
        )
        return _html_page("Your Top Artists", body)

    cards = []
    for a in artists:
        name = html.escape(a["name"])
        if a["avatar"]:
            avatar = f'<img class="avatar" src="{html.escape(a["avatar"])}" alt="">'
        else:
            initial = html.escape(a["name"][:1].upper() or "?")
            avatar = f'<div class="avatar avatar-ph">{initial}</div>'
        genre = f'<p class="p-genre">{html.escape(a["genre"])}</p>' if a["genre"] else ""
        bio = f'<p class="p-bio">{html.escape(a["bio"])}</p>' if a["bio"] else ""
        if a["listeners"]:
            fact = f'<p class="p-fact">{a["listeners"]:,} listeners on Last.fm</p>'
        else:
            fact = ""
        if a.get("album"):
            overlay = "rgba(23,17,48,.86)"
            style = (
                f' style="background-image:linear-gradient({overlay},{overlay}),'
                f"url('{html.escape(a['album'])}')\""
            )
        else:
            style = ""
        if a.get("channel_id"):
            url = f"https://www.youtube.com/channel/{html.escape(a['channel_id'])}"
            link = (
                f'<a class="card-link" href="{url}" target="_blank" rel="noopener" '
                f'aria-label="Open {name} on YouTube"></a>'
            )
            cls = "profile linkable"
        else:
            link = ""
            cls = "profile"
        cards.append(
            f'<li class="{cls}"{style}>{link}{avatar}'
            f'<div class="p-body"><p class="p-name">{name}</p>{genre}{bio}{fact}</div></li>'
        )
    body = (
        "<h1>Your Top Artists</h1>"
        '<p class="sub">Your most-played artists across likes and playlists.</p>'
        f'<ul class="profiles">{"".join(cards)}</ul>'
        '<p><a href="/recommendations">Songs you might like &rarr;</a></p>'
    )
    return _html_page("Your Top Artists", body)


def render_recommendations_page(recs) -> str:
    if not recs:
        body = (
            "<h1>Songs You Might Like</h1>"
            '<p class="empty">No recommendations yet — after you log in, the sync '
            "generates them in the background; give it a moment and refresh.</p>"
            '<p><a href="/">&larr; back to your top artists</a></p>'
        )
        return _html_page("Songs You Might Like", body)

    cards = []
    for i, (artist, track, _score, image_url, preview_url) in enumerate(recs):
        hidden = " hidden" if i >= 5 else ""
        cover = (
            f'<img class="cover" loading="lazy" src="{html.escape(image_url)}" alt="">'
            if image_url
            else '<div class="cover"></div>'
        )
        audio = (
            f'<audio preload="none" src="{html.escape(preview_url)}"></audio>'
            if preview_url
            else ""
        )
        cards.append(
            f'<li class="card{hidden}">'
            f'<div class="cover-wrap">{cover}</div>'
            f'<div class="artist">{html.escape(artist)}</div>'
            f'<div class="track">{html.escape(track)}</div>'
            f"{audio}</li>"
        )
    more = '<button id="more-btn" class="more-btn">Show 5 more</button>' if len(recs) > 5 else ""
    script = """
<script>
document.querySelectorAll('.card').forEach(function(card){
  var a = card.querySelector('audio');
  if(a){ a.volume = 0.25; }
  card.addEventListener('mouseenter', function(){ if(a){ a.play().catch(function(){}); } });
  card.addEventListener('mouseleave', function(){ if(a){ a.pause(); a.currentTime = 0; } });
});
var moreBtn = document.getElementById('more-btn');
if(moreBtn){ moreBtn.addEventListener('click', function(){
  var hidden = document.querySelectorAll('.card.hidden');
  for(var i=0;i<5 && i<hidden.length;i++){ hidden[i].classList.remove('hidden'); }
  if(document.querySelectorAll('.card.hidden').length===0){ moreBtn.style.display='none'; }
}); }
</script>
"""
    body = (
        "<h1>Songs You Might Like</h1>"
        '<p class="sub">Hover a cover to spin it and hear a preview.</p>'
        f'<ul class="recs">{"".join(cards)}</ul>'
        f"{more}"
        '<p><a href="/">&larr; back to your top artists</a></p>'
        f"{script}"
    )
    return _html_page("Songs You Might Like", body)


@app.get("/")
def read_root(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        return RedirectResponse("/login")
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    top = db.get_top_artists(conn, user_id)[:5]
    channels = db.get_top_artist_channels(conn, user_id)
    artists = []
    for name, _count in top:
        d = db.get_artist_details(conn, name) or {}
        artists.append(
            {
                "name": name,
                "avatar": d.get("avatar_url"),
                "genre": d.get("genre"),
                "bio": d.get("bio"),
                "listeners": d.get("listeners"),
                "album": d.get("album_art_url"),
                "channel_id": channels.get(name),
            }
        )
    conn.close()
    return HTMLResponse(render_results_page(artists))


@app.get("/recommendations")
def recommendations_page(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        return RedirectResponse("/login")
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    recs = db.get_recommendations(conn, user_id)
    conn.close()
    return HTMLResponse(render_recommendations_page(recs))


def _build_flow(code_verifier: str | None = None):
    return google_oauth.build_flow(
        os.environ["GOOGLE_WEB_CLIENT_ID"],
        os.environ["GOOGLE_WEB_CLIENT_SECRET"],
        REDIRECT_URI,
        code_verifier=code_verifier,
    )


@app.get("/login")
def login(request: Request):
    flow = _build_flow()
    authorization_url, state, code_verifier = google_oauth.get_authorization_url(flow)
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier
    return RedirectResponse(authorization_url)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request, background_tasks: BackgroundTasks):
    state = request.query_params.get("state")
    if state is None or state != request.session.get("oauth_state"):
        return HTMLResponse("Login failed: invalid or expired login attempt.", status_code=400)
    code_verifier = request.session.get("oauth_code_verifier")
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_code_verifier", None)

    flow = _build_flow(code_verifier=code_verifier)
    credentials = google_oauth.fetch_credentials(flow, str(request.url))
    youtube = youtube_client.build_youtube_client(credentials)
    channel_id = youtube_client.get_channel_id(youtube)
    if channel_id is None:
        return HTMLResponse(
            "Login failed: your YouTube account needs a channel before you can use this app.",
            status_code=400,
        )

    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    now = datetime.now(timezone.utc).isoformat()
    user_id = db.get_or_create_user(conn, channel_id, credentials.to_json(), now)
    conn.commit()
    conn.close()

    request.session["user_id"] = user_id
    background_tasks.add_task(
        sync.run_sync, DB_PATH, user_id, youtube,
        lastfm_api_key=os.environ.get("LASTFM_API_KEY"),
    )

    return RedirectResponse("/")
