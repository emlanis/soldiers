import os
from datetime import datetime, timedelta, date, time, timezone
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from supabase import create_client
import streamlit as st
import requests
import re

load_dotenv()


# QQ points thresholds based on total units for a day
QQ_THRESHOLDS: List[Tuple[int, int]] = [
    (0, 0),
    (2, 1),
    (5, 2),
    (8, 3),
    (11, 4),
    (15, 5),
    (20, 6),
    (25, 7),
    (30, 8),
    (35, 9),
]


def compute_qq_points(units: int) -> int:
    for upper, points in QQ_THRESHOLDS:
        if units <= upper:
            return points
    return 10


def start_of_week_window(target_date: date) -> date:
    """Return the Sunday that starts the 4-week window containing the month start."""
    # weekday(): Monday=0, Sunday=6. We want the previous Sunday (or same day if Sunday)
    return target_date - timedelta(days=(target_date.weekday() + 1) % 7)


def four_week_windows(year: int, month: int) -> List[Tuple[date, date]]:
    """Compute 4 week windows as specified (rolling Sunday starts)."""
    month_start = date(year, month, 1)
    week1_start = start_of_week_window(month_start)
    windows = []
    for i in range(4):
        start = week1_start + timedelta(days=7 * i)
        end = start + timedelta(days=6)
        windows.append((start, end))
    return windows


class UpdateService:
    def __init__(self):
        url = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")

        self.supabase = create_client(url, key)
        self._soldier_cache: Dict[str, Dict] = {}

        # Optional tweet meta sources
        self.x_bearer_token = os.getenv("X_BEARER_TOKEN")
        self.worker_endpoint = os.getenv("WORKER_TWEET_META_ENDPOINT")

    # -------------------------------------------------------------
    # Soldier helpers
    # -------------------------------------------------------------
    def refresh_soldiers(self):
        resp = self.supabase.table("soldiers").select("id, handle, profile_url").execute()
        self._soldier_cache = {row["handle"]: row for row in resp.data if row.get("handle", "").lower() != "pgm"} if resp.data else {}

    def get_soldiers(self) -> List[Dict]:
        if not self._soldier_cache:
            self.refresh_soldiers()
        return list(self._soldier_cache.values())

    def _get_soldier(self, handle: str) -> Optional[Dict]:
        if not self._soldier_cache:
            self.refresh_soldiers()
        return self._soldier_cache.get(handle)

    # -------------------------------------------------------------
    # Tweet meta fetching (worker preferred, X API fallback)
    # -------------------------------------------------------------
    def extract_handle_and_id(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            parsed = requests.utils.urlparse(url)
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) < 3:
                return None, None
            handle = path_parts[0]
            status_literal = path_parts[1].lower()
            tweet_id = path_parts[2]
            if status_literal != "status":
                return None, None
            return handle, tweet_id
        except Exception:
            return None, None

    def resolve_x_url(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        handle, tweet_id = self.extract_handle_and_id(url)
        if handle and handle.lower() != "i":
            return url, handle, tweet_id
        try:
            resp = requests.get(
                url,
                allow_redirects=True,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            final_url = resp.url
            resolved_handle, resolved_id = self.extract_handle_and_id(final_url)
            if resolved_handle and resolved_id:
                return final_url, resolved_handle, resolved_id
        except Exception:
            pass
        return None, None, tweet_id

    def normalize_x_url(self, url: str) -> Optional[str]:
        handle, tweet_id = self.extract_handle_and_id(url)
        if not handle or not tweet_id:
            return None
        handle_norm = handle.lower()
        if handle_norm == "i":
            return f"https://x.com/i/status/{tweet_id}"
        return f"https://x.com/{handle_norm}/status/{tweet_id}"

    def _fetch_from_x_api(self, url: str) -> Dict:
        if not self.x_bearer_token:
            return {}
        _, tweet_id = self.extract_handle_and_id(url)
        if not tweet_id:
            return {}
        api_url = f"https://api.twitter.com/2/tweets/{tweet_id}"
        params = {"tweet.fields": "created_at,public_metrics"}
        try:
            resp = requests.get(api_url, params=params, headers={"Authorization": f"Bearer {self.x_bearer_token}"}, timeout=10)
            if resp.status_code != 200:
                print(f"⚠️ X API error {resp.status_code}: {resp.text}")
                return {"error": f"X API error {resp.status_code}", "body": resp.text}
            data = resp.json().get("data") or {}
            created = data.get("created_at")
            metrics = data.get("public_metrics") or {}
            parsed_posted_at = None
            if created:
                try:
                    parsed_posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    parsed_posted_at = None
            return {
                "posted_at": parsed_posted_at,
                "posted_at_raw": created,
                "likes": metrics.get("like_count", 0),
                "reposts": metrics.get("retweet_count", 0),
                "views": metrics.get("impression_count", 0),
            }
        except Exception as e:
            print(f"⚠️ X API fetch failed: {e}")
            return {"error": f"X API fetch failed: {e}"}

    def fetch_tweet_meta(self, url: str) -> Dict:
        """
        Metadata fetch disabled (no X plan). Returns empty to rely on manual posted date.
        """
        return {}

    # -------------------------------------------------------------
    # Submission
    # -------------------------------------------------------------
    def _extract_profile_handle(self, profile_url: Optional[str]) -> Optional[str]:
        if not profile_url:
            return None
        try:
            parsed = requests.utils.urlparse(profile_url)
            path_parts = [p for p in parsed.path.split("/") if p]
            return path_parts[0] if path_parts else None
        except Exception:
            return None

    def add_content(self, soldier_handle: str, content_url: str, category_label: str, posted_at: Optional[datetime], use_auto_fetch: bool = False):
        try:
            soldier = self._get_soldier(soldier_handle)
            if not soldier:
                return False, "Soldier not found. Refresh and try again."

            category_map = {
                "Thread/Meme": "TM",
                "Thread/Memes": "TM",
                "Secret's Engagement": "SE",
                "Shill": "SH",
                "SHILL": "SH",
            }
            category = category_map.get(category_label, category_label)
            if category not in {"TM", "SE", "SH"}:
                return False, "Invalid category."

            resolved_url, url_handle, url_tweet_id = self.resolve_x_url(content_url)
            if not url_tweet_id:
                return False, "Invalid X link format."

            normalized_url = self.normalize_x_url(resolved_url or content_url)
            if not normalized_url:
                return False, "Invalid X link format."

            # Enforce link belongs to selected soldier
            profile_handle = self._extract_profile_handle(soldier.get("profile_url"))
            soldier_handles = {h.lower() for h in [soldier_handle, profile_handle] if h}

            if url_handle and url_handle.lower() != "i" and soldier_handles and url_handle.lower() not in soldier_handles:
                return False, "Link handle does not match selected soldier."

            # Prevent duplicates by tweet_id for this soldier
            existing = self.supabase.table("posts").select("id").eq("soldier_id", soldier["id"]).ilike("url", f"%{url_tweet_id}%").execute()
            if existing.data:
                return False, "Link already submitted for this soldier. Please submit a new link."

            # Prevent duplicate /i/status links across all soldiers
            if url_handle and url_handle.lower() == "i":
                global_existing = self.supabase.table("posts").select("id").ilike("url", f"%{url_tweet_id}%").execute()
                if global_existing.data:
                    return False, "This link has already been submitted by another soldier."

            # Fetch meta only if allowed; otherwise rely on provided posted_at
            meta = self.fetch_tweet_meta(content_url) if use_auto_fetch else {}
            posted_at_final = posted_at or meta.get("posted_at")
            if not posted_at_final and meta.get("posted_at_raw"):
                try:
                    posted_at_final = datetime.fromisoformat(meta["posted_at_raw"].replace("Z", "+00:00"))
                except Exception:
                    posted_at_final = None
            if isinstance(posted_at_final, str):
                try:
                    posted_at_final = datetime.fromisoformat(posted_at_final.replace("Z", "+00:00"))
                except Exception:
                    posted_at_final = None
            if not posted_at_final:
                error_detail = meta.get("error") or meta.get("body") or "Posted date missing."
                return False, f"Posted date is required. {error_detail}"

            # Normalize to UTC naive -> aware
            if posted_at_final.tzinfo is None:
                posted_at_final = posted_at_final.replace(tzinfo=timezone.utc)

            # Prepare meta, ensuring JSON-serializable payload
            safe_raw_meta = dict(meta) if meta else {}
            if "posted_at" in safe_raw_meta and isinstance(safe_raw_meta["posted_at"], datetime):
                safe_raw_meta["posted_at"] = safe_raw_meta["posted_at"].isoformat()

            base_meta = {
                "likes": meta.get("likes", 0),
                "reposts": meta.get("reposts", 0),
                "views": meta.get("views", 0),
                "raw_meta": safe_raw_meta,
            }

            rows = []
            # Primary post
            rows.append({
                "soldier_id": soldier["id"],
                "category": category,
                "url": normalized_url,
                "units": 1,
                "posted_at": posted_at_final.isoformat(),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                **base_meta,
            })

            # Auto +6 SE when category is TM
            if category == "TM":
                rows.append({
                    "soldier_id": soldier["id"],
                    "category": "SE",
                    "url": f"{normalized_url}#auto-se",
                    "units": 6,
                    "posted_at": posted_at_final.isoformat(),
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    **base_meta,
                })

            result = self.supabase.table("posts").upsert(rows, on_conflict="soldier_id,url").execute()
            if result.data is None:
                return False, "Insert failed"
            return True, "Content recorded with posted date"
        except Exception as e:
            return False, f"Error: {str(e)}"

    # -------------------------------------------------------------
    # Date windows and aggregation
    # -------------------------------------------------------------
    def get_available_months(self) -> List[Tuple[int, int]]:
        try:
            resp = self.supabase.table("posts").select("posted_at").order("posted_at", desc=True).execute()
            months = set()
            if resp.data:
                for row in resp.data:
                    if not row.get("posted_at"):
                        continue
                    d = datetime.fromisoformat(row["posted_at"].replace("Z", "+00:00")).date()
                    months.add((d.year, d.month))
            return sorted(list(months), reverse=True)
        except Exception:
            return []

    def _fetch_posts_range(self, start: date, end: date) -> List[Dict]:
        start_iso = datetime.combine(start, time.min).replace(tzinfo=timezone.utc).isoformat()
        end_iso = datetime.combine(end, time.max).replace(tzinfo=timezone.utc).isoformat()
        resp = self.supabase.table("posts").select("*").gte("posted_at", start_iso).lte("posted_at", end_iso).execute()
        return resp.data or []

    def _aggregate_range(self, start: date, end: date) -> List[Dict]:
        posts = self._fetch_posts_range(start, end)
        soldiers = self.get_soldiers()
        id_to_handle = {s["id"]: s["handle"] for s in soldiers}
        days_in_range = (end - start).days + 1

        agg: Dict[str, Dict] = {}

        for post in posts:
            sid = post["soldier_id"]
            handle = id_to_handle.get(sid, "Unknown")
            if handle.lower() == "pgm" or handle == "Unknown":
                continue
            if handle not in agg:
                agg[handle] = {
                    "handle": handle,
                    "tm": 0,
                    "se": 0,
                    "sh": 0,
                    "total_units": 0,
                    "daily": {},
                }
            category = post.get("category")
            units = post.get("units", 0)
            posted_at = datetime.fromisoformat(post["posted_at"].replace("Z", "+00:00"))
            day_key = posted_at.date()

            if category == "TM":
                agg[handle]["tm"] += units
            elif category == "SE":
                agg[handle]["se"] += units
            elif category == "SH":
                agg[handle]["sh"] += units

            agg[handle]["total_units"] += units
            agg[handle]["daily"][day_key] = agg[handle]["daily"].get(day_key, 0) + units

        # compute daily qq and weekly score
        for handle, data in agg.items():
            daily_points = 0
            for i in range(days_in_range):
                d = start + timedelta(days=i)
                units = data["daily"].get(d, 0)
                daily_points += compute_qq_points(units)
            data["score"] = daily_points / (days_in_range * 10) if days_in_range > 0 else 0

        leaderboard = list(agg.values())
        leaderboard.sort(key=lambda x: (-x["score"], -x["total_units"], x["handle"]))
        return leaderboard

    def get_leaderboards(self, year: int, month: int) -> Dict:
        windows = four_week_windows(year, month)
        weekly = []
        for start, end in windows:
            weekly.append(self._aggregate_range(start, end))

        # Monthly = average of weekly scores and sum of units
        monthly_agg: Dict[str, Dict] = {}
        for week in weekly:
            for row in week:
                h = row["handle"]
                if h not in monthly_agg:
                    monthly_agg[h] = {
                        "handle": h,
                        "tm": 0,
                        "se": 0,
                        "sh": 0,
                        "total_units": 0,
                        "scores": [],
                    }
                monthly_agg[h]["tm"] += row["tm"]
                monthly_agg[h]["se"] += row["se"]
                monthly_agg[h]["sh"] += row["sh"]
                monthly_agg[h]["total_units"] += row["total_units"]
                monthly_agg[h]["scores"].append(row["score"])

        monthly_list = []
        for h, data in monthly_agg.items():
            avg_score = sum(data["scores"]) / 4 if data["scores"] else 0  # missing weeks treated as 0
            monthly_list.append({
                "handle": h,
                "tm": data["tm"],
                "se": data["se"],
                "sh": data["sh"],
                "total_units": data["total_units"],
                "score": avg_score,
            })

        monthly_list.sort(key=lambda x: (-x["score"], -x["total_units"], x["handle"]))

        return {
            "weeks": weekly,
            "monthly": monthly_list,
            "windows": windows,
        }

    # -------------------------------------------------------------
    # Admin helpers
    # -------------------------------------------------------------
    def get_posts_for_soldiers(self, handles: List[str]) -> List[Dict]:
        if not handles:
            return []
        soldiers = self.get_soldiers()
        handle_to_id = {s["handle"].lower(): s["id"] for s in soldiers}
        ids = [handle_to_id[h.lower()] for h in handles if h.lower() in handle_to_id]
        if not ids:
            return []
        resp = self.supabase.table("posts").select("*").in_("soldier_id", ids).order("posted_at", desc=True).execute()
        return resp.data or []

    def delete_post(self, post_id: str, allowed_handles: List[str]) -> Tuple[bool, str]:
        try:
            soldiers = self.get_soldiers()
            handle_to_id = {s["handle"].lower(): s["id"] for s in soldiers}
            allowed_ids = {handle_to_id[h.lower()] for h in allowed_handles if h.lower() in handle_to_id}
            if not allowed_ids:
                return False, "Not authorized"
            # Verify post belongs to allowed soldiers
            post = self.supabase.table("posts").select("id,soldier_id").eq("id", post_id).execute()
            if getattr(post, "error", None):
                return False, f"Error: {post.error}"
            if not post.data:
                return False, "Post not found"
            if post.data[0]["soldier_id"] not in allowed_ids:
                return False, "Not authorized"
            resp = self.supabase.table("posts").delete().eq("id", post_id).execute()
            if getattr(resp, "error", None):
                return False, f"Error: {resp.error}"
            # Confirm deletion
            check = self.supabase.table("posts").select("id").eq("id", post_id).execute()
            if getattr(check, "error", None):
                return False, f"Error: {check.error}"
            if check.data:
                return False, "Delete failed (row still exists)"
            return True, "Deleted"
        except Exception as e:
            return False, f"Error: {e}"

    def update_post(self, post_id: str, allowed_handles: List[str], category: str, posted_at: datetime) -> Tuple[bool, str]:
        try:
            soldiers = self.get_soldiers()
            handle_to_id = {s["handle"].lower(): s["id"] for s in soldiers}
            allowed_ids = {handle_to_id[h.lower()] for h in allowed_handles if h.lower() in handle_to_id}
            if not allowed_ids:
                return False, "Not authorized"

            post = self.supabase.table("posts").select("id,soldier_id,url,category,posted_at").eq("id", post_id).execute()
            if getattr(post, "error", None):
                return False, f"Error: {post.error}"
            if not post.data:
                return False, "Post not found"
            record = post.data[0]
            if record["soldier_id"] not in allowed_ids:
                return False, "Not authorized"

            if isinstance(posted_at, date) and not isinstance(posted_at, datetime):
                posted_dt = datetime.combine(posted_at, time.min).replace(tzinfo=timezone.utc)
            else:
                posted_dt = posted_at
                if posted_dt.tzinfo is None:
                    posted_dt = posted_dt.replace(tzinfo=timezone.utc)

            url = record.get("url") or ""
            is_auto = url.endswith("#auto-se")
            new_category = "SE" if is_auto else category

            resp = self.supabase.table("posts").update({
                "category": new_category,
                "posted_at": posted_dt.isoformat(),
            }).eq("id", post_id).execute()
            if getattr(resp, "error", None):
                return False, f"Error: {resp.error}"

            if not is_auto:
                base_url = url.replace("#auto-se", "")
                auto_url = f"{base_url}#auto-se"
                if new_category == "TM":
                    auto = self.supabase.table("posts").select("id").eq("soldier_id", record["soldier_id"]).eq("url", auto_url).execute()
                    if getattr(auto, "error", None):
                        return False, f"Error: {auto.error}"
                    if auto.data:
                        upd = self.supabase.table("posts").update({
                            "category": "SE",
                            "posted_at": posted_dt.isoformat(),
                            "units": 6,
                        }).eq("id", auto.data[0]["id"]).execute()
                        if getattr(upd, "error", None):
                            return False, f"Error: {upd.error}"
                    else:
                        ins = self.supabase.table("posts").insert({
                            "soldier_id": record["soldier_id"],
                            "category": "SE",
                            "url": auto_url,
                            "units": 6,
                            "posted_at": posted_dt.isoformat(),
                            "submitted_at": datetime.now(timezone.utc).isoformat(),
                            "likes": 0,
                            "reposts": 0,
                            "views": 0,
                            "raw_meta": {},
                        }).execute()
                        if getattr(ins, "error", None):
                            return False, f"Error: {ins.error}"
                else:
                    delete_auto = self.supabase.table("posts").delete().eq("soldier_id", record["soldier_id"]).eq("url", auto_url).execute()
                    if getattr(delete_auto, "error", None):
                        return False, f"Error: {delete_auto.error}"

            # Confirm update applied
            check = self.supabase.table("posts").select("category,posted_at").eq("id", post_id).execute()
            if getattr(check, "error", None):
                return False, f"Error: {check.error}"
            if not check.data:
                return False, "Update failed (row missing)"
            current = check.data[0]
            current_category = current.get("category")
            if current_category != new_category:
                return False, "Update failed (category unchanged)"
            current_posted = current.get("posted_at")
            try:
                if isinstance(current_posted, str):
                    current_dt = datetime.fromisoformat(current_posted.replace("Z", "+00:00"))
                else:
                    current_dt = current_posted
                if current_dt and current_dt.date() != posted_dt.date():
                    return False, "Update failed (date unchanged)"
            except Exception:
                # If parsing fails, don't block success
                pass
            return True, "Updated"
        except Exception as e:
            return False, f"Error: {e}"

    def set_auth_session(self, access_token: str, refresh_token: str) -> None:
        self.supabase.auth.set_session(access_token, refresh_token)
        # Ensure PostgREST requests use the authenticated JWT.
        try:
            self.supabase.postgrest.auth(access_token)
        except Exception:
            pass
