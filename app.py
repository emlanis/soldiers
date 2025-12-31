"""
Secret Soldiers KPI Dashboard - Submit X links with posted date fidelity and view leaderboards
"""

import os
import json
import base64
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone, date, time as dtime
from typing import List, Tuple
from urllib.parse import urlsplit, parse_qs

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from supabase import create_client

from update_service import UpdateService


@st.cache_resource
def get_update_service():
    return UpdateService()


# Clear cache on app restart to ensure latest code is loaded
if "service_initialized" not in st.session_state:
    st.cache_resource.clear()
    st.session_state.service_initialized = True

service = get_update_service()

st.set_page_config(
    page_title="Secret Soldiers Dashboard",
    page_icon="img/secret.png",
    layout="wide",
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


def kpi_month_sequence(today: date, count: int = 6) -> List[Tuple[int, int]]:
    _, end = current_kpi_window(today)
    months = []
    year, month = end.year, end.month
    for i in range(count):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))
    return months


def start_of_week_window(target_date: date) -> date:
    """Return the Sunday that starts the 4-week window containing the month start."""
    return target_date - timedelta(days=(target_date.weekday() + 1) % 7)


def four_week_windows(year: int, month: int) -> List[Tuple[date, date]]:
    month_start = date(year, month, 1)
    week1_start = start_of_week_window(month_start)
    windows = []
    for i in range(4):
        start = week1_start + timedelta(days=7 * i)
        end = start + timedelta(days=6)
        windows.append((start, end))
    return windows


def get_secret(key: str, default: str = ""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.getenv(key, default)


_PROFILE_IMAGE_MAP: dict = {}


def _load_profile_images() -> None:
    if _PROFILE_IMAGE_MAP:
        return
    img_dir = Path(__file__).resolve().parent / "img"
    if not img_dir.exists():
        return
    for path in img_dir.iterdir():
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        key = path.stem.strip().lstrip("@").lower()
        _PROFILE_IMAGE_MAP[key] = path


@st.cache_data(show_spinner=False)
def profile_image_data_uri(handle: str) -> str:
    if not handle:
        return ""
    _load_profile_images()
    key = handle.strip().lstrip("@").lower()
    path = _PROFILE_IMAGE_MAP.get(key)
    if not path:
        return ""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{data}"


def render_profile_header(handle: str, title_html: str, subtitle_html: str = "") -> None:
    data_uri = profile_image_data_uri(handle)
    subtitle_block = f'<div style="font-size:1.15rem;font-weight:600;">{subtitle_html}</div>' if subtitle_html else ""
    if data_uri:
        st.markdown(
            f"""
            <div style="display:flex;flex-direction:column;align-items:center;text-align:center;gap:0.35rem;margin-bottom:0.5rem;">
              <img src="{data_uri}" alt="{handle}" style="width:72px;height:72px;border-radius:50%;object-fit:cover;border:2px solid #FF3912;" />
              <div style="font-size:1.6rem;font-weight:700;">{title_html}</div>
              {subtitle_block}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="display:flex;flex-direction:column;align-items:center;text-align:center;gap:0.35rem;margin-bottom:0.5rem;">
              <div style="font-size:1.6rem;font-weight:700;">{title_html}</div>
              {subtitle_block}
            </div>
            """,
            unsafe_allow_html=True,
        )


def persist_auth_session():
    session = st.session_state.get("auth_session")
    if not session:
        return
    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    if not access_token or not refresh_token:
        return
    payload = json.dumps({"access_token": access_token, "refresh_token": refresh_token})
    components.html(
        f"""
        <script>
        (function() {{
          const data = {payload};
          let store;
          try {{
            store = window.parent.localStorage || window.localStorage;
          }} catch (e) {{
            store = window.localStorage;
          }}
          if (store) {{
            store.setItem("ss_access_token", data.access_token);
            store.setItem("ss_refresh_token", data.refresh_token);
          }}
        }})();
        </script>
        """,
        height=0,
    )


def clear_persisted_session():
    components.html(
        """
        <script>
        (function() {
          let store;
          try {
            store = window.parent.localStorage || window.localStorage;
          } catch (e) {
            store = window.localStorage;
          }
          if (store) {
            store.removeItem("ss_access_token");
            store.removeItem("ss_refresh_token");
          }
        })();
        </script>
        """,
        height=0,
    )


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
        if not user:
            st.session_state.pop("auth_session", None)
            return None
        return user
    except Exception:
        st.session_state.pop("auth_session", None)
        return None


def require_auth():
    auth_client = get_auth_client()
    user = load_session()
    if user:
        app_meta = user.app_metadata or {}
        user_meta = user.user_metadata or {}
        role = app_meta.get("role")
        handle = app_meta.get("handle") or user_meta.get("display_name") or user_meta.get("full_name") or user_meta.get("name")
        if not handle and user.email:
            handle = user.email.split("@")[0]
        st.session_state.user_role = role
        st.session_state.user_email = user.email
        st.session_state.user_handle = handle
        persist_auth_session()
        st.sidebar.write(f"Logged in: {user.email}")
        if st.sidebar.button("Logout"):
            try:
                auth_client.auth.sign_out()
            finally:
                st.session_state.pop("auth_session", None)
                st.session_state.pop("user_role", None)
                st.session_state.pop("user_email", None)
                st.session_state.pop("user_handle", None)
                st.session_state.pop("pending_password", None)
                st.session_state.pop("pending_password_type", None)
                clear_persisted_session()
                try:
                    st.query_params.clear()
                except Exception:
                    st.experimental_set_query_params()
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
          let store;
          try {
            store = parent.localStorage || window.localStorage;
          } catch (e) {
            store = window.localStorage;
          }
          if (!store) return;
          const access = store.getItem("ss_access_token");
          const refresh = store.getItem("ss_refresh_token");
          if (access && refresh && !parent.location.search.includes("access_token=")) {
            const url = new URL(parent.location.href);
            url.hash = "";
            url.searchParams.set("access_token", access);
            url.searchParams.set("refresh_token", refresh);
            parent.location.replace(url.toString());
            return;
          }
        })();
        </script>
        """,
        height=0,
    )

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
        try:
            auth_client.auth.set_session(access_token, refresh_token)
            st.session_state.auth_session = {
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
            persist_auth_session()
            st.session_state.pending_password = True
            st.session_state.pending_password_type = invite_type or "recovery"
            try:
                st.query_params.clear()
            except Exception:
                st.experimental_set_query_params()
        except Exception:
            st.session_state.pop("auth_session", None)
            clear_persisted_session()
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

    st.markdown('<h1 style="color:#FF3912;">Login</h1>', unsafe_allow_html=True)
    if st.session_state.get("pending_password") and not st.session_state.get("auth_session"):
        st.session_state.pending_password = False
        st.session_state.pending_password_type = None
    if st.session_state.get("pending_password") and st.session_state.get("pending_password_type") == "recovery":
        st.markdown('<h1 style="color:#FF3912;">Reset Password</h1>', unsafe_allow_html=True)
        with st.form("recovery_set_password"):
            new_pw = st.text_input("New password", type="password", key="recovery_pw")
            new_pw_confirm = st.text_input("Confirm password", type="password", key="recovery_pw_confirm")
            if st.form_submit_button("Set new password"):
                if not new_pw or new_pw != new_pw_confirm:
                    st.error("Passwords do not match")
                else:
                    try:
                        auth_client.auth.update_user({"password": new_pw})
                        user = auth_client.auth.get_user().user
                        email = user.email if user else None
                        if not email:
                            raise RuntimeError("Could not resolve user email after reset")
                        res = auth_client.auth.sign_in_with_password({"email": email, "password": new_pw})
                        if not res.session:
                            raise RuntimeError("Password update did not stick. Please try reset again.")
                        st.session_state.auth_session = {
                            "access_token": res.session.access_token,
                            "refresh_token": res.session.refresh_token,
                        }
                        persist_auth_session()
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
                        persist_auth_session()
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
                            user = auth_client.auth.get_user().user
                            email = user.email if user else None
                            if not email:
                                raise RuntimeError("Could not resolve user email after invite")
                            res = auth_client.auth.sign_in_with_password({"email": email, "password": new_pw})
                            if not res.session:
                                raise RuntimeError("Password update did not stick. Please try invite again.")
                            st.session_state.auth_session = {
                                "access_token": res.session.access_token,
                                "refresh_token": res.session.refresh_token,
                            }
                            persist_auth_session()
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
except Exception:
    st.sidebar.write("🚀")

role = require_auth()

page_options = ["✨ Submit Content", "🏅 Leaderboard"]
if role in {"sergeant", "captain"}:
    page_options.append("🛡️ Sergeant Console")

page = st.sidebar.selectbox("Navigation", page_options)

if page == "✨ Submit Content":
    handle = st.session_state.get("user_handle")
    if handle:
        render_profile_header(handle, f"gm {handle} ⚡️🛡️", "✍️ Submit New Content")
    else:
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
    role = st.session_state.get("user_role")
    handle = st.session_state.get("user_handle")
    if handle:
        render_profile_header(handle, '<span style="color:#FF3912;">Leaderboard</span>')
        if role == "soldier":
            st.markdown(f"Hey {handle}, check the leaderboard to see how you’re doing in the battlefield 😎")
        else:
            st.markdown(f"Hey {handle}, check the leaderboard to see how your soldiers are doing in the battlefield 😎")
    else:
        st.markdown('<h1 style="color:#FF3912;">Leaderboard</h1>', unsafe_allow_html=True)

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
    today = datetime.now(timezone.utc).date()
    current_start, current_end = current_kpi_window(today)
    current_key = (current_end.year, current_end.month)

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        month_options = []
        month_values = []
        for year, month in kpi_month_sequence(today, 6):
            label = datetime(year, month, 1).strftime('%B %Y')
            if (year, month) == current_key:
                label = f"{label} (Current)"
            month_options.append(label)
            month_values.append((year, month))
        for year, month in available_months:
            if (year, month) not in month_values:
                month_name = datetime(year, month, 1).strftime('%B %Y')
                month_options.append(month_name)
                month_values.append((year, month))
        selected_index = st.selectbox(
            "Select Month:",
            range(len(month_options)),
            format_func=lambda x: month_options[x],
            key="month_select_x",
        )
        selected_year, selected_month = month_values[selected_index]

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
            if windows:
                monthly_window = (windows[0][0], windows[-1][1])
            else:
                monthly_window = (date.today(), date.today())
            render_board("Monthly", monthly, monthly_window)
    else:
        st.info("📝 No leaderboard data yet.")

elif page == "🛡️ Sergeant Console":
    role = st.session_state.get("user_role")
    user_email = (st.session_state.get("user_email") or "").lower()
    user_handle = st.session_state.get("user_handle") or user_email.split("@")[0]
    is_captain = role == "captain"
    is_super_sergeant = user_email == "emlanis@scrt.network"
    header_title = "Captain Console" if is_captain else "Sergeant Console"
    if user_handle:
        render_profile_header(user_handle, f'<span style="color:#FF3912;">{header_title}</span>')
    else:
        st.markdown(f'<h1 style="color:#FF3912;">{header_title}</h1>', unsafe_allow_html=True)
    sergeant_map = {
        "emlanis@scrt.network": ["Chiemerie", "Raheem", "Olarx", "Jigga"],
        "adeniyiabdulwahab372@gmail.com": ["BigBoss", "Ozed", "JohnnyLee", "QeengD"],
        "thisismohammedaliyu@gmail.com": ["ChisomBrown", "Shamex", "Murad"],
    }

    if role not in {"sergeant", "captain"}:
        st.error("Not authorized")
        st.stop()

    if is_captain or is_super_sergeant:
        allowed = [s["handle"] for s in service.get_soldiers()]
        st.write(f"Logged in as **{user_handle}**")
        if is_super_sergeant:
            st.caption("All soldiers access")
    else:
        allowed = sergeant_map.get(user_email, [])
        st.write(f"Logged in as **{user_handle}**")
        if not allowed:
            st.error("No soldier access configured for this account")
            st.stop()

    posts = service.get_posts_for_soldiers(allowed)
    if not posts:
        st.info("No submissions for your soldiers yet.")
    else:
        soldiers = service.get_soldiers()
        id_to_handle = {s["id"]: s["handle"] for s in soldiers}

        filter_cols = st.columns([2, 2, 2, 1])
        filter_options = sorted(
            set([id_to_handle.get(p["soldier_id"], "Unknown") for p in posts if id_to_handle.get(p["soldier_id"])])
        )
        chosen_soldiers = filter_cols[0].multiselect("Filter by soldier", filter_options, default=[])
        if chosen_soldiers:
            posts = [
                p
                for p in posts
                if id_to_handle.get(p["soldier_id"], "") in chosen_soldiers
            ]

        def _post_date(row):
            posted_at = row.get("posted_at")
            if isinstance(posted_at, str):
                try:
                    return datetime.fromisoformat(posted_at.replace("Z", "+00:00")).date()
                except Exception:
                    return None
            if isinstance(posted_at, datetime):
                return posted_at.date()
            return None

        date_filter_mode = filter_cols[1].selectbox(
            "Filter by date",
            ["All dates", "Custom range", "KPI month window", "KPI week window"],
        )

        date_range = None
        today = datetime.now(timezone.utc).date()
        if date_filter_mode == "Custom range":
            range_val = st.date_input("Date range", value=(today, today), key="date_range")
            if isinstance(range_val, tuple):
                start_date, end_date = range_val
            else:
                start_date = end_date = range_val
            if start_date and end_date:
                date_range = (min(start_date, end_date), max(start_date, end_date))
        elif date_filter_mode == "KPI month window":
            month_options = []
            month_values = []
            current_start, current_end = current_kpi_window(today)
            current_key = (current_end.year, current_end.month)
            for year, month in kpi_month_sequence(today, 6):
                label = datetime(year, month, 1).strftime('%B %Y')
                if (year, month) == current_key:
                    label = f"{label} (Current)"
                month_options.append(label)
                month_values.append((year, month))
            for year, month in service.get_available_months():
                if (year, month) not in month_values:
                    month_name = datetime(year, month, 1).strftime('%B %Y')
                    month_options.append(month_name)
                    month_values.append((year, month))
            selected_idx = st.selectbox(
                "KPI month window",
                range(len(month_options)),
                format_func=lambda x: month_options[x],
                key="kpi_month_filter",
            )
            year, month = month_values[selected_idx]
            start_date, end_date = _kpi_month_window(date(year, month, 1))
            st.caption(f"Window: {start_date} → {end_date}")
            date_range = (start_date, end_date)
        elif date_filter_mode == "KPI week window":
            month_options = []
            month_values = []
            current_start, current_end = current_kpi_window(today)
            current_key = (current_end.year, current_end.month)
            for year, month in kpi_month_sequence(today, 6):
                label = datetime(year, month, 1).strftime('%B %Y')
                if (year, month) == current_key:
                    label = f"{label} (Current)"
                month_options.append(label)
                month_values.append((year, month))
            for year, month in service.get_available_months():
                if (year, month) not in month_values:
                    month_name = datetime(year, month, 1).strftime('%B %Y')
                    month_options.append(month_name)
                    month_values.append((year, month))
            month_idx = st.selectbox(
                "KPI month for weeks",
                range(len(month_options)),
                format_func=lambda x: month_options[x],
                key="kpi_week_month_filter",
            )
            year, month = month_values[month_idx]
            week_windows = four_week_windows(year, month)
            week_labels = [
                f"Week {i+1}: {window[0]} → {window[1]}"
                for i, window in enumerate(week_windows)
            ]
            week_idx = st.selectbox(
                "KPI week window",
                range(len(week_labels)),
                format_func=lambda x: week_labels[x],
                key="kpi_week_filter",
            )
            start_date, end_date = week_windows[week_idx]
            date_range = (start_date, end_date)

        if date_range:
            start_date, end_date = date_range
            filtered = []
            for p in posts:
                d = _post_date(p)
                if d and start_date <= d <= end_date:
                    filtered.append(p)
            posts = filtered

        category_options = ["All"] + sorted({p.get("category") for p in posts if p.get("category")})
        selected_category = filter_cols[2].selectbox("Filter by category", category_options)
        if selected_category != "All":
            posts = [p for p in posts if p.get("category") == selected_category]

        filter_key = (
            tuple(chosen_soldiers),
            date_filter_mode,
            date_range,
            selected_category,
        )
        if st.session_state.get("posts_filter_key") != filter_key:
            st.session_state.posts_filter_key = filter_key
            st.session_state.posts_page = 1

        total_entries = len(posts)
        page_size = 50
        total_pages = max(1, (total_entries + page_size - 1) // page_size)
        current_page = st.session_state.get("posts_page", 1)
        if current_page > total_pages:
            current_page = total_pages
        start_idx = (current_page - 1) * page_size
        end_idx = start_idx + page_size
        page_posts = posts[start_idx:end_idx]

        page_cols = st.columns([1, 1, 2, 1, 1])
        if page_cols[1].button("Prev", disabled=current_page <= 1, key="posts_prev"):
            st.session_state.posts_page = current_page - 1
            st.rerun()
        page_cols[2].markdown(f"Page {current_page} of {total_pages}")
        if page_cols[3].button("Next", disabled=current_page >= total_pages, key="posts_next"):
            st.session_state.posts_page = current_page + 1
            st.rerun()

        filter_cols[3].markdown(
            """
            <style>
            div[data-testid="stMetricValue"] { color: #FF3912; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        filter_cols[3].metric("Total Entries", total_entries)

        st.write("Use Edit to update posted date or category. Use Delete to remove a submission.")

        category_labels = {
            "TM": "Thread/Meme",
            "SE": "Secret's Engagement",
            "SH": "Shill",
        }

        for p in page_posts:
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
                    posted_dt = (
                        datetime.fromisoformat(posted_at_val.replace("Z", "+00:00"))
                        if isinstance(posted_at_val, str)
                        else posted_at_val
                    )
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
