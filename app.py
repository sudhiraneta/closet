"""Closet — standalone Streamlit UI for the wardrobe manager."""

import streamlit as st
import requests

API_BASE = "http://localhost:8001/api"

st.set_page_config(page_title="Closet", page_icon="👔", layout="wide")

# Global CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

/* Base */
.stApp { background: #fff !important; }
html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif !important; color: #222 !important; }

/* Typography */
h1 { font-weight: 600 !important; font-size: 26px !important; color: #222 !important; }
h2, h3 { font-weight: 600 !important; font-size: 16px !important; color: #222 !important; }

/* Kill Streamlit chrome */
#MainMenu, footer, header, [data-testid="stDecoration"], .stDeployButton { display: none !important; }

/* Buttons — rounded pill */
.stButton > button {
    background: #fff !important; color: #222 !important;
    border: 1.5px solid #ddd !important; border-radius: 24px !important;
    font-size: 13px !important; padding: 8px 20px !important; font-weight: 500 !important;
    transition: all 0.2s;
}
.stButton > button:hover { background: #f7f7f7 !important; box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important; }

/* Tabs — pill style */
.stTabs [data-baseweb="tab-list"] { border: none !important; gap: 8px; background: transparent !important; padding-bottom: 16px; }
.stTabs [data-baseweb="tab"] {
    color: #717171 !important; font-size: 14px !important; font-weight: 500 !important;
    border: 1.5px solid #ddd !important; border-radius: 24px !important;
    padding: 6px 18px !important; background: #fff !important;
}
.stTabs [aria-selected="true"] { background: #222 !important; color: #fff !important; border-color: #222 !important; }
</style>
""", unsafe_allow_html=True)


def api_call(method: str, endpoint: str, **kwargs) -> dict | None:
    try:
        url = f"{API_BASE}{endpoint}"
        resp = getattr(requests, method)(url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to Closet API. Run: `python main.py` first.")
        return None
    except Exception as e:
        st.error(f"API error: {e}")
        return None


from wardrobe.page import render
render(api_call, API_BASE)
