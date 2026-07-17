# src/ytm_taste/main.py
import html
import os
import time
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from ytm_taste import db, deezer_client, google_oauth, recommendations, sync, youtube_client

load_dotenv()

# Everything that differs between a laptop and a host lives here, so one build
# serves both. BASE_URL is where users actually reach the app; Google matches the
# redirect URI against it character-for-character, so it must be the public
# address, not the address the process happens to bind to.
BASE_URL = os.environ.get("YTM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DB_PATH = os.environ.get("YTM_DB_PATH", "data/ytm_taste.db")

REDIRECT_URI = f"{BASE_URL}/auth/callback"

# A loopback redirect is necessarily plain HTTP, and oauthlib refuses a non-HTTPS
# authorization_response without this — the documented approach for local OAuth.
# Deployed behind HTTPS it must stay ABSENT, or the check is off in production.
# There is no way to set it falsely: oauthlib only tests that the variable is
# non-empty, so "0" would disable the check just as surely as "1". Being unset is
# the only safe state, which is why this is a conditional and not a value.
IS_LOCAL_HTTP = BASE_URL.startswith("http://")
if IS_LOCAL_HTTP:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _clear_stale_syncing() -> None:
    """A background sync dies with its process, but its users.syncing flag
    survives in the DB. Left set, it would gate /artists forever and bounce the
    user between the loader and the gate. Nothing can be syncing in a process
    that has only just started, so clear the flags on the way up."""
    try:
        conn = db.get_connection(DB_PATH)
        db.init_db(conn)
        db.clear_all_syncing(conn)
        conn.commit()
        conn.close()
    except Exception as exc:  # never block startup on this
        print(f"Could not clear stale syncing flags (skipped): {exc}")


@asynccontextmanager
async def lifespan(app):
    _clear_stale_syncing()
    yield


app = FastAPI(title="ytm-taste", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SECRET_KEY"],
    # Deployed, the session cookie must never travel over plain HTTP. Locally the
    # app *is* plain HTTP, so demanding HTTPS there would stop the browser storing
    # the cookie at all and nobody could stay logged in.
    https_only=not IS_LOCAL_HTTP,
)

BASE_STYLES = """
:root{--bg:#0c0a14;--surface:#171130;--surface-2:#1e1740;--primary:#7c3aed;
  --primary-glow:#a855f7;--fg:#f5f3ff;--muted:#a29dc4;--border:rgba(255,255,255,.08)}
*{box-sizing:border-box}
body{margin:0;background-color:var(--bg);color:var(--fg);
  font-family:'Poppins',system-ui,sans-serif;line-height:1.6}
.container{width:70%;max-width:1400px;margin:0 auto;padding:2.5rem 1.25rem}
.container.wide{width:90%;max-width:1750px}
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
.recs{display:flex;flex-wrap:wrap;justify-content:center;align-items:stretch;
  gap:1.75rem;list-style:none;padding:0;margin:1.5rem 0}
.card{position:relative;flex:0 0 300px;background:var(--surface);border:1px solid var(--border);
  border-radius:20px;padding:1.5rem;text-align:center;cursor:pointer;
  transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-4px);box-shadow:0 0 24px rgba(124,58,237,.45)}
.song-link{position:absolute;inset:0;border-radius:20px;z-index:2}
.song-link:focus-visible{outline:2px solid var(--primary-glow);outline-offset:2px}
.cover-wrap{position:relative;width:230px;height:230px;margin:0 auto 1rem}
.cover{width:100%;height:100%;border-radius:12px;object-fit:cover;
  transition:border-radius .3s;background:var(--surface-2)}
.cover-ph{display:flex;align-items:center;justify-content:center;
  font-family:'Righteous',cursive;font-size:2.4rem;color:var(--primary-glow);
  background:linear-gradient(150deg,var(--surface-2),var(--surface))}
.card:hover .cover{border-radius:50%;animation:spin 3s linear infinite}
.cover-wrap::after{content:"";position:absolute;top:50%;left:50%;width:14px;height:14px;
  margin:-7px;border-radius:50%;background:var(--bg);box-shadow:0 0 0 3px rgba(255,255,255,.15);
  opacity:0;transition:opacity .3s;pointer-events:none}
.card:hover .cover-wrap::after{opacity:1}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion: reduce){.card:hover .cover{animation:none}}
.card .artist{font-weight:600;font-size:1.15rem}
.card .track{color:var(--muted);font-size:.95rem;margin-top:.15rem}
.hidden{display:none}
.more-btn{display:block;margin:1.75rem auto 0;padding:.7rem 1.5rem;background:var(--primary);
  color:#fff;border:none;border-radius:999px;font-family:'Poppins';font-weight:600;
  cursor:pointer;transition:background .2s,box-shadow .2s}
.more-btn:hover{background:var(--primary-glow);box-shadow:0 0 18px rgba(168,85,247,.5)}
.profile{position:relative;display:flex;align-items:center;gap:1.25rem;background:var(--surface);
  background-size:cover;background-position:center;
  border:1px solid var(--border);border-radius:20px;padding:1.25rem 1.5rem}
.eyebrow{display:flex;align-items:center;gap:.55rem;margin:0 0 .4rem;font-size:.72rem;
  letter-spacing:.15em;text-transform:uppercase;color:var(--primary-glow)}
.eyebrow::before{content:"";width:1.6rem;height:2px;border-radius:2px;background:var(--primary-glow)}
.hero{margin:1.5rem 0;padding:1.9rem 2rem;gap:1.9rem;box-shadow:0 10px 40px rgba(0,0,0,.35)}
.hero .avatar{width:132px;height:132px;border-width:3px}
.hero .p-name{font-size:2rem;margin-bottom:.25rem}
.hero .p-bio{font-size:.95rem}
.ranked{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:.75rem}
.rank-item{padding:1rem 1.25rem;gap:1rem}
.rank-item .avatar{width:60px;height:60px}
.rank-item .p-name{font-size:1.1rem}
.rank-item .p-bio{font-size:.85rem}
@media (max-width:600px){.hero{flex-direction:column;text-align:center;gap:1.1rem}
  .hero .avatar{width:104px;height:104px}.hero .eyebrow{justify-content:center}}
@keyframes cardIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.profile{animation:cardIn .55s ease backwards}
.hero{animation-delay:.05s}
.ranked li:nth-child(1){animation-delay:.20s}
.ranked li:nth-child(2){animation-delay:.32s}
.ranked li:nth-child(3){animation-delay:.44s}
.ranked li:nth-child(4){animation-delay:.56s}
@media (prefers-reduced-motion:reduce){.profile{animation:none}}
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
.ft-dock{position:fixed;right:1.5rem;bottom:1.5rem;z-index:20;display:flex;
  flex-direction:column;align-items:flex-end;gap:.5rem}
.ft-gear{width:44px;height:44px;font-size:1.15rem;line-height:1;color:var(--muted);
  background:var(--surface);border:1px solid var(--border);border-radius:50%;cursor:pointer;
  box-shadow:0 6px 20px rgba(0,0,0,.4);transition:color .2s,border-color .2s,transform .2s}
.ft-gear:hover{color:var(--fg);border-color:var(--primary-glow);transform:rotate(45deg)}
.ft-gear:focus-visible{outline:2px solid var(--primary-glow);outline-offset:3px}
.ft-menu{display:flex;flex-direction:column;gap:.35rem;padding:.4rem;background:var(--surface);
  border:1px solid var(--border);border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.45)}
.ft-item{min-height:40px;padding:.5rem 1.1rem;font-family:'Poppins',sans-serif;
  font-size:.85rem;font-weight:600;color:var(--fg);background:none;border:none;
  border-radius:10px;cursor:pointer;white-space:nowrap;text-align:right;
  transition:background .15s,color .15s}
.ft-item:hover{background:var(--surface-2);color:var(--primary-glow)}
.ft-item:focus-visible{outline:2px solid var(--primary-glow);outline-offset:-2px}
.ft-overlay{position:fixed;inset:0;z-index:30;display:flex;align-items:center;
  justify-content:center;padding:1.25rem;background:rgba(6,4,12,.72)}
/* `display:flex` above beats the browser's [hidden]{display:none} at equal specificity,
   so the wizard would render open on load. A compound selector wins whatever the order. */
.ft-overlay[hidden],.ft-menu[hidden]{display:none}
.ft-panel{position:relative;width:min(30rem,100%);padding:2rem;background:var(--surface);
  border:1px solid var(--border);border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.ft-close{position:absolute;top:.6rem;right:.9rem;background:none;border:none;
  color:var(--muted);font-size:1.5rem;line-height:1;cursor:pointer}
.ft-close:hover{color:var(--fg)}
.ft-panel h2{font-family:'Righteous',cursive;font-weight:400;font-size:1.4rem;
  margin:0 0 .35rem;color:var(--fg)}
.ft-hint{margin:0 0 1rem;font-size:.85rem;color:var(--muted)}
.ft-step{opacity:1;transform:translateY(0);transition:opacity .22s ease,transform .22s ease}
.ft-step.ft-out{opacity:0;transform:translateY(-8px)}
.ft-step.ft-in{opacity:0;transform:translateY(8px)}
.ft-opts{display:flex;flex-direction:column;gap:.5rem;margin:1rem 0 1.4rem;
  max-height:46vh;overflow-y:auto}
.ft-opt{display:flex;align-items:center;gap:.7rem;min-height:44px;padding:.6rem .9rem;
  background:var(--surface-2);border:1px solid var(--border);border-radius:12px;
  cursor:pointer;transition:border-color .2s}
.ft-opt:hover{border-color:var(--primary-glow)}
.ft-opt input{accent-color:var(--primary-glow);width:1.05rem;height:1.05rem;flex:0 0 auto}
.ft-opt em{color:var(--muted);font-style:normal;font-size:.8rem}
.ft-panel .more-btn{margin:0;width:100%}
@media (prefers-reduced-motion:reduce){.ft-step{transition:none}}
.pagenav{display:flex;margin:2.25rem 0 0}
.pagenav-link{display:flex;flex-direction:column;justify-content:center;gap:.1rem;
  min-height:44px;min-width:min(300px,100%);padding:.85rem 1.25rem;background:var(--surface);
  border:1px solid var(--border);border-radius:16px;
  transition:transform .2s,border-color .2s,box-shadow .2s}
.pagenav-link:hover{text-decoration:none;transform:translateY(-3px);
  border-color:var(--primary-glow);box-shadow:0 0 22px rgba(124,58,237,.4)}
.pagenav-link:focus-visible{outline:2px solid var(--primary-glow);outline-offset:3px}
.pagenav-dir{font-size:.7rem;text-transform:uppercase;letter-spacing:.16em;color:var(--muted)}
.pagenav-title{font-family:'Righteous',cursive;font-size:1.05rem;color:var(--primary-glow)}
.pagenav-link.next{margin-left:auto;text-align:right}
.pagenav-link.prev{margin-right:auto}
.pagenav-link.next .pagenav-title::after{content:"\\2192";margin-left:.4rem}
.pagenav-link.prev .pagenav-title::before{content:"\\2190";margin-right:.4rem}
.topbar{display:flex;align-items:center;gap:1rem;margin:0 0 1.5rem}
.refresh-form{margin-left:auto}
.refresh-data-btn{display:inline-flex;align-items:center;gap:.45rem;min-height:44px;
  padding:.45rem 1.1rem;font-family:'Poppins',sans-serif;font-size:.85rem;font-weight:600;
  color:var(--muted);background:var(--surface);border:1px solid var(--border);
  border-radius:999px;cursor:pointer;transition:color .2s,border-color .2s,box-shadow .2s}
.refresh-data-btn:hover{color:var(--fg);border-color:var(--primary-glow);
  box-shadow:0 0 18px rgba(124,58,237,.35)}
.refresh-data-btn:focus-visible{outline:2px solid var(--primary-glow);outline-offset:3px}
.home-link{display:inline-flex;align-items:center;gap:.5rem;padding:.45rem 1rem;
  font-family:'Righteous',cursive;font-size:.95rem;color:var(--primary-glow);
  background:var(--surface);border:1px solid var(--border);border-radius:999px;
  transition:border-color .2s,box-shadow .2s,transform .2s}
.home-link::before{content:"\\2190";font-family:'Poppins',sans-serif}
.home-link:hover{text-decoration:none;transform:translateY(-2px);border-color:var(--primary-glow);
  box-shadow:0 0 18px rgba(124,58,237,.4)}
.landing{min-height:70vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;gap:1rem;padding:2rem 0;position:relative;animation:cardIn .6s ease backwards}
.landing::before{content:"";position:absolute;top:8%;left:50%;width:min(680px,90%);height:340px;
  transform:translateX(-50%);background:radial-gradient(closest-side,rgba(124,58,237,.35),transparent);
  filter:blur(30px);z-index:-1;pointer-events:none}
.eyebrow2{margin:0;text-transform:uppercase;letter-spacing:.28em;font-size:.72rem;color:var(--muted)}
.wordmark{font-family:'Righteous',cursive;font-weight:400;font-size:clamp(3rem,10vw,5.5rem);
  line-height:1;margin:.25rem 0;background:linear-gradient(100deg,var(--primary-glow),#e9d5ff 60%,
  var(--primary));-webkit-background-clip:text;background-clip:text;color:transparent}
.lead{margin:0;font-size:clamp(1.3rem,3vw,1.9rem);font-weight:600;color:var(--fg)}
.lead-sub{margin:0;max-width:34rem;color:var(--muted)}
.eq{display:flex;align-items:flex-end;gap:.35rem;height:56px;margin:.6rem 0}
.eq span{width:8px;height:16px;border-radius:4px;
  background:linear-gradient(var(--primary-glow),var(--primary));animation:eqBounce 1s ease-in-out
  infinite}
.eq span:nth-child(1){animation-delay:-.9s}.eq span:nth-child(2){animation-delay:-.7s}
.eq span:nth-child(3){animation-delay:-.5s}.eq span:nth-child(4){animation-delay:-.3s}
.eq span:nth-child(5){animation-delay:-.6s}.eq span:nth-child(6){animation-delay:-.2s}
.eq span:nth-child(7){animation-delay:-.4s}
@keyframes eqBounce{0%,100%{height:14px}50%{height:52px}}
.cta{display:inline-block;margin:.4rem 0 .6rem;padding:.85rem 2rem;background:var(--primary);
  color:#fff;border-radius:999px;font-weight:600;box-shadow:0 8px 30px rgba(124,58,237,.4);
  transition:background .2s,box-shadow .2s,transform .2s}
.cta:hover{background:var(--primary-glow);text-decoration:none;transform:translateY(-2px);
  box-shadow:0 10px 34px rgba(168,85,247,.55)}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin-top:1.25rem;
  width:100%;max-width:640px}
.tile{display:flex;flex-direction:column;align-items:center;gap:.35rem;padding:1.25rem 1rem;
  background:var(--surface);border:1px solid var(--border);border-radius:16px;color:var(--fg);
  transition:transform .2s,box-shadow .2s,border-color .2s}
.tile:hover{transform:translateY(-3px);border-color:var(--primary-glow);text-decoration:none;
  box-shadow:0 0 22px rgba(124,58,237,.4)}
.tile-ic{font-size:1.6rem}
.tile-h{font-weight:600}
.tile-p{font-size:.82rem;color:var(--muted)}
@media (max-width:560px){.tiles{grid-template-columns:1fr}}
.landing-bar .refresh-form{margin-left:0}
.stats{display:flex;justify-content:center;flex-wrap:wrap;gap:3.5rem;width:100%;
  margin-top:2.25rem;padding-top:1.75rem;border-top:1px solid var(--border)}
.stat{display:flex;flex-direction:column;align-items:center;gap:.15rem}
.stat-n{font-family:'Righteous',cursive;font-size:2rem;color:var(--fg);
  font-variant-numeric:tabular-nums}
.stat-l{font-size:.8rem;color:var(--muted)}
@media (prefers-reduced-motion:reduce){.eq span{animation:none;height:32px}.landing{animation:none}}
"""

def _html_page(title: str, body: str, wide: bool = False) -> str:
    # The recommendations grid asks for a wider container so its bigger cards fill
    # more of the screen; every other page keeps the standard 70% width.
    container = "container wide" if wide else "container"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n"
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?"
        "family=Poppins:wght@300;400;500;600;700&family=Righteous&display=swap\">\n"
        f"<style>{BASE_STYLES}</style>\n"
        f"</head>\n<body>\n<div class=\"{container}\">\n"
        f"{body}\n</div>\n</body>\n</html>"
    )


_ALLOWED_NEXT = {"/artists", "/recommendations"}


def _safe_next(value) -> str:
    return value if value in _ALLOWED_NEXT else "/artists"


def _session_user(request: Request, conn) -> int | None:
    """The logged-in user, or None if the cookie names someone who no longer exists.

    A browser cookie outlives the database. Without this check a wipe, restore or bad
    migration bricks every logged-in visitor: the app sees the cookie and skips the
    landing page, then asks "is their sync finished?" about a user who isn't there.
    That reads as "not ready" -- identical to a sync in progress -- so they're parked
    on the loader forever, unable to reach the landing page to sign up again.
    """
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    if not db.user_exists(conn, user_id):
        request.session.pop("user_id", None)
        return None
    return user_id


def _topbar(refresh: bool = False, next_path: str = "/artists") -> str:
    # next_path brings the user back to the page they refreshed from.
    action = (
        f'<form class="refresh-form" method="post" action="/refresh?next={next_path}">'
        '<button class="refresh-data-btn" type="submit">'
        '<span aria-hidden="true">&#8635;</span> Refresh my data</button></form>'
        if refresh
        else ""
    )
    return (
        '<header class="topbar"><a class="home-link" href="/">ytm-taste</a>'
        f"{action}</header>"
    )


def _fine_tune_wizard(playlists, prefs) -> str:
    """Three fading steps: which playlists -> discovery -> safe/adventurous."""
    def checked(name, value):
        return " checked" if prefs.get(name) == value else ""

    boxes = "".join(
        f'<label class="ft-opt"><input type="checkbox" name="playlists" '
        f'value="{html.escape(p["playlist_id"])}"'
        f'{" checked" if p["playlist_id"] in (prefs.get("playlists") or []) else ""}>'
        f'<span>{html.escape(p["title"])}<em> {p["count"]} songs</em></span></label>'
        for p in playlists
    )
    if not boxes:
        boxes = '<p class="ft-hint">No playlists big enough to build from yet.</p>'
    discovery = "".join(
        f'<label class="ft-opt"><input type="radio" name="discovery" value="{v}"'
        f'{checked("discovery", v)}><span>{label}</span></label>'
        for v, label in (
            ("love", "More from artists I love"),
            ("mix", "A mix"),
            ("new", "Artists I&rsquo;ve never heard"),
        )
    )
    mode = "".join(
        f'<label class="ft-opt"><input type="radio" name="mode" value="{v}"'
        f'{checked("mode", v)}><span>{label}</span></label>'
        for v, label in (
            ("safe", "Safe &mdash; fits my taste broadly"),
            ("adventurous", "Adventurous &mdash; bold matches"),
        )
    )
    # Reset only appears once something is actually tuned -- offering to reset
    # nothing is noise.
    tuned = any(prefs.get(k) != v for k, v in db.DEFAULT_PREFS.items())
    reset = (
        '<button id="ft-reset" class="ft-item" type="button">Reset</button>' if tuned else ""
    )
    return (
        '<div class="ft-dock">'
        '<div id="ft-menu" class="ft-menu" hidden>'
        '<button id="ft-open" class="ft-item" type="button">Fine-tune</button>'
        f"{reset}</div>"
        '<button id="ft-gear" class="ft-gear" type="button" aria-expanded="false" '
        'aria-controls="ft-menu" aria-label="Recommendation settings">&#9881;</button>'
        "</div>"
        '<div id="ft-overlay" class="ft-overlay" hidden>'
        '<div class="ft-panel">'
        '<button id="ft-close" class="ft-close" type="button" aria-label="Close">&times;</button>'
        '<div class="ft-step" data-step="1">'
        "<h2>Which playlists do you prefer?</h2>"
        '<p class="ft-hint">Pick any you like, or none to use all your music.</p>'
        f'<div class="ft-opts">{boxes}</div>'
        '<button class="ft-next more-btn" type="button">Next</button>'
        "</div>"
        '<div class="ft-step" data-step="2" hidden>'
        "<h2>Recommend&hellip;</h2>"
        f'<div class="ft-opts">{discovery}</div>'
        '<button class="ft-next more-btn" type="button">Next</button>'
        "</div>"
        '<div class="ft-step" data-step="3" hidden>'
        "<h2>Picks should be&hellip;</h2>"
        f'<div class="ft-opts">{mode}</div>'
        '<button id="ft-submit" class="more-btn" type="button">Tune my recommendations</button>'
        "</div>"
        "</div></div>"
    )


def _pagenav(direction: str, href: str, title: str) -> str:
    """Docs-style footer nav: a card previewing the destination page by name,
    pinned to the edge matching its direction."""
    label = "Next" if direction == "next" else "Previous"
    return (
        '<nav class="pagenav" aria-label="Page navigation">'
        f'<a class="pagenav-link {direction}" href="{href}" '
        f'aria-label="{label}: {title}">'
        f'<span class="pagenav-dir">{label}</span>'
        f'<span class="pagenav-title">{title}</span></a></nav>'
    )


def _landing_stats(stats: dict | None) -> str:
    if not stats:
        return ""
    cells = "".join(
        f'<div class="stat"><span class="stat-n">{value:,}</span>'
        f'<span class="stat-l">{label}</span></div>'
        for value, label in (
            (stats["tracks"], "tracks analyzed"),
            (stats["artists"], "artists ranked"),
            (stats["recs"], "song recs"),
        )
    )
    return f'<div class="stats">{cells}</div>'


def render_landing_page(logged_in: bool = False, stats: dict | None = None) -> str:
    tiles = (
        '<a class="tile" href="/artists"><span class="tile-ic">&#127911;</span>'
        '<span class="tile-h">Top Artists</span>'
        '<span class="tile-p">Your most-played, ranked.</span></a>'
        '<a class="tile" href="/recommendations"><span class="tile-ic">&#10024;</span>'
        '<span class="tile-h">Song Recs</span>'
        '<span class="tile-p">Picked from your taste.</span></a>'
        '<a class="tile" href="/recommendations"><span class="tile-ic">&#9654;</span>'
        '<span class="tile-h">Previews</span>'
        '<span class="tile-p">Hover any cover to hear it.</span></a>'
    )
    eq = (
        '<div class="eq" aria-hidden="true">'
        + "".join("<span></span>" for _ in range(7))
        + "</div>"
    )
    if logged_in:
        blurb = "Your top artists, song recs, and instant previews are ready."
        cta = '<a class="cta" href="/artists">View your taste &rarr;</a>'
        # Already synced -> a top bar to re-sync on demand, matching the other pages.
        top = (
            '<header class="topbar landing-bar">'
            '<form class="refresh-form" method="post" action="/refresh?next=/artists">'
            '<button class="refresh-data-btn" type="submit">'
            '<span aria-hidden="true">&#8635;</span> Refresh my data</button></form></header>'
        )
    else:
        blurb = (
            "Connect your YouTube account for your top artists, song recs, and instant previews."
        )
        cta = '<a class="cta" href="/login">Connect YouTube</a>'
        top = ""
    body = (
        f"{top}"
        '<div class="landing">'
        '<p class="eyebrow2">YouTube Music &middot; Taste Analyzer</p>'
        '<h1 class="wordmark">ytm-taste</h1>'
        '<p class="lead">Your listening, decoded.</p>'
        f'<p class="lead-sub">{blurb}</p>'
        f"{eq}"
        f"{cta}"
        f'<div class="tiles">{tiles}</div>'
        f"{_landing_stats(stats)}"
        "</div>"
    )
    return _html_page("ytm-taste", body)


def render_loading_page(next_target: str) -> str:
    eq = (
        '<div class="eq" aria-hidden="true">'
        + "".join("<span></span>" for _ in range(7))
        + "</div>"
    )
    target = html.escape(next_target)
    # Navigate ONLY when ready. Redirecting on a timeout would bounce off
    # /artists' not-ready gate straight back here, looping forever; instead keep
    # polling (more slowly) and say so.
    script = (
        "<script>(function(){var t=" + repr(next_target) + ";var n=0;"
        "function wait(){return n<40?1500:5000;}"
        "function note(){if(n===40){var s=document.getElementById('slow-note');"
        "if(s){s.hidden=false;}}}"
        "function c(){n++;fetch('/status').then(function(r){return r.json();})"
        ".then(function(d){if(d&&d.ready){window.location.replace(t);return;}"
        "note();setTimeout(c,wait());})"
        ".catch(function(){note();setTimeout(c,wait());});}"
        "c();})();</script>"
    )
    body = (
        f'<div class="landing" data-next="{target}">'
        '<p class="eyebrow2">YouTube Music &middot; Taste Analyzer</p>'
        '<h1 class="wordmark">ytm-taste</h1>'
        '<p class="lead">Tuning in to your library&hellip;</p>'
        '<p class="lead-sub">Reading your likes and playlists. This takes a few seconds.</p>'
        f"{eq}"
        '<p class="lead-sub slow-note" id="slow-note" hidden>Still working &mdash; '
        "this is taking longer than usual.</p>"
        f"{script}"
        "</div>"
    )
    return _html_page("Tuning in…", body)


@app.get("/health")
def health():
    return {"status": "ok", "service": "ytm-taste"}


# Cache of proxied artist avatars, keyed by source URL: {url: (content_type, bytes)}.
# YouTube throttles hotlinked yt3.ggpht.com avatars (429), so we fetch each once
# server-side (not rate-limited at our volume) and serve the bytes ourselves.
_avatar_cache: dict[str, tuple[str, bytes]] = {}


def _fetch_avatar_bytes(url: str) -> tuple[str, bytes]:
    cached = _avatar_cache.get(url)
    if cached is not None:
        return cached
    resp = requests.get(url, timeout=10)
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    result = (content_type, resp.content)
    _avatar_cache[url] = result
    return result


@app.get("/artist-avatar")
def artist_avatar(artist: str):
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    details = db.get_artist_details(conn, artist) or {}
    conn.close()
    url = details.get("avatar_url")
    if not url:
        return Response(status_code=404)
    try:
        content_type, data = _fetch_avatar_bytes(url)
    except Exception:
        # Best-effort fallback: let the browser try the original URL directly.
        return RedirectResponse(url)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Deezer signs preview URLs with a ~12-minute expiry, so they can't be stored at sync
# time -- we resolve them fresh when a card is actually played. Cache the lookup briefly
# (well under the expiry) so replaying the same card doesn't re-hit Deezer each hover.
_preview_cache: dict[tuple[str, str], tuple[float, str]] = {}
_PREVIEW_TTL_SECONDS = 300


def _resolve_preview(artist: str, track: str) -> str | None:
    key = (artist, track)
    now = time.monotonic()
    cached = _preview_cache.get(key)
    if cached is not None and now - cached[0] < _PREVIEW_TTL_SECONDS:
        return cached[1]
    url = deezer_client.fetch_preview_url(artist, track)
    if url:
        _preview_cache[key] = (now, url)
    return url


@app.get("/preview")
def preview(artist: str, track: str):
    url = _resolve_preview(artist, track)
    if not url:
        return Response(status_code=404)
    return RedirectResponse(url)


# The faded album cover behind each artist card. Fetched fresh here rather than stored
# during the sync: the sync's storage step kept coming back empty on the host even
# though Deezer answers fine one request at a time. Deezer cover URLs are static (no
# expiry, load with any referer), so a resolved one is cached for the process lifetime.
_artist_cover_cache: dict[str, str] = {}


def _resolve_artist_cover(artist: str) -> str | None:
    cached = _artist_cover_cache.get(artist)
    if cached:
        return cached
    url = deezer_client.fetch_artist_album_art(artist)
    if url:
        _artist_cover_cache[artist] = url
    return url


@app.get("/artist-cover")
def artist_cover(artist: str):
    url = _resolve_artist_cover(artist)
    if not url:
        return Response(status_code=404)
    return RedirectResponse(url)


def render_results_page(artists) -> str:
    if not artists:
        body = (
            f"{_topbar(refresh=True)}<h1>Your Top Artists</h1>"
            '<p class="empty">No liked music synced yet — if you just logged in, '
            "give it a few seconds and refresh.</p>"
            f"{_pagenav('next', '/recommendations', 'Songs You Might Like')}"
        )
        return _html_page("Your Top Artists", body)

    hero = _artist_card(artists[0], hero=True)
    ranked = "".join(_artist_card(a, hero=False) for a in artists[1:])
    ranked_block = f'<ul class="ranked">{ranked}</ul>' if ranked else ""
    body = (
        f"{_topbar(refresh=True)}<h1>Your Top Artists</h1>"
        '<p class="sub">Your most-played artists across likes and playlists.</p>'
        f"{hero}{ranked_block}"
        f"{_pagenav('next', '/recommendations', 'Songs You Might Like')}"
    )
    return _html_page("Your Top Artists", body)


def _artist_card(a, hero: bool) -> str:
    name = html.escape(a["name"])
    if a["avatar"]:
        proxied = "/artist-avatar?artist=" + urllib.parse.quote(a["name"])
        avatar = f'<img class="avatar" src="{html.escape(proxied)}" alt="">'
    else:
        initial = html.escape(a["name"][:1].upper() or "?")
        avatar = f'<div class="avatar avatar-ph">{initial}</div>'
    eyebrow = '<p class="eyebrow">Most played</p>' if hero else ""
    genre = f'<p class="p-genre">{html.escape(a["genre"])}</p>' if a["genre"] else ""
    bio = f'<p class="p-bio">{html.escape(a["bio"])}</p>' if a["bio"] else ""
    fact = (
        f'<p class="p-fact">{a["listeners"]:,} listeners on Last.fm</p>'
        if a["listeners"]
        else ""
    )
    # The faded album cover behind the card, resolved on demand by /artist-cover. If
    # Deezer has no art the request 404s and only the gradient layer shows -- the same
    # look as before. The hero shows more of its art; ranked cards keep it more faded.
    overlay = "rgba(23,17,48,.80)" if hero else "rgba(23,17,48,.88)"
    cover_src = "/artist-cover?artist=" + urllib.parse.quote(a["name"])
    style = (
        f' style="background-image:linear-gradient({overlay},{overlay}),'
        f"url('{html.escape(cover_src)}')\""
    )
    if a.get("channel_id"):
        url = f"https://www.youtube.com/channel/{html.escape(a['channel_id'])}"
        link = (
            f'<a class="card-link" href="{url}" target="_blank" rel="noopener" '
            f'aria-label="Open {name} on YouTube"></a>'
        )
        linkable = " linkable"
    else:
        link = ""
        linkable = ""
    tag = "div" if hero else "li"
    variant = "hero" if hero else "rank-item"
    return (
        f'<{tag} class="profile {variant}{linkable}"{style}>{link}{avatar}'
        f'<div class="p-body">{eyebrow}<p class="p-name">{name}</p>'
        f"{genre}{bio}{fact}</div></{tag}>"
    )


def render_recommendations_page(recs, playlists=None, prefs=None) -> str:
    playlists = playlists or []
    prefs = prefs or dict(db.DEFAULT_PREFS)
    if not recs:
        body = (
            f"{_topbar(refresh=True, next_path='/recommendations')}<h1>Songs You Might Like</h1>"
            '<p class="empty">No recommendations yet — after you log in, the sync '
            "generates them in the background; give it a moment and refresh.</p>"
            f"{_pagenav('prev', '/artists', 'Your Top Artists')}"
        )
        return _html_page("Songs You Might Like", body, wide=True)

    cards = []
    for i, (artist, track, _score, image_url, preview_url) in enumerate(recs):
        hidden = " hidden" if i >= 5 else ""
        if image_url:
            cover = f'<img class="cover" loading="lazy" src="{html.escape(image_url)}" alt="">'
        else:
            # No cover art for this song. An empty box looks like a failed image;
            # the artist's initial reads as deliberate, matching the avatars.
            initial = html.escape(artist[:1].upper() or "?")
            cover = f'<div class="cover cover-ph">{initial}</div>'
        # preview_url is only a "this song had a preview at sync time" flag; the URL
        # itself has long since expired. Point the player at /preview, which fetches a
        # fresh signed URL from Deezer on demand.
        if preview_url:
            src = "/preview?" + urllib.parse.urlencode({"artist": artist, "track": track})
            audio = f'<audio preload="none" src="{html.escape(src)}"></audio>'
        else:
            audio = ""
        # Clicking a card opens the song on YouTube Music in a new tab. The search
        # lands on the track as the top result -- no API call, so it costs no quota.
        yt_url = "https://music.youtube.com/search?" + urllib.parse.urlencode(
            {"q": f"{artist} {track}"}
        )
        yt_label = html.escape(f"Open {artist} – {track} on YouTube Music")
        song_link = (
            f'<a class="song-link" href="{html.escape(yt_url)}" target="_blank" '
            f'rel="noopener" aria-label="{yt_label}"></a>'
        )
        cards.append(
            f'<li class="card{hidden}">'
            f"{song_link}"
            f'<div class="cover-wrap">{cover}</div>'
            f'<div class="artist">{html.escape(artist)}</div>'
            f'<div class="track">{html.escape(track)}</div>'
            f"{audio}</li>"
        )
    more = (
        '<button id="refresh-btn" class="more-btn" type="button">'
        '<span class="refresh-ic" aria-hidden="true">&#8635;</span> Refresh</button>'
        if len(recs) > 5
        else ""
    )
    script = """
<script>
var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
cards.forEach(function(card){
  var a = card.querySelector('audio');
  if(a){ a.volume = 0.25; }
  card.addEventListener('mouseenter', function(){ if(a){ a.play().catch(function(){}); } });
  card.addEventListener('mouseleave', function(){ if(a){ a.pause(); a.currentTime = 0; } });
});
var PAGE = 5;
var pages = Math.ceil(cards.length / PAGE);
var page = 0;
function showPage(p){
  var start = p * PAGE;
  cards.forEach(function(card, i){
    var visible = i >= start && i < start + PAGE;
    card.classList.toggle('hidden', !visible);
    if(!visible){
      var a = card.querySelector('audio');
      if(a){ a.pause(); a.currentTime = 0; }
    }
  });
}
var refreshBtn = document.getElementById('refresh-btn');
if(refreshBtn){ refreshBtn.addEventListener('click', function(){
  page = (page + 1) % pages;
  showPage(page);
}); }
</script>
"""
    ft_script = """
<script>
(function(){
  var overlay=document.getElementById('ft-overlay');
  if(!overlay) return;
  var steps=Array.prototype.slice.call(overlay.querySelectorAll('.ft-step'));
  var at=0;
  function show(i){
    var cur=steps[at], nxt=steps[i];
    cur.classList.add('ft-out');
    setTimeout(function(){
      cur.hidden=true; cur.classList.remove('ft-out');
      nxt.hidden=false; nxt.classList.add('ft-in');
      setTimeout(function(){ nxt.classList.remove('ft-in'); }, 20);
      at=i;
    }, 220);
  }
  function reset(){ steps.forEach(function(s,i){ s.hidden = i!==0; }); at=0; }
  function tune(body){
    fetch('/fine-tune',{
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    }).then(function(){ window.location.href='/?next=/recommendations'; })
      .catch(function(){ window.location.href='/?next=/recommendations'; });
  }
  var gear=document.getElementById('ft-gear'), menu=document.getElementById('ft-menu');
  gear.addEventListener('click', function(e){
    e.stopPropagation();
    var open = menu.hidden;
    menu.hidden = !open;
    gear.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('click', function(){
    menu.hidden = true; gear.setAttribute('aria-expanded','false');
  });
  menu.addEventListener('click', function(e){ e.stopPropagation(); });
  var resetBtn=document.getElementById('ft-reset');
  if(resetBtn){ resetBtn.addEventListener('click', function(){
    this.disabled=true; this.textContent='Resetting\\u2026';
    tune({playlists:[], discovery:'mix', mode:'safe'});
  }); }
  document.getElementById('ft-open').addEventListener('click', function(){
    menu.hidden=true; gear.setAttribute('aria-expanded','false');
    reset(); overlay.hidden=false;
  });
  document.getElementById('ft-close').addEventListener('click', function(){
    overlay.hidden=true;
  });
  overlay.querySelectorAll('.ft-next').forEach(function(b){
    b.addEventListener('click', function(){ if(at<steps.length-1) show(at+1); });
  });
  document.getElementById('ft-submit').addEventListener('click', function(){
    var picked=[];
    overlay.querySelectorAll('input[name=playlists]:checked').forEach(function(c){
      picked.push(c.value);
    });
    function radio(n){
      var el=overlay.querySelector('input[name='+n+']:checked');
      return el ? el.value : null;
    }
    this.disabled=true; this.textContent='Tuning\\u2026';
    tune({playlists:picked, discovery:radio('discovery'), mode:radio('mode')});
  });
})();
</script>
"""
    body = (
        f"{_topbar(refresh=True, next_path='/recommendations')}<h1>Songs You Might Like</h1>"
        '<p class="sub">Hover a cover to spin it and hear a preview.</p>'
        f'<ul class="recs">{"".join(cards)}</ul>'
        f"{more}"
        f"{_pagenav('prev', '/artists', 'Your Top Artists')}"
        f"{_fine_tune_wizard(playlists, prefs)}"
        f"{script}{ft_script}"
    )
    return _html_page("Songs You Might Like", body, wide=True)


@app.get("/")
def read_root(request: Request):
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    user_id = _session_user(request, conn)
    if user_id is None:
        conn.close()
        return HTMLResponse(render_landing_page(logged_in=False))
    # A pending target is a one-shot intent (from login, or a gated page bouncing
    # here mid-sync). Consume it; without one, "/" is just the landing page, which
    # is what the Home button wants.
    explicit = request.query_params.get("next") or request.session.pop("post_sync_next", None)
    ready = db.is_sync_ready(conn, user_id)
    stats = db.get_library_stats(conn, user_id) if ready else None
    conn.close()
    if not ready:
        return HTMLResponse(render_loading_page(_safe_next(explicit)))
    if explicit:
        return RedirectResponse(_safe_next(explicit))
    return HTMLResponse(render_landing_page(logged_in=True, stats=stats))


@app.get("/artists")
def artists_page(request: Request):
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    user_id = _session_user(request, conn)
    if user_id is None:
        conn.close()
        return RedirectResponse("/login?next=/artists")
    if not db.is_sync_ready(conn, user_id):
        conn.close()
        return RedirectResponse("/?next=/artists")
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


@app.post("/refresh")
def refresh(request: Request, background_tasks: BackgroundTasks):
    """Re-sync on demand, reusing the refresh token stored at login so the user
    never sees Google's consent screen again. POST, so a stray reload or a link
    prefetcher can't kick off a sync by accident."""
    back_to = _safe_next(request.query_params.get("next"))
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    user_id = _session_user(request, conn)
    if user_id is None:
        conn.close()
        return RedirectResponse(f"/login?next={back_to}", status_code=303)
    try:
        credentials = google_oauth.credentials_from_json(db.get_user_oauth_token(conn, user_id))
    except Exception as exc:
        # Revoked/expired beyond repair: the only way back is a fresh consent.
        conn.close()
        print(f"Stored token unusable, sending user back to login: {exc}")
        request.session.pop("user_id", None)
        return RedirectResponse(f"/login?next={back_to}", status_code=303)
    # Persist the (possibly refreshed) token so the next refresh still works.
    db.update_user_oauth_token(conn, user_id, credentials.to_json())
    db.set_user_syncing(conn, user_id, True)
    conn.commit()
    conn.close()
    youtube = youtube_client.build_youtube_client(credentials)
    background_tasks.add_task(
        sync.run_sync, DB_PATH, user_id, youtube,
        lastfm_api_key=os.environ.get("LASTFM_API_KEY"),
    )
    return RedirectResponse(f"/?next={back_to}", status_code=303)


@app.post("/fine-tune")
async def fine_tune(request: Request, background_tasks: BackgroundTasks):
    """Store the wizard's answers and rebuild recommendations from them.

    JSON rather than a form post: FastAPI's Form() needs python-multipart, and the
    wizard already requires JavaScript for its step transitions.
    """
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    user_id = _session_user(request, conn)
    if user_id is None:
        conn.close()
        return Response(status_code=401)
    payload = await request.json()
    # Clamp everything: only the user's own playlists, only known option values.
    own = {p["playlist_id"] for p in db.get_seedable_playlists(conn, user_id)}
    asked = payload.get("playlists") or []
    prefs = {
        "playlists": [p for p in asked if p in own],
        "discovery": payload.get("discovery")
        if payload.get("discovery") in recommendations.KNOWN_ARTIST_WEIGHTS
        else db.DEFAULT_PREFS["discovery"],
        "mode": payload.get("mode")
        if payload.get("mode") in ("safe", "adventurous")
        else db.DEFAULT_PREFS["mode"],
    }
    db.set_user_prefs(conn, user_id, prefs)
    db.set_user_syncing(conn, user_id, True)
    conn.commit()
    conn.close()
    background_tasks.add_task(
        sync.rerank, DB_PATH, user_id, lastfm_api_key=os.environ.get("LASTFM_API_KEY")
    )
    return {"ok": True}


@app.get("/status")
def status(request: Request):
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    user_id = _session_user(request, conn)
    if user_id is None:
        conn.close()
        return {"ready": False}
    ready = db.is_sync_ready(conn, user_id)
    conn.close()
    return {"ready": ready}


@app.get("/recommendations")
def recommendations_page(request: Request):
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    user_id = _session_user(request, conn)
    if user_id is None:
        conn.close()
        return RedirectResponse("/login?next=/recommendations")
    if not db.is_sync_ready(conn, user_id):
        conn.close()
        return RedirectResponse("/?next=/recommendations")
    recs = db.get_recommendations(conn, user_id)
    playlists = db.get_seedable_playlists(conn, user_id)
    prefs = db.get_user_prefs(conn, user_id)
    conn.close()
    return HTMLResponse(render_recommendations_page(recs, playlists, prefs))


def _build_flow(code_verifier: str | None = None):
    return google_oauth.build_flow(
        os.environ["GOOGLE_WEB_CLIENT_ID"],
        os.environ["GOOGLE_WEB_CLIENT_SECRET"],
        REDIRECT_URI,
        code_verifier=code_verifier,
    )


@app.get("/login")
def login(request: Request):
    request.session["post_sync_next"] = _safe_next(request.query_params.get("next"))
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
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    db.set_user_syncing(conn, user_id, True)
    conn.commit()
    conn.close()
    background_tasks.add_task(
        sync.run_sync, DB_PATH, user_id, youtube,
        lastfm_api_key=os.environ.get("LASTFM_API_KEY"),
    )

    return RedirectResponse("/")
