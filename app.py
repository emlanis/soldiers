"""
Secret Soldiers KPI Dashboard - Submit X links with posted date fidelity and view leaderboards
"""

import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone, date, time as dtime
from dotenv import load_dotenv
from typing import List, Tuple
import time
from update_service import UpdateService

@st.cache_resource
def get_update_service():
    return UpdateService()

# Clear cache on app restart to ensure latest code is loaded
if 'service_initialized' not in st.session_state:
    st.cache_resource.clear()
    st.session_state.service_initialized = True

service = get_update_service()

st.set_page_config(
    page_title="Secret Soldiers Dashboard",
    page_icon="img/secret.png",
    layout="wide"
)

# Load environment variables for sergeant credentials
load_dotenv()

# Sidebar with logo
try:
    col1, col2, col3 = st.sidebar.columns([1, 2, 1])
    with col2:
        st.image("img/secret.png", width=80)
except:
    st.sidebar.write("🚀")

page = st.sidebar.selectbox("Navigation", [
    "✨ Submit Content", 
    "🏅 Leaderboard",
    "🛡️ Sergeant Console"
])

if page == "✨ Submit Content":
    st.title("✍️ Submit New Content")
    st.caption("Thread auto-adds +6 units to Secret's Engagement on the same posted date. If OP is a meme NOT a thread, ADD it to Secret's Engagement.")
    
    soldiers = service.get_soldiers()
    soldier_handles = [s["handle"] for s in soldiers] if soldiers else []
    soldier = st.selectbox("Soldier", soldier_handles, key="soldier_select")
    selected_profile = ""
    if soldier:
        selected_profile = next((s["profile_url"] for s in soldiers if s["handle"] == soldier), "")
    if selected_profile:
        st.markdown(f"[View {soldier}'s X profile]({selected_profile})")
    
    with st.form("content_form"):
        category = st.selectbox("Category", ["Thread/Meme", "Secret's Engagement", "Shill"])
        content_url = st.text_input("Content URL")

        default_date = datetime.now().date()
        posted_date = st.date_input("Posted date (UTC)", value=default_date)
        confirm = st.checkbox("I confirm the category and posted date are correct for this link.")

        if st.form_submit_button("Submit Content"):
            if not content_url:
                st.error("Please enter a content URL")
            elif not soldier:
                st.error("Please select a soldier")
            elif not confirm:
                st.error("Please confirm category and posted date are correct.")
            else:
                posted_at = datetime.combine(posted_date, dtime.min).replace(tzinfo=timezone.utc)
                with st.spinner("Recording content..."):
                    success, message = service.add_content(soldier, content_url, category, posted_at, use_auto_fetch=False)
                if success:
                    st.success(f"✅ {message}")
                    time.sleep(2)
                    st.balloons()
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

elif page == "🏅 Leaderboard":
    st.title("Leaderboard")

    available_months = service.get_available_months()
    current_month = datetime.now()

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        if available_months:
            month_options = []
            month_values = []
            current_option = f"{current_month.strftime('%B %Y')} (Current)"
            month_options.append(current_option)
            month_values.append((current_month.year, current_month.month))
            for year, month in available_months:
                if not (year == current_month.year and month == current_month.month):
                    month_name = datetime(year, month, 1).strftime('%B %Y')
                    month_options.append(month_name)
                    month_values.append((year, month))
            selected_index = st.selectbox("Select Month:", range(len(month_options)),
                                         format_func=lambda x: month_options[x],
                                         key="month_select_x")
            selected_year, selected_month = month_values[selected_index]
        else:
            selected_year, selected_month = current_month.year, current_month.month
            st.info("No historical data available")

    with col3:
        if st.button("🔄 Refresh", key="refresh_leaderboard"):
            st.rerun()

    with st.spinner("Loading leaderboards..."):
        data = service.get_leaderboards(selected_year, selected_month)

    def render_board(title: str, rows: List[dict], window: Tuple[date, date]):
        start, end = window
        st.subheader(f"{title} ({start} → {end})")
        if not rows:
            st.info("No data yet.")
            return
        cleaned_rows = []
        for r in rows:
            r = dict(r)
            r.pop("daily", None)
            cleaned_rows.append(r)
        # Remove any non-serializable date keys inside dicts
        df = pd.DataFrame(cleaned_rows)
        df = df.rename(columns={
            "handle": "Soldier",
            "score": "QQ Rating",
            "total_units": "Total",
            "tm": "TM",
            "se": "SE",
            "sh": "SH",
        })
        df["QQ Rating"] = df["QQ Rating"].apply(lambda x: f"{x * 100:.2f}%")
        st.dataframe(df, width="stretch", hide_index=True)

    if data:
        week_tabs = st.tabs(["Week 1", "Week 2", "Week 3", "Week 4", "Monthly"])
        windows = data.get("windows", [])
        weekly = data.get("weeks", [])
        monthly = data.get("monthly", [])

        for idx in range(4):
            with week_tabs[idx]:
                window = windows[idx] if idx < len(windows) else (date.today(), date.today())
                rows = weekly[idx] if idx < len(weekly) else []
                render_board(f"Week {idx+1}", rows, window)

        with week_tabs[4]:
            # Monthly window spans first -> last day of computed four weeks
            if windows:
                monthly_window = (windows[0][0], windows[-1][1])
            else:
                monthly_window = (date.today(), date.today())
            render_board("Monthly", monthly, monthly_window)
    else:
        st.info("📝 No leaderboard data yet.")

elif page == "🛡️ Sergeant Console":
    st.title("Sergeant Console")
    st.caption("Login with sergeant name (case-insensitive) and password. Captain AnewbiZ sees all.")

    def _get_secret(key: str, default: str = ""):
        try:
            return st.secrets.get(key, default)
        except Exception:
            return os.getenv(key, default)

    credentials = {
        "emlanis": _get_secret("SERGEANT_EMLANIS_PW", ""),
        "tripplea": _get_secret("SERGEANT_TRIPPLEA_PW", ""),
        "aliyu": _get_secret("SERGEANT_ALIYU_PW", ""),
        "anewbiz": _get_secret("CAPTAIN_ANEWBIZ_PW", ""),
    }

    sergeant_map = {
        "emlanis": ["Chiemerie", "Raheem", "Olarx", "Jigga"],
        "tripplea": ["BigBoss", "Ozed", "JohnnyLee", "QeengD"],
        "aliyu": ["ChisomBrown", "Shamex", "PGM", "Murad"],
        "anewbiz": [s["handle"] for s in service.get_soldiers()],
    }

    if "sergeant_user" not in st.session_state:
        st.session_state.sergeant_user = None

    if st.session_state.sergeant_user is None:
        with st.form("sergeant_login"):
            user = st.text_input("Username").strip().lower()
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                if user in credentials and credentials[user] and pw == credentials[user]:
                    st.session_state.sergeant_user = user
                    st.success("Logged in")
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    else:
        user = st.session_state.sergeant_user
        st.write(f"Logged in as **{user}**")
        if st.button("Logout"):
            st.session_state.sergeant_user = None
            st.rerun()

        allowed = sergeant_map.get(user, [])
        posts = service.get_posts_for_soldiers(allowed)
        if not posts:
            st.info("No submissions for your soldiers yet.")
        else:
            soldiers = service.get_soldiers()
            id_to_handle = {s["id"]: s["handle"] for s in soldiers}

            # Soldier filter
            handles_lower = [h.lower() for h in allowed]
            filter_options = ["All"] + sorted(set([id_to_handle.get(p["soldier_id"], "Unknown") for p in posts if id_to_handle.get(p["soldier_id"])]))
            chosen = st.selectbox("Filter by soldier", filter_options)

            if chosen != "All":
                posts = [p for p in posts if id_to_handle.get(p["soldier_id"], "") == chosen]

            st.write("Click Delete to remove a submission.")
            for p in posts:
                post_id = p.get("id")
                soldier_name = id_to_handle.get(p.get("soldier_id"), "Unknown")
                posted_at_val = p.get("posted_at")
                posted_at_disp = posted_at_val[:10] if isinstance(posted_at_val, str) else posted_at_val
                cols = st.columns([4, 5, 2, 1])
                cols[0].markdown(f"**{soldier_name}** — {p.get('category')}  ")
                cols[1].markdown(f"[Link]({p.get('url')})  \nPosted: {posted_at_disp} | Units: {p.get('units', 0)}")
                if cols[3].button("Delete", key=f"del_{post_id}"):
                    ok, msg = service.delete_post(post_id, allowed)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
