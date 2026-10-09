"""Public pages: privacy policy, terms of use, account deletion and open-source notices.

Google Play needs a privacy policy URL and a web page that explains how to delete an account; these are served
from the API host so they are always online with the app. The support address comes from SUPPORT_EMAIL.
"""

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(tags=["legal"], include_in_schema=False)

UPDATED = "4 October 2026"

_CSS = """
:root{--bg:#FBF6EC;--card:#FFFFFF;--ink:#2A2118;--ink2:#5E5244;--pri:#2F6B4F;--line:#E8DFCF}
@media (prefers-color-scheme:dark){:root{--bg:#14110C;--card:#1E1A14;--ink:#F3EBDD;--ink2:#B9AE9B;--pri:#8CC7A6;--line:#3A3226}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 18px 56px}h1{font-size:28px;line-height:1.25;margin:8px 0 4px}
h2{font-size:19px;margin:28px 0 6px}p,li{color:var(--ink2)}a{color:var(--pri)}.meta{font-size:14px;color:var(--ink2)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 18px;margin:14px 0}
nav a{margin-right:14px;font-weight:600;text-decoration:none}ol,ul{padding-left:22px}
"""


def _page(title: str, body: str) -> HTMLResponse:
    nav = ('<nav><a href="/">PlateMile</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a>'
           '<a href="/delete-account">Delete account</a></nav>')
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{escape(title)} · PlateMile</title><style>{_CSS}</style>'
            f'</head><body><main>{nav}{body}</main></body></html>')
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


def _mail() -> str:
    e = escape(settings.support_email)
    return f'<a href="mailto:{e}">{e}</a>'


@router.get("/", response_class=HTMLResponse)
async def home():
    return _page("PlateMile", f"""
<h1>PlateMile</h1>
<p>Indian meal ideas, food logging and simple nutrition targets. General wellness guidance, not medical advice.</p>
<div class="card"><p>Questions or problems? Write to {_mail()}.</p></div>
<ul><li><a href="/privacy">Privacy policy</a></li><li><a href="/terms">Terms of use</a></li>
<li><a href="/delete-account">How to delete your account and data</a></li><li><a href="/licences">Open-source notices</a></li></ul>
""")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return _page("Privacy policy", f"""
<h1>Privacy policy</h1><p class="meta">Last updated {UPDATED}</p>
<p>This policy explains what the PlateMile app ("PlateMile", "we") collects, why, and the choices you have. PlateMile is
for adults aged 18 and over.</p>

<h2>What we collect</h2>
<ul>
<li><b>Account:</b> your Google account email address, name and a Google account identifier, received when you sign in
with Google. We never see your Google password.</li>
<li><b>Profile and goals:</b> birth year (or age), sex, height, weight, target weight, activity level, goal, food type
(for example veg, Jain or no onion/garlic), allergies and foods you dislike.</li>
<li><b>What you log:</b> meals and their nutrition estimates, water, weight, notes you add to reports, saved recipes and
meal plans.</li>
<li><b>Steps (optional):</b> if you connect Android Health Connect, PlateMile reads your daily step count only. It does
not read or write any other health data.</li>
<li><b>App use:</b> the requests you make to the coach and meal finder, your credit balance and history, and app
settings such as reminder times, units and theme.</li>
</ul>
<p>We do not collect your precise location, contacts, photos or advertising ID, and the app shows no ads.</p>

<h2>How we use it</h2>
<ul>
<li>To calculate your nutrition targets, suggest meals and plans that respect your food type and allergies, and show
your progress.</li>
<li>To keep your account secure, prevent abuse (for example, repeated sign-ups to collect welcome credits) and fix
problems.</li>
<li>To answer you when you contact support.</li>
</ul>
<p>Meal suggestions are generated on our own server from a curated recipe set. We do not send your personal or health
data to third-party AI services, and we never use your data for advertising.</p>

<h2>Health Connect data</h2>
<p>Step counts read from Health Connect are used only to show your steps and progress inside PlateMile. They are not
shared with anyone, not used for advertising or credit decisions, and not sold. You can disconnect at any time in
PlateMile (Me, then Health Connect) or in the Health Connect app. PlateMile's use of information received from Health
Connect follows the Health Connect Permissions policy, including its Limited Use requirements.</p>

<h2>Sharing</h2>
<p>We do not sell or rent your data. We share it only with service providers that run PlateMile for us, under contract
and only for that purpose: our cloud hosting provider (servers) and our managed database provider (storage), and Google
for sign-in. We may disclose data if the law requires it.</p>

<h2>Storage and security</h2>
<p>Data is sent over encrypted connections (HTTPS) and stored in a managed database with access controls. On your phone,
your sign-in token is kept in the device's secure storage. Our providers may store data on servers outside India.</p>

<h2>How long we keep it</h2>
<p>We keep your data while your account is open. When you delete your account, your profile, logs, plans, saved meals,
settings and credit history are deleted from our database straight away. Encrypted backups kept by our database
provider are overwritten within about 30 days. We keep only a one-way, salted code made from your Google account
identifier, with no name, email or health data, so the welcome credits cannot be claimed again by re-registering.</p>

<h2>Your choices and rights</h2>
<ul>
<li><b>See and copy your data:</b> Me, then Privacy and data, then Export my data.</li>
<li><b>Correct it:</b> edit your profile, targets and logs in the app.</li>
<li><b>Delete it:</b> Me, then Privacy and data, then Delete my account, or follow <a href="/delete-account">these
steps</a>.</li>
<li><b>Withdraw consent:</b> you can stop using health features or delete your account at any time.</li>
</ul>
<p>You also have the rights given by India's Digital Personal Data Protection Act, 2023 and other applicable laws. For
questions, requests or complaints (our grievance contact), write to {_mail()}. We aim to reply within 7 days.</p>

<h2>Children</h2>
<p>PlateMile is not meant for anyone under 18 and we do not knowingly collect their data. If you think a child has
signed up, write to us and we will delete the account.</p>

<h2>Changes</h2>
<p>If we change this policy we will update the date above and, for important changes, tell you in the app.</p>
""")


@router.get("/terms", response_class=HTMLResponse)
async def terms():
    return _page("Terms of use", f"""
<h1>Terms of use</h1><p class="meta">Last updated {UPDATED}</p>
<p>By using PlateMile you agree to these terms. If you do not agree, please do not use the app.</p>
<h2>Wellness, not medical advice</h2>
<p>PlateMile gives general nutrition and wellness information. It is not medical advice, diagnosis or treatment, and it
does not replace a doctor or registered dietitian. Calories and nutrients are estimates and can differ from your actual
food. Talk to a doctor before big changes to your diet, especially if you are pregnant, have a health condition or take
medicines. Always check ingredients yourself if you have a food allergy.</p>
<h2>Who can use PlateMile</h2>
<p>You must be 18 or older and sign in with your own Google account. Keep your phone and account secure.</p>
<h2>Credits</h2>
<p>Some features use credits. New accounts get free welcome credits. Credits have no cash value, cannot be transferred
and may be returned automatically when a request fails. If paid credits are offered, prices are shown before you buy and
payments are handled by Google Play under its terms.</p>
<h2>Fair use</h2>
<p>Do not misuse PlateMile: no attempts to break, overload or reverse-engineer the service, and no automated scraping.
We may limit or close accounts that do.</p>
<h2>Your content</h2>
<p>You own the data you enter. You let us store and process it only to provide PlateMile to you, as described in the
<a href="/privacy">privacy policy</a>.</p>
<h2>Service</h2>
<p>We work to keep PlateMile available and accurate but provide it "as is", without guarantees. To the extent the law
allows, we are not liable for indirect losses arising from use of the app. We may change or stop features, and will
update these terms when we do.</p>
<h2>Law</h2>
<p>These terms are governed by the laws of India. Contact: {_mail()}.</p>
""")


@router.get("/delete-account", response_class=HTMLResponse)
async def delete_account_page():
    return _page("Delete your account", f"""
<h1>Delete your PlateMile account</h1>
<p>You can delete your account and all its data at any time.</p>
<div class="card"><h2>In the app</h2><ol>
<li>Open PlateMile and go to <b>Me</b>.</li><li>Tap <b>Privacy and data</b>.</li>
<li>Tap <b>Delete my account</b> and confirm.</li></ol>
<p>Your account is deleted immediately.</p></div>
<div class="card"><h2>Without the app</h2>
<p>Email {_mail()} from the Google account you signed in with, with the subject "Delete my account". We will delete it
within 7 days and confirm by email.</p></div>
<h2>What is deleted</h2>
<p>Your profile, goals, food, water, weight and step logs, meal plans, saved recipes, reports, settings, coach requests
and credit history. Database backups are overwritten within about 30 days.</p>
<h2>What is kept</h2>
<p>Only a one-way, salted code made from your Google account identifier (no name, email or health data), so welcome
credits cannot be claimed again by signing up repeatedly. Unused credits are lost when the account is deleted.</p>
""")


@router.get("/licences", response_class=HTMLResponse)
async def licences():
    items = [
        ("React Native, React", "MIT"), ("Expo SDK and Expo modules", "MIT"), ("expo-router", "MIT"),
        ("React Native Reanimated, Gesture Handler, Screens, Safe Area Context, SVG", "MIT"),
        ("Zustand", "MIT"), ("TanStack Query", "MIT"), ("date-fns", "MIT"), ("Zod", "MIT"),
        ("React Native Google Sign-In", "MIT"), ("react-native-health-connect", "MIT"),
        ("Gorhom Bottom Sheet", "MIT"), ("Shopify React Native Skia", "MIT"),
        ("Mukta and Young Serif fonts", "SIL Open Font License 1.1"),
        ("FastAPI, Starlette, Pydantic", "MIT"), ("SQLAlchemy, Alembic", "MIT"), ("asyncpg", "Apache 2.0"),
        ("Uvicorn", "BSD 3-Clause"),
    ]
    rows = "".join(f"<li>{escape(n)}: {escape(lic)}</li>" for n, lic in items)
    return _page("Open-source notices", f"""
<h1>Open-source notices</h1>
<p>PlateMile is built with these open-source projects. Thank you to their authors.</p><ul>{rows}</ul>
<p>Each project is used under its licence; full texts are available from the projects' repositories.</p>
""")
