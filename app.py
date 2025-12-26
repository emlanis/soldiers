"""
Secret Soldiers KPI Dashboard - Submit X links with posted date fidelity and view leaderboards
"""

import os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import datetime, timedelta, timezone, date, time as dtime
from dotenv import load_dotenv
from typing import List, Tuple
import time
from update_service import UpdateService
from supabase import create_client
from urllib.parse import urlsplit, parse_qs

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

def _kpi_month_window(target_date: date) -> Tuple[date, date]:
    month_start = date(target_date.year, target_date.month, 1)
    # KPI month starts on the Sunday before the 1st of the month
    start = month_start - timedelta(days=(month_start.weekday() + 1) % 7)
    end = start + timedelta(days=27)
    return start, end


def current_kpi_window(today: date) -> Tuple[date, date]:
    start, end = _kpi_month_window(today)
    if today > end:
        next_month = 1 if today.month == 12 else today.month + 1
        next_year = today.year + (1 if today.month == 12 else 0)
        start, end = _kpi_month_window(date(next_year, next_month, 1))
    elif today < start:
        prev_month = 12 if today.month == 1 else today.month - 1
        prev_year = today.year - (1 if today.month == 1 else 0)
        start, end = _kpi_month_window(date(prev_year, prev_month, 1))
    return start, end

def get_secret(key: str, default: str = ""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.getenv(key, default)

def get_auth_client():
    if "auth_client" not in st.session_state:
        url = get_secret("SUPABASE_URL")
        key = get_secret("SUPABASE_ANON_KEY")
        if not url or not key:
            st.error("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
            st.stop()
        st.session_state.auth_client = create_client(url, key)
    return st.session_state.auth_client


def load_session():
    session = st.session_state.get("auth_session")
    if not session:
        return None
    auth_client = get_auth_client()
    try:
        auth_client.auth.set_session(session["access_token"], session["refresh_token"])
        service.set_auth_session(session["access_token"], session["refresh_token"])
        user = auth_client.auth.get_user().user
        return user
    except Exception:
        return None


def require_auth():
    auth_client = get_auth_client()
    user = load_session()
    if user:
        role = (user.app_metadata or {}).get("role")
        st.session_state.user_role = role
        st.session_state.user_email = user.email
        st.sidebar.write(f"Logged in: {user.email}")
        if st.sidebar.button("Logout"):
            try:
                auth_client.auth.sign_out()
            finally:
                st.session_state.pop("auth_session", None)
                st.session_state.pop("user_role", None)
                st.rerun()
        if not role:
            st.error("Your account has no role assigned. Contact an admin.")
            st.stop()
        return role

    components.html(
        """
        <script>
        (function() {
          const parent = window.parent;
          const hash = parent.location.hash;
          if (hash && hash.includes("access_token=") && !parent.location.search.includes("access_token=")) {
            const params = new URLSearchParams(hash.slice(1));
            const url = new URL(parent.location.href);
            url.hash = "";
            params.forEach((v, k) => url.searchParams.set(k, v));
            parent.location.replace(url.toString());
          }
        })();
        </script>
        """,
        height=0,
    )

    params = st.query_params
    access_token = params.get("access_token")
    refresh_token = params.get("refresh_token")
    token_hash = params.get("token")
    invite_type = params.get("type")

    if isinstance(access_token, list):
        access_token = access_token[0] if access_token else None
    if isinstance(refresh_token, list):
        refresh_token = refresh_token[0] if refresh_token else None
    if isinstance(token_hash, list):
        token_hash = token_hash[0] if token_hash else None
    if isinstance(invite_type, list):
        invite_type = invite_type[0] if invite_type else None

    if access_token and refresh_token:
        auth_client.auth.set_session(access_token, refresh_token)
        st.session_state.auth_session = {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
        st.session_state.pending_password = True
        st.session_state.pending_password_type = invite_type or "invite"
        try:
            st.query_params.clear()
        except Exception:
            st.experimental_set_query_params()

    if token_hash and invite_type:
        try:
            res = auth_client.auth.verify_otp({"token_hash": token_hash, "type": invite_type})
            if res.session:
                st.session_state.auth_session = {
                    "access_token": res.session.access_token,
                    "refresh_token": res.session.refresh_token,
                }
                st.session_state.pending_password = True
                st.session_state.pending_password_type = invite_type
                try:
                    st.query_params.clear()
                except Exception:
                    st.experimental_set_query_params()
        except Exception as e:
            st.error(f"Invite verification failed: {e}")

    st.markdown("<h1 style=\"color:#FF3912;\">Login</h1>", unsafe_allow_html=True)
    if st.session_state.get("pending_password") and st.session_state.get("pending_password_type") == "recovery":
        st.markdown("<h1 style=\"color:#FF3912;\">Reset Password</h1>", unsafe_allow_html=True)
        with st.form("recovery_set_password"):
            new_pw = st.text_input("New password", type="password", key="recovery_pw")
            new_pw_confirm = st.text_input("Confirm password", type="password", key="recovery_pw_confirm")
            if st.form_submit_button("Set new password"):
                if not new_pw or new_pw != new_pw_confirm:
                    st.error("Passwords do not match")
                else:
                    try:
                        auth_client.auth.update_user({"password": new_pw})
                        st.session_state.pending_password = False
                        st.session_state.pending_password_type = None
                        st.success("Password updated. You are now logged in.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Password update failed: {e}")
        st.stop()

    tabs = st.tabs(["Sign in", "Accept invite"])

    with tabs[0]:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            btn_row = st.columns([1, 2, 2, 1])
            with btn_row[1]:
                sign_in = st.form_submit_button("Sign in")
            with btn_row[2]:
                reset = st.form_submit_button("Reset password")

            if sign_in:
                try:
                    res = auth_client.auth.sign_in_with_password({"email": email, "password": password})
                    if res.session:
                        st.session_state.auth_session = {
                            "access_token": res.session.access_token,
                            "refresh_token": res.session.refresh_token,
                        }
                        st.rerun()
                    else:
                        st.error("Login failed")
                except Exception as e:
                    st.error(f"Login failed: {e}")

            if reset:
                if not email:
                    st.error("Enter your email to reset your password")
                else:
                    try:
                        auth_client.auth.reset_password_for_email(email)
                        st.success("Reset link sent. Check your email.")
                    except Exception as e:
                        st.error(f"Reset failed: {e}")

    with tabs[1]:
        st.write("Open your invite email link in the browser. After redirect, set your password here.")
        if st.session_state.get("pending_password") and st.session_state.get("pending_password_type") == "invite":
            with st.form("invite_set_password"):
                new_pw = st.text_input("New password", type="password")
                new_pw_confirm = st.text_input("Confirm password", type="password")
                if st.form_submit_button("Set password"):
                    if not new_pw or new_pw != new_pw_confirm:
                        st.error("Passwords do not match")
                    else:
                        try:
                            auth_client.auth.update_user({"password": new_pw})
                            st.session_state.pending_password = False
                            st.session_state.pending_password_type = None
                            st.success("Password set. You are now logged in.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Password update failed: {e}")
        else:
            st.info("Waiting for invite redirect. Open your invite link first.")

    st.stop()

# Sidebar with logo
try:
    col1, col2, col3 = st.sidebar.columns([1, 2, 1])
    with col2:
        st.image("img/secret.png", width=80)
except:
    st.sidebar.write("🚀")

role = require_auth()

page_options = ["✨ Submit Content", "🏅 Leaderboard"]
if role in {"sergeant", "captain"}:
    page_options.append("🛡️ Sergeant Console")

page = st.sidebar.selectbox("Navigation", page_options)

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

        today = datetime.now(timezone.utc).date()
        kpi_start, kpi_end = current_kpi_window(today)
        default_date = min(max(today, kpi_start), kpi_end)
        st.caption(f"Submissions allowed only for the current KPI month: {kpi_start} to {kpi_end} (UTC).")
        posted_date = st.date_input(
            "Posted date (UTC)",
            value=default_date,
            min_value=kpi_start,
            max_value=kpi_end,
        )
        confirm = st.checkbox("I confirm the category and posted date are correct for this link.")

        if st.form_submit_button("Submit Content"):
            if not content_url:
                st.error("Please enter a content URL")
            elif not soldier:
                st.error("Please select a soldier")
            elif not confirm:
                st.error("Please confirm category and posted date are correct.")
            elif posted_date < kpi_start or posted_date > kpi_end:
                st.error(f"Posted date must be within the current KPI month: {kpi_start} to {kpi_end} (UTC).")
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
    sergeant_map = {
        "emlanisk@gmail.com": ["Chiemerie", "Raheem", "Olarx", "Jigga"],
        "adeniyiabdulwahab372@gmail.com": ["BigBoss", "Ozed", "JohnnyLee", "QeengD"],
        "thisismohammedaliyu@gmail.com": ["ChisomBrown", "Shamex", "Murad"],
    }

    role = st.session_state.get("user_role")
    user_email = (st.session_state.get("user_email") or "").lower()

    if role not in {"sergeant", "captain"}:
        st.error("Not authorized")
        st.stop()

    if role == "captain":
        allowed = [s["handle"] for s in service.get_soldiers()]
        st.write("Logged in as **Captain**")
    else:
        allowed = sergeant_map.get(user_email, [])
        st.write(f"Logged in as **{user_email}**")
        if not allowed:
            st.error("No soldier access configured for this account")
            st.stop()
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