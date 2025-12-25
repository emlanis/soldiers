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


st.markdown(
    """
    <style>
    @media (max-width: 768px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        [data-testid="stHorizontalBlock"] { flex-direction: column; gap: 0.75rem; }
        [data-testid="column"] { width: 100% !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
# Load environment variables for sergeant credentials
load_dotenv()

def get_secret(key: str, default: str = ""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.getenv(key, default)

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
    st.markdown("<h1 style=\"color:#FF3912;\">Leaderboard</h1>", unsafe_allow_html=True)

    _table_css = """
    <style>
    .stMarkdown table { border-collapse: separate; border-spacing: 0; width: 100%; }
    .stMarkdown th { text-align: center; font-weight: 700; color: #FF3912; padding: 0.5rem 0.75rem; border-bottom: 1px solid #eee; }
    .stMarkdown td { text-align: center; padding: 0.5rem 0.75rem; border-bottom: 1px solid #f0f0f0; }
    .stMarkdown th:first-child, .stMarkdown td:first-child { text-align: left; }
    .stMarkdown tr:last-child td { border-bottom: none; }
    </style>
    """

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

        if title == "Monthly" and not df.empty:
            for col in ["TM", "SE", "SH", "Total", "QQ Rating"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            totals = {
                "Soldier": "Total",
                "TM": df["TM"].sum(),
                "SE": df["SE"].sum(),
                "SH": df["SH"].sum(),
                "Total": df["Total"].sum(),
                "QQ Rating": df["QQ Rating"].mean(),
            }
            df = pd.concat([df, pd.DataFrame([totals])], ignore_index=True)

        if title == "Monthly":
            medal_map = {
                0: "🥇 ",
                1: "🥈 ",
                2: "🥉 ",
                3: "4️⃣ ",
                4: "5️⃣ ",
                5: "6️⃣ ",
                6: "7️⃣ ",
                7: "8️⃣ ",
                8: "9️⃣ ",
                9: "🔟 ",
                10: "1️⃣1️⃣ ",
            }
            for i in range(min(11, len(df))):
                df.at[i, "Soldier"] = f"{medal_map[i]}{df.at[i, 'Soldier']}"

            def _style_top1(row):
                styles = [""] * len(row)
                if row.name == 0:
                    styles = ["background-color: #D4AF37; color: #000; font-weight: 600"] * len(row)
                return styles

            def _style_monthly(data):
                styles = pd.DataFrame("", index=data.index, columns=data.columns)
                total_mask = data["Soldier"] == "Total"

                for col in ["Soldier", "TM", "SE", "SH", "Total", "QQ Rating"]:
                    styles.loc[total_mask, col] = "color: #FF3912; font-weight: 700"

                non_total = ~total_mask
                tm_mask = non_total & (pd.to_numeric(data["TM"], errors="coerce") < 4)
                sh_mask = non_total & (pd.to_numeric(data["SH"], errors="coerce") < 560)
                styles.loc[tm_mask, "TM"] = "color: #d00000; font-weight: 600"
                styles.loc[sh_mask, "SH"] = "color: #d00000; font-weight: 600"

                return styles

            styler = (
                df.style
                .apply(_style_top1, axis=1)
                .apply(_style_monthly, axis=None)
                .format({"QQ Rating": "{:.2%}"})
                .hide(axis="index")
            )
            st.markdown(_table_css, unsafe_allow_html=True)
            st.markdown(styler.to_html(), unsafe_allow_html=True)
        else:
            df["QQ Rating"] = df["QQ Rating"].apply(lambda x: f"{x * 100:.2f}%")
            st.markdown(_table_css, unsafe_allow_html=True)
            st.markdown(df.to_html(index=False), unsafe_allow_html=True)

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
    st.markdown("<h1 style=\"color:#FF3912;\">Sergeant Console</h1>", unsafe_allow_html=True)
    st.caption("Login with your username and password.")

    credentials = {
        "emlanis": get_secret("SERGEANT_EMLANIS_PW", ""),
        "tripplea": get_secret("SERGEANT_TRIPPLEA_PW", ""),
        "aliyu": get_secret("SERGEANT_ALIYU_PW", ""),
        "anewbiz": get_secret("CAPTAIN_ANEWBIZ_PW", ""),
    }

    sergeant_map = {
        "emlanis": ["Chiemerie", "Raheem", "Olarx", "Jigga"],
        "tripplea": ["BigBoss", "Ozed", "JohnnyLee", "QeengD"],
        "aliyu": ["ChisomBrown", "Shamex", "Murad"],
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
            filter_cols = st.columns([2, 2, 2, 1])
            filter_options = ["All"] + sorted(set([id_to_handle.get(p["soldier_id"], "Unknown") for p in posts if id_to_handle.get(p["soldier_id"])]))
            chosen = filter_cols[0].selectbox("Filter by soldier", filter_options)

            if chosen != "All":
                posts = [p for p in posts if id_to_handle.get(p["soldier_id"], "") == chosen]

            date_options = ["All"] + sorted({
                (p.get("posted_at") or "")[:10]
                for p in posts
                if isinstance(p.get("posted_at"), str)
            }, reverse=True)
            selected_date = filter_cols[1].selectbox("Filter by date", date_options)
            if selected_date != "All":
                posts = [p for p in posts if isinstance(p.get("posted_at"), str) and p.get("posted_at", "").startswith(selected_date)]

            category_options = ["All"] + sorted({p.get("category") for p in posts if p.get("category")})
            selected_category = filter_cols[2].selectbox("Filter by category", category_options)
            if selected_category != "All":
                posts = [p for p in posts if p.get("category") == selected_category]

            filter_cols[3].markdown(
                """
                <style>
                div[data-testid="stMetricValue"] { color: #FF3912; }
                </style>
                """,
                unsafe_allow_html=True,
            )
            filter_cols[3].metric("Total Entries", len(posts))

            st.write("Use Edit to update posted date or category. Use Delete to remove a submission.")

            category_labels = {
                "TM": "Thread/Meme",
                "SE": "Secret's Engagement",
                "SH": "Shill",
            }

            for p in posts:
                post_id = p.get("id")
                soldier_name = id_to_handle.get(p.get("soldier_id"), "Unknown")
                posted_at_val = p.get("posted_at")
                posted_at_disp = posted_at_val[:10] if isinstance(posted_at_val, str) else posted_at_val
                cols = st.columns([4, 5, 1, 1])
                cols[0].markdown(f"**{soldier_name}** — {p.get('category')}  ")
                cols[1].markdown(
                    f"[Link]({p.get('url')})  \nPosted: {posted_at_disp} | Units: {p.get('units', 0)}"
                )

                if cols[2].button("Edit", key=f"edit_{post_id}"):
                    st.session_state[f"edit_open_{post_id}"] = True

                if cols[3].button("Delete", key=f"del_{post_id}"):
                    st.session_state[f"confirm_del_{post_id}"] = True

                if st.session_state.get(f"confirm_del_{post_id}"):
                    st.warning("You are about to delete this submission. This cannot be undone.")
                    confirm_cols = st.columns([1, 1, 6])
                    if confirm_cols[0].button("Yes, delete", key=f"confirm_yes_{post_id}"):
                        ok, msg = service.delete_post(post_id, allowed)
                        if ok:
                            st.success(msg)
                            st.session_state.pop(f"confirm_del_{post_id}", None)
                            st.rerun()
                        else:
                            st.error(msg)
                    if confirm_cols[1].button("Cancel", key=f"confirm_no_{post_id}"):
                        st.session_state.pop(f"confirm_del_{post_id}", None)

                if st.session_state.get(f"edit_open_{post_id}"):
                    try:
                        posted_dt = datetime.fromisoformat(posted_at_val.replace("Z", "+00:00")) if isinstance(posted_at_val, str) else posted_at_val
                        posted_date = posted_dt.date() if posted_dt else datetime.now(timezone.utc).date()
                    except Exception:
                        posted_date = datetime.now(timezone.utc).date()

                    category_value = p.get("category") or "TM"
                    category_options = ["TM", "SE", "SH"]
                    is_auto = isinstance(p.get("url"), str) and p.get("url", "").endswith("#auto-se")

                    with st.form(f"edit_form_{post_id}"):
                        new_date = st.date_input("Posted date (UTC)", value=posted_date, key=f"edit_date_{post_id}")
                        new_category = st.selectbox(
                            "Category",
                            category_options,
                            index=category_options.index(category_value) if category_value in category_options else 0,
                            format_func=lambda x: category_labels.get(x, x),
                            disabled=is_auto,
                            key=f"edit_cat_{post_id}",
                        )
                        if is_auto:
                            st.caption("Auto-added SE entry. Category is locked to Secret's Engagement.")
                        save = st.form_submit_button("Save changes")
                        cancel = st.form_submit_button("Cancel")
                        if save:
                            posted_at = datetime.combine(new_date, dtime.min).replace(tzinfo=timezone.utc)
                            ok, msg = service.update_post(post_id, allowed, new_category, posted_at)
                            if ok:
                                st.success(msg)
                                st.session_state.pop(f"edit_open_{post_id}", None)
                                st.rerun()
                            else:
                                st.error(msg)
                        if cancel:
                            st.session_state.pop(f"edit_open_{post_id}", None)
                            st.rerun()