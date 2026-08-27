"""
Streamlit frontend for the Resume Screening Classifier — "Aurora" premium UI.

Design language: light glassmorphism over an animated aurora-gradient
background (indigo → violet → fuchsia → cyan), staggered entrance
animations, count-up KPI tiles, an animated score ring, gradient pills and
micro-interactions throughout. Explicitly NOT the generic black-and-gold
look. Pure CSS/inline-SVG + tiny sandboxed JS widgets — zero external
frontend dependencies, so it degrades gracefully offline.

Account system:
  - With the API reachable: signup/login against the backend (bcrypt +
    signed tokens); every analysis is attributed to the signed-in user and
    appears on "🗂 My History" with CSV/PDF export.
  - API unreachable: legacy env-credential login (HR_PASSWORD /
    RECRUITER_PASSWORD) and local-only scoring — no persistence.

Pages: 🔍 Screening · 📈 Analytics · 🗂 My History · 🛠 Admin (admins only).
"""

import html as _html
import json
import os
import time

import altair as alt
import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from fpdf import FPDF
from wordcloud import WordCloud

import parsing
from extractors import extract_fields
from roles import classify_role
from scoring import overlap_score

# ---------------- PAGE CONFIG (must be the FIRST Streamlit call) ----------------
st.set_page_config(
    page_title="ResumeRank · AI Resume Screening",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
POLL_INTERVAL_S = 2
POLL_TIMEOUT_S = 120

CHART_COLORS = ["#6366F1", "#8B5CF6", "#D946EF", "#22D3EE", "#34D399", "#F59E0B"]
GRADIENTS = [
    "linear-gradient(135deg,#6366F1,#8B5CF6)",
    "linear-gradient(135deg,#8B5CF6,#D946EF)",
    "linear-gradient(135deg,#06B6D4,#3B82F6)",
    "linear-gradient(135deg,#10B981,#34D399)",
    "linear-gradient(135deg,#F59E0B,#F97316)",
    "linear-gradient(135deg,#EC4899,#F43F5E)",
]

_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# =============================== AURORA THEME CSS ===============================
AURORA_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root{
  --ink:#0F172A; --muted:#64748B;
  --violet:#7C3AED; --indigo:#6366F1; --fuchsia:#D946EF; --cyan:#22D3EE;
  --grad:linear-gradient(135deg,#6366F1,#8B5CF6 45%,#D946EF);
  --card:rgba(255,255,255,.74); --card-brd:rgba(255,255,255,.85);
  --shadow:0 10px 32px rgba(49,46,129,.10);
}
*{box-sizing:border-box}
html,body,[data-testid="stAppViewContainer"]{
  font-family:'Plus Jakarta Sans','Segoe UI',system-ui,-apple-system,sans-serif !important;
  color:var(--ink);
}
h1,h2,h3,h4,[data-testid="stMarkdownContainer"] h1,[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,[data-testid="stMarkdownContainer"] h4{
  font-family:'Space Grotesk','Plus Jakarta Sans',system-ui,sans-serif !important;
  letter-spacing:-.02em; color:var(--ink);
}
.stApp{background:#EEF1F9}
[data-testid="stHeader"]{background:transparent}
[data-testid="stDecoration"], footer{display:none}
.block-container{padding-top:2.6rem;max-width:1220px}
::selection{background:rgba(139,92,246,.28)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#8B5CF6,#6366F1);border-radius:99px;border:2px solid #EEF1F9}

/* ---------- animated aurora background ---------- */
.aurora{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.aurora span{position:absolute;border-radius:50%;filter:blur(90px);opacity:.5;will-change:transform}
.aurora span:nth-child(1){width:46vw;height:46vw;left:-12vw;top:-16vh;background:#C4B5FD;animation:drift1 22s ease-in-out infinite alternate}
.aurora span:nth-child(2){width:40vw;height:40vw;right:-14vw;top:6vh;background:#A5F3FC;animation:drift2 26s ease-in-out infinite alternate}
.aurora span:nth-child(3){width:34vw;height:34vw;left:24vw;bottom:-22vh;background:#F5D0FE;animation:drift3 24s ease-in-out infinite alternate}
.aurora span:nth-child(4){width:22vw;height:22vw;right:16vw;bottom:-8vh;background:#BFDBFE;animation:drift1 28s ease-in-out infinite alternate-reverse}
@keyframes drift1{from{transform:translate(0,0) rotate(0)}to{transform:translate(9vw,7vh) rotate(40deg)}}
@keyframes drift2{from{transform:translate(0,0) scale(1)}to{transform:translate(-8vw,10vh) scale(1.15)}}
@keyframes drift3{from{transform:translate(0,0)}to{transform:translate(10vw,-8vh) scale(1.12)}}
[data-testid="stAppViewContainer"] > .main, [data-testid="stSidebar"]{position:relative;z-index:1}

/* ---------- page entrance choreography ---------- */
.main .block-container > div{animation:fadeUp .55s cubic-bezier(.21,.85,.36,1) both}
.main .block-container > div:nth-child(2){animation-delay:.06s}
.main .block-container > div:nth-child(3){animation-delay:.12s}
.main .block-container > div:nth-child(4){animation-delay:.18s}
.main .block-container > div:nth-child(5){animation-delay:.24s}
.main .block-container > div:nth-child(6){animation-delay:.30s}
.main .block-container > div:nth-child(7){animation-delay:.36s}
.main .block-container > div:nth-child(8){animation-delay:.42s}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}

/* ---------- glass cards ---------- */
div[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--card);border:1px solid var(--card-brd)!important;
  border-radius:20px!important;box-shadow:var(--shadow);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  transition:transform .25s ease,box-shadow .25s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{
  transform:translateY(-3px);box-shadow:0 16px 40px rgba(76,29,149,.16);
}
.ct{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:1.06rem;color:var(--ink);
  display:flex;align-items:center;gap:.5rem;margin:.1rem 0 .4rem}
.ct::after{content:"";flex:1;height:2px;border-radius:2px;
  background:linear-gradient(90deg,rgba(139,92,246,.45),transparent)}

/* ---------- hero ---------- */
.hero{text-align:center;padding:1.4rem 1rem 1.1rem}
.hero-eyebrow{display:inline-block;font-size:.78rem;font-weight:800;letter-spacing:.22em;
  text-transform:uppercase;color:var(--violet);background:rgba(139,92,246,.10);
  border:1px solid rgba(139,92,246,.28);padding:.34rem .9rem;border-radius:99px;margin-bottom:.7rem}
.hero-title{font-family:'Space Grotesk',sans-serif;font-size:clamp(2.1rem,4.6vw,3.4rem);
  font-weight:700;line-height:1.06;
  background:linear-gradient(90deg,#6366F1,#D946EF 35%,#06B6D4 70%,#6366F1);
  background-size:300% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
  animation:sheen 9s linear infinite}
@keyframes sheen{from{background-position:0% 0}to{background-position:300% 0}}
.hero-sub{color:var(--muted);font-size:1.03rem;max-width:640px;margin:.55rem auto .9rem}
.hero-pill{display:inline-flex;align-items:center;gap:.5rem;font-size:.82rem;font-weight:700;
  color:#334155;background:rgba(255,255,255,.72);border:1px solid rgba(255,255,255,.9);
  padding:.42rem .95rem;border-radius:99px;box-shadow:var(--shadow);backdrop-filter:blur(8px)}
.dot{width:9px;height:9px;border-radius:50%;position:relative}
.dot.on{background:#10B981}.dot.off{background:#F59E0B}
.dot::after{content:"";position:absolute;inset:-4px;border-radius:50%;
  border:2px solid currentColor;opacity:0;animation:ping 1.8s ease-out infinite}
.dot.on{color:#10B981}.dot.off{color:#F59E0B}
@keyframes ping{0%{transform:scale(.6);opacity:.8}100%{transform:scale(1.5);opacity:0}}

/* ---------- buttons ---------- */
.stButton > button, [data-testid="stFormSubmitButton"] button{
  font-family:'Plus Jakarta Sans',sans-serif;font-weight:700;letter-spacing:.01em;
  border:none!important;border-radius:14px!important;padding:.6rem 1.3rem;color:#fff!important;
  background:var(--grad)!important;background-size:160% 100%!important;
  box-shadow:0 8px 20px rgba(124,58,237,.30)!important;
  transition:all .25s cubic-bezier(.21,.85,.36,1)!important;
}
.stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover{
  transform:translateY(-2px);background-position:90% 0!important;
  box-shadow:0 14px 30px rgba(124,58,237,.42)!important;
}
.stButton > button:active{transform:translateY(0) scale(.97)}
.stButton > button:disabled{opacity:.45;box-shadow:none!important;transform:none}
.stDownloadButton > button{
  border-radius:14px!important;font-weight:700;color:#fff!important;border:none!important;
  background:linear-gradient(135deg,#06B6D4,#3B82F6)!important;
  box-shadow:0 8px 20px rgba(6,182,212,.30)!important;transition:all .25s ease!important;
}
.stDownloadButton > button:hover{transform:translateY(-2px);box-shadow:0 14px 30px rgba(6,182,212,.42)!important}

/* ---------- inputs ---------- */
.stTextArea textarea, .stTextInput input, .stNumberInput input{
  border-radius:14px!important;border:1.5px solid #E2E8F0!important;background:#fff!important;
  transition:border-color .2s,box-shadow .2s!important;
}
.stTextArea textarea:focus, .stTextInput input:focus{
  border-color:var(--violet)!important;box-shadow:0 0 0 4px rgba(124,58,237,.14)!important;
}
[data-testid="stFileUploader"] section{
  border:2px dashed #C4B5FD!important;border-radius:16px!important;background:rgba(255,255,255,.66)!important;
  transition:border-color .25s,background .25s!important;
}
[data-testid="stFileUploader"] section:hover{border-color:var(--violet)!important;background:#fff!important}
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"]{background:var(--violet)!important}

/* ---------- radios -> segmented pills ---------- */
[role="radiogroup"]{gap:.5rem}
[role="radiogroup"] label{
  border-radius:12px;padding:.42rem .95rem;transition:all .22s ease;
  border:1.5px solid transparent;cursor:pointer;
}
[role="radiogroup"] label > div:first-child{display:none}
[data-testid="stAppViewContainer"] [role="radiogroup"] label{background:rgba(255,255,255,.66);border-color:#E2E8F0;box-shadow:0 2px 8px rgba(49,46,129,.06)}
[data-testid="stAppViewContainer"] [role="radiogroup"] label:hover{transform:translateY(-1px);border-color:#C4B5FD}
[data-testid="stAppViewContainer"] [role="radiogroup"] label:has(input:checked){
  background:var(--grad);border-color:transparent;box-shadow:0 8px 18px rgba(124,58,237,.32)}
[data-testid="stAppViewContainer"] [role="radiogroup"] label:has(input:checked) p{color:#fff;font-weight:700}

/* ---------- tabs ---------- */
[data-testid="stTabs"] [data-baseweb="tab-list"]{
  background:rgba(255,255,255,.6);backdrop-filter:blur(10px);
  border-radius:14px;padding:.3rem;gap:.35rem;border:1px solid rgba(255,255,255,.85);
}
[data-testid="stTabs"] [data-baseweb="tab"]{border-radius:10px;font-weight:700;color:#475569;transition:all .2s}
[data-testid="stTabs"] [data-baseweb="tab"]:hover{color:var(--violet)}
[data-testid="stTabs"] [aria-selected="true"]{background:var(--grad)!important;color:#fff!important;
  box-shadow:0 6px 16px rgba(124,58,237,.32)}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],[data-testid="stTabs"] [data-baseweb="tab-border"]{display:none}

/* ---------- progress bar ---------- */
[data-testid="stProgressBar"] > div > div{
  background:linear-gradient(90deg,#6366F1,#D946EF,#22D3EE)!important;
  background-size:200% 100%!important;animation:barflow 1.4s linear infinite!important;border-radius:99px;
}
@keyframes barflow{from{background-position:0 0}to{background-position:200% 0}}

/* ---------- alerts / expander / dataframe ---------- */
[data-testid="stAlert"]{border-radius:14px;border:1px solid rgba(255,255,255,.8);backdrop-filter:blur(8px)}
[data-testid="stExpander"]{background:var(--card);border:1px solid var(--card-brd)!important;
  border-radius:16px!important;backdrop-filter:blur(12px);box-shadow:var(--shadow)}
[data-testid="stDataFrame"]{border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,.85);
  box-shadow:var(--shadow)}
[data-testid="stMetric"]{background:var(--card);border:1px solid var(--card-brd);border-radius:16px;
  padding:.9rem 1.1rem;box-shadow:var(--shadow);transition:transform .25s}
[data-testid="stMetric"]:hover{transform:translateY(-3px)}
[data-testid="stMetricValue"]{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}

/* ---------- custom step chips / footer / rankings table ---------- */
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:.4rem 0 .2rem}
.step{background:var(--card);border:1px solid var(--card-brd);border-radius:16px;padding:.85rem 1rem;
  box-shadow:var(--shadow);display:flex;gap:.7rem;align-items:center;backdrop-filter:blur(10px);
  transition:transform .25s,box-shadow .25s}
.step:hover{transform:translateY(-3px);box-shadow:0 14px 32px rgba(76,29,149,.16)}
.step .n{width:34px;height:34px;flex:0 0 34px;border-radius:11px;display:flex;align-items:center;justify-content:center;
  font-size:1rem;background:var(--grad);color:#fff;box-shadow:0 6px 14px rgba(124,58,237,.28)}
.step b{font-size:.92rem}.step small{display:block;color:var(--muted);font-size:.76rem;font-weight:600}

.rtable{width:100%;border-collapse:separate;border-spacing:0 8px;font-size:.92rem}
.rtable th{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
  text-align:left;padding:.2rem .9rem}
.rtable td{background:rgba(255,255,255,.8);padding:.72rem .9rem;vertical-align:middle}
.rtable tbody tr{transition:transform .2s}
.rtable tbody tr:hover{transform:scale(1.01)}
.rtable tbody tr td:first-child{border-radius:14px 0 0 14px}
.rtable tbody tr td:last-child{border-radius:0 14px 14px 0}
.rtable tbody tr{box-shadow:0 4px 14px rgba(49,46,129,.07)}
.medal{font-weight:800;white-space:nowrap}
.scorebar{position:relative;width:150px;height:9px;background:#E2E8F0;border-radius:99px;overflow:hidden;display:inline-block;margin-right:.5rem}
.scorebar i{position:absolute;inset:0;border-radius:99px;transform-origin:left;
  animation:grow .9s cubic-bezier(.21,.85,.36,1) both}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.rolepill{display:inline-block;font-size:.76rem;font-weight:700;color:var(--violet);
  background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.3);border-radius:99px;padding:.18rem .7rem;white-space:nowrap}
.srcpill{display:inline-block;font-size:.72rem;font-weight:800;border-radius:99px;padding:.18rem .7rem;text-transform:uppercase;letter-spacing:.06em}
.src-api{background:rgba(16,185,129,.14);color:#059669;border:1px solid rgba(16,185,129,.35)}
.src-cached{background:rgba(245,158,11,.14);color:#B45309;border:1px solid rgba(245,158,11,.4)}
.src-local{background:rgba(100,116,139,.12);color:#475569;border:1px solid rgba(100,116,139,.3)}

.grad-divider{height:3px;border:none;border-radius:99px;margin:1.6rem 0 .8rem;
  background:linear-gradient(90deg,transparent,#8B5CF6 25%,#D946EF 60%,#22D3EE 85%,transparent)}
.footer{text-align:center;color:var(--muted);font-size:.84rem;font-weight:600;padding-bottom:1.4rem}
.footer b{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}

/* ---------- sidebar: deep-space indigo ---------- */
[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#150F38 0%,#22195C 52%,#2E2574 100%)!important;
}
[data-testid="stSidebar"] *{color:#E5E7FF}
[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.14)}
[data-testid="stSidebar"] .stMarkdown p,[data-testid="stSidebar"] .stMarkdown li{color:#C7CBF5}
.brand{display:flex;align-items:center;gap:.8rem;padding:.2rem .2rem 1rem}
.brand .logo{width:46px;height:46px;flex:0 0 46px;border-radius:14px;display:flex;align-items:center;
  justify-content:center;font-size:1.45rem;background:var(--grad);
  box-shadow:0 8px 22px rgba(217,70,239,.45);animation:bob 4.5s ease-in-out infinite}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
.brand .bname{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:1.22rem;color:#fff;letter-spacing:-.01em}
.brand .bsub{font-size:.72rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#A5B4FC}
.userchip{display:flex;align-items:center;gap:.6rem;background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:.55rem .8rem;backdrop-filter:blur(6px)}
.userchip .ava{width:34px;height:34px;flex:0 0 34px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-weight:800;color:#fff;background:linear-gradient(135deg,#22D3EE,#8B5CF6)}
.userchip .un{font-weight:800;color:#fff;font-size:.92rem;line-height:1.1}
.userchip .ur{font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#A5B4FC}
.adminbadge{display:inline-block;margin-left:.4rem;font-size:.6rem;font-weight:800;letter-spacing:.1em;
  background:linear-gradient(135deg,#F59E0B,#EC4899);color:#fff;border-radius:99px;padding:.1rem .5rem;vertical-align:middle}
[data-testid="stSidebar"] [role="radiogroup"]{flex-direction:column;gap:.35rem}
[data-testid="stSidebar"] [role="radiogroup"] label{
  padding:.55rem .9rem;border-radius:12px;background:transparent;border:1.5px solid transparent;
  transition:all .22s ease}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:rgba(255,255,255,.09);transform:translateX(5px)}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:linear-gradient(120deg,rgba(139,92,246,.85),rgba(217,70,239,.85));
  box-shadow:0 8px 20px rgba(139,92,246,.4);border-color:rgba(255,255,255,.2)}
[data-testid="stSidebar"] [role="radiogroup"] label p{color:#E5E7FF;font-weight:600}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{color:#fff;font-weight:800}
.side-status{display:flex;align-items:center;gap:.55rem;font-size:.8rem;font-weight:700;
  background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:.5rem .8rem}
[data-testid="stSidebar"] .stButton > button{background:rgba(255,255,255,.10)!important;
  border:1px solid rgba(255,255,255,.22)!important;box-shadow:none!important}
[data-testid="stSidebar"] .stButton > button:hover{background:rgba(244,63,94,.75)!important;box-shadow:0 8px 20px rgba(244,63,94,.35)!important}

@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
"""


# =============================== UI HELPERS ===============================
def inject_css() -> None:
    """Global Aurora stylesheet + animated background (idempotent per rerun)."""
    st.markdown(f"<style>{AURORA_CSS}</style>", unsafe_allow_html=True)
    st.markdown('<div class="aurora"><span></span><span></span><span></span><span></span></div>',
                unsafe_allow_html=True)


def hero(eyebrow: str, title: str, subtitle: str, api_ok: bool) -> None:
    status = "⚡ AI pipeline online" if api_ok else "🟠 Local mode — API offline"
    dot = "on" if api_ok else "off"
    st.markdown(
        f"""<div class="hero">
  <div class="hero-eyebrow">{eyebrow}</div>
  <div class="hero-title">{title}</div>
  <div class="hero-sub">{subtitle}</div>
  <div class="hero-pill"><span class="dot {dot}"></span>{status}</div>
</div>""",
        unsafe_allow_html=True,
    )


def card_title(text: str) -> None:
    st.markdown(f'<div class="ct">{text}</div>', unsafe_allow_html=True)


def grad_divider() -> None:
    st.markdown('<hr class="grad-divider">', unsafe_allow_html=True)


def footer() -> None:
    grad_divider()
    st.markdown(
        '<div class="footer">Built with 💜 in Lagos, Nigeria · <b>3MTT Nextgen Capstone</b> · '
        'Fellow ID FE/26/5786051575 · FastAPI ⚡ Celery 🧵 Postgres 🐘 Streamlit 🎈</div>',
        unsafe_allow_html=True,
    )


_KPI_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0}
body{font-family:'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif;background:transparent}
.wrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{position:relative;padding:14px 16px 12px;border-radius:18px;background:rgba(255,255,255,.82);
 border:1px solid rgba(255,255,255,.95);box-shadow:0 8px 24px rgba(49,46,129,.10);
 overflow:hidden;animation:pop .6s cubic-bezier(.21,.85,.36,1) both;animation-delay:var(--d);
 transition:transform .25s,box-shadow .25s}
.tile:hover{transform:translateY(-4px);box-shadow:0 16px 36px rgba(124,58,237,.20)}
.tile::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;background:var(--g)}
.ico{width:34px;height:34px;border-radius:11px;display:flex;align-items:center;justify-content:center;
 font-size:17px;background:var(--g);box-shadow:0 6px 14px rgba(124,58,237,.28);margin-bottom:8px}
.val{font-size:29px;font-weight:800;letter-spacing:-.5px;background:var(--g);
 -webkit-background-clip:text;background-clip:text;color:transparent;font-variant-numeric:tabular-nums;line-height:1.05}
.lbl{font-size:11px;font-weight:700;color:#64748B;text-transform:uppercase;letter-spacing:.09em;margin-top:3px}
@keyframes pop{from{opacity:0;transform:translateY(16px) scale(.95)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="wrap" id="wrap"></div>
<script>
const items = __DATA__;
const wrap = document.getElementById('wrap');
const easeOut = t => 1 - Math.pow(1 - t, 3);
items.forEach((it, i) => {
  const t = document.createElement('div');
  t.className = 'tile';
  t.style.setProperty('--d', (i * 0.09) + 's');
  t.style.setProperty('--g', it.g);
  t.innerHTML = `<div class="ico">${it.icon}</div><div class="val"></div><div class="lbl">${it.label}</div>`;
  wrap.appendChild(t);
  const el = t.querySelector('.val');
  if (it.animate !== null && it.animate !== undefined) {
    const dur = 1300, start = performance.now();
    const tick = now => {
      const p = Math.min(1, (now - start) / dur);
      el.textContent = (it.animate * easeOut(p)).toFixed(it.dec || 0) + (it.suffix || '');
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  } else { el.textContent = String(it.text ?? '—'); }
});
</script></body></html>"""


def kpi_strip(items: list[dict], height: int = 132) -> None:
    """Animated count-up KPI tiles. item: {icon,label,animate|text,suffix,dec,g}"""
    safe = []
    for i, it in enumerate(items):
        it = dict(it)
        it.setdefault("g", GRADIENTS[i % len(GRADIENTS)])
        safe.append(it)
    components.html(_KPI_TEMPLATE.replace("__DATA__", json.dumps(safe)),
                    height=height, scrolling=False)


_RING_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0}
body{font-family:'Plus Jakarta Sans','Segoe UI',system-ui,sans-serif;background:transparent;color:#0F172A}
.panel{background:rgba(255,255,255,.84);border:1px solid rgba(255,255,255,.95);border-radius:22px;
 box-shadow:0 12px 34px rgba(49,46,129,.12);padding:22px 26px;animation:pop .7s cubic-bezier(.21,.85,.36,1) both}
.row{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.ringwrap{position:relative;width:172px;height:172px;flex:0 0 172px}
svg{transform:rotate(-90deg)}
.track{fill:none;stroke:#E8EBF6;stroke-width:14}
.prog{fill:none;stroke:url(#rg);stroke-width:14;stroke-linecap:round;
 stroke-dasharray:439.8;stroke-dashoffset:439.8;transition:stroke-dashoffset 1.5s cubic-bezier(.21,.85,.36,1)}
.mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.mid .n{font-size:42px;font-weight:800;background:__G__;-webkit-background-clip:text;background-clip:text;color:transparent;font-variant-numeric:tabular-nums}
.mid .p{font-size:12px;font-weight:700;color:#64748B;text-transform:uppercase;letter-spacing:.12em}
.info{flex:1;min-width:260px}
.cname{font-family:'Space Grotesk',sans-serif;font-size:1.3rem;font-weight:700;margin-bottom:6px}
.role{display:inline-block;font-size:.82rem;font-weight:700;color:#7C3AED;background:rgba(139,92,246,.12);
 border:1px solid rgba(139,92,246,.35);border-radius:99px;padding:.28rem .9rem;margin:2px 6px 10px 0}
.flag{display:inline-block;font-size:.74rem;font-weight:800;border-radius:99px;padding:.24rem .8rem;text-transform:uppercase;letter-spacing:.07em}
.f-dup{background:rgba(245,158,11,.14);color:#B45309;border:1px solid rgba(245,158,11,.4)}
.f-live{background:rgba(16,185,129,.14);color:#059669;border:1px solid rgba(16,185,129,.35)}
.kw{max-width:100%;margin-top:4px}
.chip{display:inline-block;font-size:.76rem;font-weight:600;color:#334155;background:rgba(99,102,241,.09);
 border:1px solid rgba(99,102,241,.22);border-radius:99px;padding:.16rem .7rem;margin:0 6px 6px 0;
 animation:pop .5s both}
.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-top:16px}
.fld{background:rgba(238,241,249,.7);border:1px solid rgba(226,232,240,.9);border-radius:14px;padding:9px 13px}
.fld .k{font-size:10px;font-weight:800;color:#64748B;text-transform:uppercase;letter-spacing:.1em}
.fld .v{font-size:.9rem;font-weight:700;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@keyframes pop{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<div class="panel">
  <div class="row">
    <div class="ringwrap">
      <svg width="172" height="172"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="__C1__"/><stop offset="100%" stop-color="__C2__"/></linearGradient></defs>
        <circle class="track" cx="86" cy="86" r="70"></circle>
        <circle class="prog" id="prog" cx="86" cy="86" r="70"></circle></svg>
      <div class="mid"><div class="n" id="num">0%</div><div class="p">JD match</div></div>
    </div>
    <div class="info">
      <div class="cname" id="cname"></div>
      <span class="role" id="role"></span><span class="flag" id="flag"></span>
      <div class="kw" id="kw"></div>
    </div>
  </div>
  <div class="fields" id="fields"></div>
</div>
<script>
const d = __DATA__;
const C = 439.8, p = Math.max(0, Math.min(100, d.score)) / 100;
requestAnimationFrame(() => requestAnimationFrame(() => {
  document.getElementById('prog').style.strokeDashoffset = (C * (1 - p)).toFixed(1);
}));
const easeOut = t => 1 - Math.pow(1 - t, 3), start = performance.now();
const tick = now => {
  const q = Math.min(1, (now - start) / 1400);
  document.getElementById('num').textContent = (d.score * easeOut(q)).toFixed(0) + '%';
  if (q < 1) requestAnimationFrame(tick);
};
requestAnimationFrame(tick);
document.getElementById('cname').textContent = d.candidate;
document.getElementById('role').textContent = '🧠 ' + (d.role || '—');
const fl = document.getElementById('flag');
if (d.duplicate) { fl.className = 'flag f-dup'; fl.textContent = '♻ smart cache hit'; }
else { fl.className = 'flag f-live'; fl.textContent = '⚡ analyzed via ' + d.source; }
const kw = document.getElementById('kw');
d.keywords.slice(0, 12).forEach((k, i) => {
  const c = document.createElement('span'); c.className = 'chip';
  c.style.animationDelay = (0.5 + i * 0.06) + 's'; c.textContent = k; kw.appendChild(c);
});
const F = d.fields || {};
const rows = [
  ['👤 Name', F.name], ['✉️ Email', F.email], ['📞 Phone', F.phone],
  ['⏳ Experience', F.experience_years ? F.experience_years + ' yrs' : null],
  ['🎓 Education', (F.education || []).join(', ')], ['🏢 Organizations', (F.organizations || []).join(', ')],
];
const fs = document.getElementById('fields');
rows.forEach(([k, v]) => {
  const e = document.createElement('div'); e.className = 'fld';
  e.innerHTML = `<div class="k">${k}</div><div class="v"></div>`;
  e.querySelector('.v').textContent = v || '—';
  fs.appendChild(e);
});
</script></body></html>"""


def _score_gradient(score: float) -> tuple[str, str, str]:
    if score >= 75:
        return "#10B981", "#22D3EE", "linear-gradient(135deg,#10B981,#22D3EE)"
    if score >= 50:
        return "#6366F1", "#D946EF", "linear-gradient(135deg,#6366F1,#D946EF)"
    return "#F59E0B", "#F43F5E", "linear-gradient(135deg,#F59E0B,#F43F5E)"


def score_ring_panel(candidate: str, score: float, role: str, keywords: list[str],
                     fields: dict, duplicate: bool, source: str) -> None:
    c1, c2, css_grad = _score_gradient(score)
    html_doc = (_RING_TEMPLATE
                .replace("__DATA__", json.dumps({
                    "score": float(score), "candidate": candidate, "role": role,
                    "keywords": list(keywords)[:12], "fields": fields or {},
                    "duplicate": bool(duplicate), "source": source}))
                .replace("__C1__", c1).replace("__C2__", c2).replace("__G__", css_grad))
    components.html(html_doc, height=460, scrolling=False)


def _rankings_html(df_sorted: pd.DataFrame) -> str:
    rows = []
    for i, r in df_sorted.iterrows():
        medal = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"#{i + 1}")
        score = float(r["Score"])
        c1, c2, _g = _score_gradient(score)
        src = str(r.get("Source", "local"))
        src_cls = "src-cached" if "cached" in src else ("src-api" if src == "api" else "src-local")
        kws = _html.escape(str(r.get("Matched Keywords", ""))[:70]) or "—"
        rows.append(
            f'<tr><td class="medal">{medal}</td>'
            f'<td><b>{_html.escape(str(r["Candidate"]))}</b></td>'
            f'<td><span class="scorebar"><i style="width:{score:.0f}%;background:linear-gradient(90deg,{c1},{c2})"></i></span>'
            f'<b>{score:.0f}%</b></td>'
            f'<td><span class="rolepill">{_html.escape(str(r.get("Role") or "—"))}</span></td>'
            f'<td style="color:#64748B;font-size:.82rem">{kws}</td>'
            f'<td><span class="srcpill {src_cls}">{_html.escape(src)}</span></td></tr>'
        )
    return (
        '<table class="rtable"><thead><tr><th>Rank</th><th>Candidate</th><th>Match score</th>'
        '<th>Predicted role</th><th>Matched keywords</th><th>Source</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _chart_style(chart: alt.Chart) -> alt.Chart:
    return (chart
            .configure_view(strokeWidth=0)
            .configure_axis(gridColor="#E2E8F0", domain=False, tickSize=0,
                            labelColor="#64748B", labelFontWeight=600, titleColor="#475569")
            .configure_legend(labelColor="#475569"))


# ---------------- ACCOUNT LAYER ----------------
def api_available() -> bool:
    try:
        return requests.get(f"{API_URL}/health", timeout=3).ok
    except requests.RequestException:
        return False


USING_API = api_available()

inject_css()

for key, default in (("token", None), ("username", None), ("is_admin", False),
                     ("screen", None), ("_flash", None)):
    if key not in st.session_state:
        st.session_state[key] = default


def api_headers() -> dict:
    return {"X-User-Token": st.session_state.token} if st.session_state.token else {}


def _flash(message: str, icon: str = "✨") -> None:
    st.session_state._flash = (message, icon)


def _do_login(username: str, password: str) -> str | None:
    try:
        resp = requests.post(
            f"{API_URL}/auth/login",
            json={"username": username, "password": password}, timeout=15,
        )
    except requests.RequestException:
        return "API unreachable"
    if resp.ok:
        data = resp.json()
        st.session_state.token = data["token"]
        st.session_state.username = data["username"]
        st.session_state.is_admin = bool(data.get("is_admin"))
        return None
    return resp.json().get("detail", "Login failed")


def _do_signup(username: str, email: str, password: str) -> str | None:
    try:
        resp = requests.post(
            f"{API_URL}/auth/signup",
            json={"username": username, "email": email, "password": password},
            timeout=15,
        )
    except requests.RequestException:
        return "API unreachable"
    if resp.ok:
        data = resp.json()
        st.session_state.token = data["token"]
        st.session_state.username = data["username"]
        st.session_state.is_admin = bool(data.get("is_admin"))
        return None
    try:
        return resp.json().get("detail", str(resp.json()))
    except ValueError:
        return f"Signup failed ({resp.status_code})"


# ---------------- LOGIN / SIGNUP (API mode) ----------------
if USING_API and not st.session_state.token:
    hero("3MTT Nextgen Capstone · AI-Powered Hiring",
         "ResumeRank",
         "Screen resumes against any job description in seconds — semantic AI scoring, "
         "smart field extraction, role prediction and recruiter analytics in one beautiful suite.",
         api_ok=True)
    _l, mid, _r = st.columns([1, 1.9, 1])
    with mid:
        with st.container(border=True):
            card_title("🔐 Welcome back")
            tab_login, tab_signup = st.tabs(["🔑 Login", "🆕 Sign Up"])

            with tab_login:
                with st.form("login_form"):
                    li_user = st.text_input("Username")
                    li_pass = st.text_input("Password", type="password")
                    if st.form_submit_button("Login →", width="stretch"):
                        err = _do_login(li_user.strip(), li_pass)
                        if err:
                            st.error(f"❌ {err}")
                        else:
                            _flash(f"Welcome back, {st.session_state.username}! 👋", "🚀")
                            st.rerun()

            with tab_signup:
                with st.form("signup_form"):
                    su_user = st.text_input("Choose a username (min 3 chars)")
                    su_email = st.text_input("Email")
                    su_pass = st.text_input("Password (min 6 chars)", type="password")
                    su_pass2 = st.text_input("Confirm password", type="password")
                    if st.form_submit_button("Create Account ✨", width="stretch"):
                        if su_pass != su_pass2:
                            st.error("Passwords do not match")
                        else:
                            err = _do_signup(su_user.strip(), su_email.strip(), su_pass)
                            if err:
                                st.error(f"❌ {err}")
                            else:
                                _flash("Account created — welcome aboard! 🎉", "🎊")
                                st.rerun()

    _l2, mid2, _r2 = st.columns([1, 1.9, 1])
    with mid2:
        st.markdown(
            """<div class="steps">
  <div class="step"><div class="n">📄</div><div><b>Paste the job post</b><small>any JD, any role</small></div></div>
  <div class="step"><div class="n">📂</div><div><b>Drop in resumes</b><small>PDF &amp; DOCX, one or many</small></div></div>
  <div class="step"><div class="n">🏆</div><div><b>Get instant rankings</b><small>scores, roles &amp; insights</small></div></div>
</div>""",
            unsafe_allow_html=True,
        )
    footer()
    st.stop()

# ---------------- LEGACY LOGIN (API offline) ----------------
if not USING_API:
    import streamlit_authenticator as stauth

    names = ["HR Manager", "Recruiter"]
    usernames = [os.environ.get("HR_USERNAME", "hr"),
                 os.environ.get("RECRUITER_USERNAME", "recruiter")]
    passwords = [os.environ.get("HR_PASSWORD", "password123"),
                 os.environ.get("RECRUITER_PASSWORD", "securepass")]
    hashed = stauth.Hasher(passwords).generate()
    authenticator = stauth.Authenticate(
        names, usernames, hashed, "resume_dashboard",
        os.environ.get("COOKIE_KEY", "abcdef"), cookie_expiry_days=30,
    )
    name, auth_status, _u = authenticator.login("Login", "main")
    if not auth_status:
        st.stop()
    st.session_state.username = name
    st.session_state.is_admin = False

# ---------------- SIDEBAR ----------------
initial = (st.session_state.username or "?")[0].upper()
badge = '<span class="adminbadge">ADMIN</span>' if st.session_state.is_admin else ""
st.sidebar.markdown(
    f"""<div class="brand"><div class="logo">🎯</div>
  <div><div class="bname">ResumeRank</div><div class="bsub">AI Screening Suite</div></div></div>
<div class="userchip"><div class="ava">{initial}</div>
  <div><div class="un">{_html.escape(str(st.session_state.username))}{badge}</div>
  <div class="ur">{"Administrator" if st.session_state.is_admin else "Recruiter"}</div></div></div>""",
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    f'<div class="side-status"><span class="dot {"on" if USING_API else "off"}"></span>'
    f'{"API connected · " + API_URL if USING_API else "API offline — local mode"}</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown("<div style='height:.7rem'></div>", unsafe_allow_html=True)

nav_options = ["🔍 Screening", "📈 Analytics"]
if st.session_state.token:
    nav_options.append("🗂 My History")
if st.session_state.token and st.session_state.is_admin:
    nav_options.append("🛠 Admin")
page = st.sidebar.radio("Navigate", nav_options, label_visibility="collapsed")

if st.session_state.token and st.sidebar.button("🚪 Log out", width="stretch"):
    st.session_state.token = None
    st.session_state.username = None
    st.session_state.is_admin = False
    st.session_state.screen = None
    st.rerun()

st.sidebar.markdown(
    "<div style='margin-top:1.2rem;font-size:.7rem;font-weight:700;letter-spacing:.1em;"
    "text-transform:uppercase;color:#818CF8'>FE/26/5786051575 · Lagos 🇳🇬</div>",
    unsafe_allow_html=True,
)

# flash toast queued before a rerun
if st.session_state._flash:
    msg, icon = st.session_state._flash
    st.session_state._flash = None
    st.toast(msg, icon=icon)

# ---------------- EXPORT HELPERS ----------------
def export_pdf(df, title="Resume Analysis Report") -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(200, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
    for _, row in df.iterrows():
        candidate = str(row["Candidate"]).encode("latin-1", "replace").decode("latin-1")
        role = str(row.get("Role", "")).encode("latin-1", "replace").decode("latin-1")
        badge_txt = str(row.get("Badge", "")).encode("latin-1", "replace").decode("latin-1")
        line = f"{candidate} - {row['Score']}%"
        if badge_txt:
            line += f" - {badge_txt}"
        if role:
            line += f" - {role}"
        pdf.cell(200, 10, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def download_exports(df, stem: str):
    c1, c2 = st.columns(2)
    with c1:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download CSV", csv, f"{stem}.csv", "text/csv",
                           width="stretch")
    with c2:
        pdf_bytes = export_pdf(df)
        st.download_button("📥 Download PDF", pdf_bytes, f"{stem}.pdf", "application/pdf",
                           width="stretch")


# =============================== ADMIN PAGE ===============================
if page == "🛠 Admin":
    hero("Mission Control", "Admin Dashboard",
         "Every user, every analysis, every trend — monitored live from the API.",
         api_ok=True)
    try:
        overview = requests.get(f"{API_URL}/admin/overview", headers=api_headers(), timeout=15)
        users_resp = requests.get(f"{API_URL}/admin/users", headers=api_headers(), timeout=15)
        trends = requests.get(f"{API_URL}/admin/trends?days=30", headers=api_headers(), timeout=15)
    except requests.RequestException as exc:
        st.error(f"Admin API unreachable: {exc}")
        st.stop()
    if overview.status_code in (401, 403):
        st.error("Admin access required.")
        st.stop()

    ov = overview.json()
    kpi_strip([
        {"icon": "👥", "label": "Users", "animate": ov["total_users"]},
        {"icon": "🧾", "label": "Jobs", "animate": ov["total_jobs"]},
        {"icon": "✅", "label": "Completed", "animate": ov["by_status"].get("completed", 0)},
        {"icon": "❌", "label": "Failed", "animate": ov["by_status"].get("failed", 0)},
        {"icon": "🗓", "label": "Jobs (7d)", "animate": ov["jobs_last_7d"]},
        {"icon": "🎯", "label": "Avg Score",
         "animate": ov["avg_match_score"], "suffix": "%", "dec": 1},
    ])

    tr = trends.json()
    grad_divider()
    tcol1, tcol2 = st.columns(2)
    with tcol1:
        with st.container(border=True):
            card_title("📈 Jobs analyzed per day")
            if tr["jobs_per_day"]:
                jdf = pd.DataFrame({"day": list(tr["jobs_per_day"].keys()),
                                    "jobs": list(tr["jobs_per_day"].values())})
                st.altair_chart(_chart_style(
                    alt.Chart(jdf).mark_area(
                        line={"color": "#8B5CF6"},
                        color=alt.Gradient(gradient="linear", stops=[
                            alt.GradientStop(color="rgba(217,70,239,0.45)", offset=0),
                            alt.GradientStop(color="rgba(99,102,241,0.03)", offset=1)],
                            x1=1, x2=1, y1=1, y2=0),
                    ).encode(x=alt.X("day", title=None), y=alt.Y("jobs", title="Jobs"),
                             tooltip=["day", "jobs"]).properties(height=260)
                ), width="stretch")
            else:
                st.caption("No activity yet.")
    with tcol2:
        with st.container(border=True):
            card_title("🆕 New signups per day")
            if tr["signups_per_day"]:
                sdf = pd.DataFrame({"day": list(tr["signups_per_day"].keys()),
                                    "signups": list(tr["signups_per_day"].values())})
                st.altair_chart(_chart_style(
                    alt.Chart(sdf).mark_bar(cornerRadiusEnd=7, color="#22D3EE").encode(
                        x=alt.X("day", title=None), y=alt.Y("signups", title="Signups"),
                        tooltip=["day", "signups"]).properties(height=260)
                ), width="stretch")
            else:
                st.caption("No signups in window.")

    dcol1, dcol2, dcol3 = st.columns(3)
    with dcol1:
        with st.container(border=True):
            card_title("🧑‍💼 Professions")
            if tr["profession_distribution"]:
                pdf_ = pd.DataFrame({"role": list(tr["profession_distribution"].keys()),
                                     "n": list(tr["profession_distribution"].values())})
                st.altair_chart(_chart_style(
                    alt.Chart(pdf_).mark_bar(cornerRadiusEnd=7).encode(
                        x=alt.X("n", title=None), y=alt.Y("role", sort="-x", title=None),
                        color=alt.Color("role", legend=None,
                                        scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["role", "n"]).properties(height=250)
                ), width="stretch")
            else:
                st.caption("—")
    with dcol2:
        with st.container(border=True):
            card_title("🧰 Tech Stack (top skills)")
            if tr["skill_distribution"]:
                sdf2 = pd.DataFrame(tr["skill_distribution"])
                st.altair_chart(_chart_style(
                    alt.Chart(sdf2).mark_bar(cornerRadiusEnd=7).encode(
                        x=alt.X("count", title=None), y=alt.Y("skill", sort="-x", title=None),
                        color=alt.Color("skill", legend=None,
                                        scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["skill", "count"]).properties(height=250)
                ), width="stretch")
            else:
                st.caption("—")
    with dcol3:
        with st.container(border=True):
            card_title("🎯 Score Histogram")
            if tr["score_histogram"]:
                hdf2 = pd.DataFrame({"bucket": list(tr["score_histogram"].keys()),
                                     "n": list(tr["score_histogram"].values())})
                st.altair_chart(_chart_style(
                    alt.Chart(hdf2).mark_bar(cornerRadiusEnd=7, color="#D946EF").encode(
                        x=alt.X("bucket", title=None), y=alt.Y("n", title="Resumes"),
                        tooltip=["bucket", "n"]).properties(height=250)
                ), width="stretch")
            else:
                st.caption("—")

    grad_divider()
    with st.container(border=True):
        card_title("👥 Registered Users")
        ub = users_resp.json()
        users_df = pd.DataFrame(ub["users"])
        if not users_df.empty:
            users_df["joined"] = users_df["created_at"].str[:10]
            users_df["last_active"] = (users_df["last_active"].fillna("—")
                                       .str[:16].str.replace("T", " "))
            st.dataframe(
                users_df[["username", "email", "is_admin", "jobs", "completed",
                          "failed", "avg_score", "joined", "last_active"]],
                width="stretch",
            )
        else:
            st.caption("No users yet.")

    with st.container(border=True):
        card_title("🔎 Per-User Drill-Down")
        if ub["users"]:
            choice = st.selectbox(
                "Inspect user activity",
                options=ub["users"],
                format_func=lambda u: f"{u['username']} ({u['jobs']} jobs)",
            )
            if choice:
                jobs_resp = requests.get(f"{API_URL}/admin/users/{choice['id']}/jobs",
                                         headers=api_headers(), timeout=15)
                if jobs_resp.ok:
                    ujobs = jobs_resp.json()["jobs"]
                    if ujobs:
                        st.dataframe(pd.DataFrame(ujobs)[
                            ["filename", "jd_match_score", "predicted_role",
                             "status", "skills_extracted", "created_at"]],
                            width="stretch")
                    else:
                        st.caption(f"{choice['username']} has no analyses yet.")
    footer()
    st.stop()

# =============================== HISTORY PAGE ===============================
if page == "🗂 My History":
    hero("Your personal archive", "My Analysis History",
         "Every screening you've ever run — filterable, inspectable, exportable.", api_ok=True)
    try:
        resp = requests.get(f"{API_URL}/history", headers=api_headers(), timeout=15)
    except requests.RequestException as exc:
        st.error(f"Could not load history: {exc}")
        st.stop()
    if resp.status_code == 401:
        st.session_state.token = None
        st.warning("Session expired — please log in again.")
        st.rerun()

    jobs = resp.json()["jobs"]
    if not jobs:
        with st.container(border=True):
            card_title("🌱 Nothing here yet")
            st.markdown("Run a screening on the **🔍 Screening** page and it will appear here — "
                        "scored, classified and ready to export.")
        st.stop()

    hist = pd.DataFrame([
        {
            "Candidate": j["filename"],
            "Score": j["jd_match_score"],
            "Role": j["predicted_role"],
            "Skills": j["skills_extracted"],
            "Status": j["status"],
            "Date": (j["created_at"] or "")[:16].replace("T", " "),
            "job_id": j["job_id"],
            "_fields": j.get("extracted_fields"),
        }
        for j in jobs
    ])

    done = hist[hist["Status"] == "completed"]
    kpi_strip([
        {"icon": "🧾", "label": "Analyses", "animate": len(hist)},
        {"icon": "🎯", "label": "Avg Score",
         "animate": float(done["Score"].mean()) if len(done) else None,
         "text": "—", "suffix": "%", "dec": 1},
        {"icon": "🏆", "label": "Best Score",
         "animate": float(done["Score"].max()) if len(done) else None,
         "text": "—", "suffix": "%"},
    ])

    grad_divider()
    with st.container(border=True):
        card_title("🗂 All analyses")
        min_score = st.slider("Minimum score filter", 0, 100, 0)
        view = hist[(hist["Score"].fillna(0) >= min_score)]
        st.dataframe(
            view[["Candidate", "Score", "Role", "Status", "Skills", "Date"]],
            width="stretch",
        )

    with st.expander("🔍 Extracted fields (per candidate)"):
        for _, row in view.iterrows():
            f = row["_fields"] or {}
            st.write(
                f"**{row['Candidate']}** — name: {f.get('name') or '—'}, "
                f"email: {f.get('email') or '—'}, phone: {f.get('phone') or '—'}, "
                f"experience: {f.get('experience_years') or '—'}y"
            )

    with st.container(border=True):
        card_title("📤 Export my history")
        export_df = view[["Candidate", "Score", "Role", "Status", "Skills", "Date"]]
        download_exports(export_df, f"history_{st.session_state.username}")
    footer()
    st.stop()

# =============================== ANALYTICS PAGE ===============================
if page == "📈 Analytics":
    hero("Recruiter intelligence", "Analytics",
         "What the pipeline has learned across every resume it has screened.", api_ok=USING_API)
    if not USING_API:
        st.info(
            "Analytics reads from Postgres via the API — start the backend "
            f"and set API_URL (currently {API_URL}) to use this page."
        )
        st.stop()

    try:
        summary = requests.get(f"{API_URL}/analytics/summary", timeout=10).json()
    except requests.RequestException as exc:
        st.error(f"Could not load analytics: {exc}")
        st.stop()

    kpi_strip([
        {"icon": "🧾", "label": "Jobs Processed", "animate": summary["total_jobs"]},
        {"icon": "✅", "label": "Completed", "animate": summary["by_status"].get("completed", 0)},
        {"icon": "🎯", "label": "Avg Match Score",
         "animate": summary["avg_match_score"], "text": "—", "suffix": "%", "dec": 1},
        {"icon": "🏷️", "label": "Top Role", "text": next(iter(summary["role_distribution"]), "—")},
    ])

    grad_divider()
    colL, colR = st.columns(2)
    with colL:
        with st.container(border=True):
            card_title("🎯 Match Score Distribution")
            if summary["score_histogram"]:
                hist_df = pd.DataFrame(
                    {"Bucket": list(summary["score_histogram"].keys()),
                     "Resumes": list(summary["score_histogram"].values())}
                )
                st.altair_chart(_chart_style(
                    alt.Chart(hist_df).mark_bar(cornerRadiusEnd=8).encode(
                        x=alt.X("Bucket", title=None, sort=None),
                        y=alt.Y("Resumes", title="Resumes"),
                        color=alt.Color("Bucket", legend=None,
                                        scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["Bucket", "Resumes"]).properties(height=270)
                ), width="stretch")
            else:
                st.caption("No completed analyses yet.")

        with st.container(border=True):
            card_title("⚙️ Pipeline Status")
            status_df = pd.DataFrame(
                {"Status": list(summary["by_status"].keys()),
                 "Count": list(summary["by_status"].values())}
            )
            st.altair_chart(_chart_style(
                alt.Chart(status_df).mark_arc(innerRadius=62, cornerRadius=5, padAngle=0.02)
                .encode(theta="Count",
                        color=alt.Color("Status", scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["Status", "Count"]).properties(height=270)
            ), width="stretch")

    with colR:
        with st.container(border=True):
            card_title("🏷️ Role Distribution")
            if summary["role_distribution"]:
                role_df = pd.DataFrame(
                    {"Role": list(summary["role_distribution"].keys()),
                     "Resumes": list(summary["role_distribution"].values())}
                )
                st.altair_chart(_chart_style(
                    alt.Chart(role_df).mark_bar(cornerRadiusEnd=8).encode(
                        x=alt.X("Resumes", title=None),
                        y=alt.Y("Role", sort="-x", title=None),
                        color=alt.Color("Role", legend=None,
                                        scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["Role", "Resumes"]).properties(height=270)
                ), width="stretch")
            else:
                st.caption("No role predictions yet.")

        with st.container(border=True):
            card_title("🧠 Top Skills Seen")
            if summary["top_skills"]:
                skill_df = pd.DataFrame(summary["top_skills"])
                st.altair_chart(_chart_style(
                    alt.Chart(skill_df).mark_bar(cornerRadiusEnd=8).encode(
                        x=alt.X("count", title=None),
                        y=alt.Y("skill", sort="-x", title=None),
                        color=alt.Color("skill", legend=None,
                                        scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["skill", "count"]).properties(height=270)
                ), width="stretch")
            else:
                st.caption("No skills extracted yet.")

    grad_divider()
    with st.container(border=True):
        card_title("🕘 Recent Jobs")
        if summary["recent_jobs"]:
            st.dataframe(pd.DataFrame(summary["recent_jobs"]), width="stretch")
        else:
            st.caption("Nothing processed yet — run a screening first.")
    footer()
    st.stop()

# =============================== SCREENING PAGE ===============================
hero("AI-Powered Resume Screening", "Screen. Score. Hire.",
     "Paste a job description, drop in resumes, and let the pipeline rank every "
     "candidate — semantic matching, entity extraction and role prediction included.",
     api_ok=USING_API)

st.sidebar.markdown("---")
st.sidebar.markdown(
    """**📖 How it works**
1. Paste the **job description**.
2. Upload resumes — **PDF or DOCX**.
3. Pick **Single** or **Batch** mode.
4. Hit **⚡ Run AI Analysis**.
5. Scores, roles, extracted fields, rankings & exports — all saved to **🗂 My History**.
""")

st.markdown(
    """<div class="steps">
  <div class="step"><div class="n">1️⃣</div><div><b>Paste the JD</b><small>keywords &amp; skills auto-extracted</small></div></div>
  <div class="step"><div class="n">2️⃣</div><div><b>Upload resumes</b><small>PDF / DOCX · multi-file</small></div></div>
  <div class="step"><div class="n">3️⃣</div><div><b>AI ranks everyone</b><small>score · role · fields · badges</small></div></div>
</div>""",
    unsafe_allow_html=True,
)

with st.container(border=True):
    card_title("🧪 Screening setup")
    col1, col2 = st.columns(2)
    with col1:
        job_desc = st.text_area("📄 Paste the Job Description", height=190,
                                placeholder="e.g. We're looking for a Data Engineer with strong "
                                            "Python, SQL, Airflow and cloud (AWS/GCP) experience…")
    with col2:
        resumes = st.file_uploader(
            "📂 Upload Resume(s)",
            type=[ext.lstrip(".") for ext in parsing.SUPPORTED_EXTENSIONS],
            accept_multiple_files=True,
        )
    mode = st.radio("Analysis mode:", ["Single Analysis", "Batch Screening"], horizontal=True)
    ready = bool(resumes and job_desc.strip())
    run_cols = st.columns([1, 1, 4])
    with run_cols[0]:
        run_clicked = st.button("⚡ Run AI Analysis", width="stretch",
                                disabled=not ready)
    if not ready:
        st.caption("👆 Add a job description and at least one resume to enable analysis.")
    if st.session_state.screen is not None and run_cols[1].button("🧹 Clear results"):
        st.session_state.screen = None
        st.rerun()


def extract_text(file) -> str:
    file.seek(0)
    return parsing.parse_resume(file.name, file.read())


def analyze_via_api(file, jd: str):
    """Submit to FastAPI -> Celery worker, poll until done."""
    file.seek(0)
    raw = file.read()
    ext = os.path.splitext(file.name)[1].lower()
    mime = _MIME.get(ext, "application/octet-stream")

    resp = requests.post(
        f"{API_URL}/single_analyze",
        files={"resume": (file.name, raw, mime)},
        data={"jd": jd},
        headers=api_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    submitted = resp.json()

    if submitted.get("duplicate") and submitted.get("status") == "completed":
        details = requests.get(f"{API_URL}/results/{submitted['job_id']}", timeout=10)
        payload = details.json() if details.ok else submitted
        payload["duplicate"] = True
        return payload, None

    job_id = submitted["job_id"]
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        r = requests.get(f"{API_URL}/results/{job_id}", timeout=10)
        if r.ok:
            payload = r.json()
            if payload["status"] == "completed":
                return payload, None
            if payload["status"] == "failed":
                return None, "worker reported failure"
        time.sleep(POLL_INTERVAL_S)
    return None, "timed out waiting for worker"


if run_clicked and ready:
    results, all_keywords, fields_by_candidate, dup_flags = [], [], {}, {}
    progress = st.progress(0.0)
    with st.status("✨ AI pipeline working its magic…", expanded=True) as status_box:
        for i, resume in enumerate(resumes, start=1):
            st.write(f"🔎 `{resume.name}` — parsing, scoring, classifying…")
            try:
                resume_text = extract_text(resume)
            except ValueError as exc:
                st.error(f"{resume.name}: {exc}")
                continue

            score, overlap = overlap_score(resume_text, job_desc)
            fields = extract_fields(resume_text)
            role = classify_role(resume_text)
            source = "local"
            duplicate = False

            if USING_API:
                payload, err = analyze_via_api(resume, job_desc)
                if payload is not None:
                    score = payload["jd_match_score"]
                    role = payload.get("predicted_role") or role
                    fields = payload.get("extracted_fields") or fields
                    duplicate = payload.get("duplicate", False)
                    source = "api (cached)" if duplicate else "api"
                else:
                    st.warning(f"{resume.name}: pipeline unavailable ({err}); used local score.")

            results.append({
                "Candidate": resume.name,
                "Score": score,
                "Role": role,
                "Matched Keywords": ", ".join(overlap),
                "Source": source,
            })
            fields_by_candidate[resume.name] = fields
            dup_flags[resume.name] = duplicate
            all_keywords.extend(overlap)
            progress.progress(i / len(resumes))

        if not results:
            status_box.update(label="❌ No resumes could be analyzed.", state="error")
            st.stop()
        status_box.update(label="✅ Analysis complete — results ready below!",
                          state="complete", expanded=False)

    st.session_state.screen = {
        "results": results,
        "keywords": all_keywords,
        "fields": fields_by_candidate,
        "dups": dup_flags,
        "mode": mode,
        "n_files": len(resumes),
    }
    top = max(r["Score"] for r in results)
    st.toast(f"Top candidate scored {top:.0f}% 🎉" if top >= 80
             else "Analysis complete ✨", icon="🎉" if top >= 80 else "✨")
    if top >= 80:
        st.balloons()

# ---- render stored results (survives reruns from download buttons) ----
screen = st.session_state.screen
if screen:
    df = pd.DataFrame(screen["results"])
    fields_map = screen["fields"]
    dups = screen.get("dups", {})
    all_keywords = screen["keywords"]

    grad_divider()
    top_candidate = df.loc[df["Score"].idxmax()]
    kpi_strip([
        {"icon": "🧾", "label": "Resumes Analyzed", "animate": len(df)},
        {"icon": "🎯", "label": "Average Score", "animate": float(df["Score"].mean()),
         "suffix": "%", "dec": 1},
        {"icon": "🏆", "label": "Top Candidate",
         "text": f'{top_candidate["Candidate"]} · {top_candidate["Score"]:.0f}%'},
        {"icon": "♻️", "label": "Smart Cache Hits", "animate": int(sum(dups.values()))},
    ])

    if screen["mode"] == "Single Analysis" and screen["n_files"] == 1 and len(df) == 1:
        row = df.iloc[0]
        with st.container(border=True):
            card_title("📄 Candidate Analysis")
            score_ring_panel(
                candidate=row["Candidate"],
                score=float(row["Score"]),
                role=row["Role"],
                keywords=[k.strip() for k in str(row["Matched Keywords"]).split(",") if k.strip()],
                fields=fields_map.get(row["Candidate"]),
                duplicate=bool(dups.get(row["Candidate"])),
                source=row["Source"].replace(" (cached)", ""),
            )
    else:
        bcol1, bcol2 = st.columns(2)
        with bcol1:
            with st.container(border=True):
                card_title("📑 Scores by Candidate")
                st.altair_chart(_chart_style(
                    alt.Chart(df).mark_bar(cornerRadiusEnd=8).encode(
                        x=alt.X("Candidate", title=None, sort="-y"),
                        y=alt.Y("Score", title="Match %"),
                        color=alt.Color("Role", scale=alt.Scale(range=CHART_COLORS)),
                        tooltip=["Candidate", "Score", "Role"]).properties(height=300)
                ), width="stretch")
        with bcol2:
            with st.container(border=True):
                card_title("📈 Score Trend")
                st.altair_chart(_chart_style(
                    alt.Chart(df.reset_index()).mark_line(point=alt.OverlayMarkDef(size=90),
                                                          interpolate="monotone",
                                                          color="#8B5CF6", strokeWidth=3).encode(
                        x=alt.X("index", title="Resume #"),
                        y=alt.Y("Score", title="Match %"),
                        tooltip=["Candidate", "Score", "Role"]).properties(height=300)
                ), width="stretch")

    if all_keywords:
        with st.container(border=True):
            card_title("☁️ Skill & Keyword Cloud")
            wordcloud = WordCloud(
                width=1100, height=380, background_color=None, mode="RGBA",
                colormap="cool", prefer_horizontal=0.92, min_font_size=11,
            ).generate(" ".join(all_keywords))
            fig, ax = plt.subplots(figsize=(11, 3.8))
            fig.patch.set_alpha(0.0)
            ax.imshow(wordcloud, interpolation="bilinear")
            ax.axis("off")
            st.pyplot(fig)
            plt.close(fig)

    with st.container(border=True):
        card_title("🏆 Candidate Rankings")
        df_sorted = df.sort_values(by="Score", ascending=False).reset_index(drop=True)
        st.markdown(_rankings_html(df_sorted), unsafe_allow_html=True)

    with st.container(border=True):
        card_title("📤 Export Results")
        df_sorted["Badge"] = [
            {0: "Top Performer", 1: "Strong Match", 2: "Good Candidate"}.get(i, "Candidate")
            for i in range(len(df_sorted))
        ]
        download_exports(df_sorted[["Candidate", "Score", "Badge", "Role", "Matched Keywords"]],
                         "resume_analysis_results")
        if st.session_state.token:
            st.caption("💾 Saved to your account — see **🗂 My History** for all past analyses.")

footer()
