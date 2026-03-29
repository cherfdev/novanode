#!/usr/bin/env python3
"""
NovaNode HyperDL
Premium DataNodes downloader with per-link progress bars, pause/resume,
and persistent sessions.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


APP_NAME = "NovaNode HyperDL"
APP_TAGLINE = "SaaS-grade multi-source direct downloader"
SETTINGS_FILE = Path(__file__).with_name("novanode_settings.json")
SESSION_FILE = Path(__file__).with_name("novanode_session.json")
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "NovaNode"


STATUS_PENDING = "pending"
STATUS_RESOLVING = "resolving"
STATUS_READY = "ready"
STATUS_DOWNLOADING = "downloading"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class PauseSignal(Exception):
    pass


class StopSignal(Exception):
    pass


class DirectLinkExpired(Exception):
    pass


@dataclass
class AppSettings:
    timeout_seconds: float = 30.0
    resolve_retries: int = 3
    download_retries: int = 3
    chunk_kb: int = 512
    auto_save_session: bool = True
    gofile_token: str = ""
    create_project_subfolder: bool = False
    project_folder_name: str = ""
    auto_resume_on_startup: bool = True


@dataclass
class QueueItem:
    item_id: str
    source_link: str
    file_id: str
    file_name: str
    provider: str = "auto"
    direct_link: str = ""
    status: str = STATUS_PENDING
    progress: float = 0.0
    downloaded: int = 0
    total: int = 0
    speed_bps: float = 0.0
    error: str = ""
    output_name: str = ""
    updated_at: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.utcnow().isoformat()


class DatanodesResolver:
    BASE_URL = "https://datanodes.to/download"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )

    def parse_link(self, link: str) -> tuple[str, str]:
        raw = link.strip()
        if not raw:
            raise ValueError("Empty link")

        parsed = urlparse(raw)
        if not parsed.scheme:
            parsed = urlparse(f"https://{raw}")

        host = parsed.netloc.lower()
        if "datanodes.to" not in host:
            raise ValueError("Not a datanodes.to link")

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Invalid DataNodes path. Expected /<id>/<name>")

        return parts[0], parts[1]

    @staticmethod
    def _clean_url(value: str) -> str:
        return unquote(value).replace("\r", "").replace("\n", "").replace("\t", "").strip()

    def _extract_url(self, response: requests.Response) -> str:
        header_location = response.headers.get("Location")
        if header_location:
            return self._clean_url(header_location)

        try:
            payload = response.json()
            if isinstance(payload, dict):
                for key in ("url", "direct_url", "link", "direct"):
                    maybe = payload.get(key)
                    if isinstance(maybe, str) and maybe.strip():
                        return self._clean_url(maybe)
        except ValueError:
            pass

        text = response.text.strip()
        if text.startswith("http://") or text.startswith("https://"):
            return self._clean_url(text)

        found = re.search(r"https?://[^\s\"'<>]+", text)
        if found:
            return self._clean_url(found.group(0))

        raise ValueError("No direct URL found in DataNodes response")

    def resolve(self, source_link: str) -> tuple[str, str, str]:
        file_id, file_name = self.parse_link(source_link)

        payload_1 = {
            "op": "download1",
            "usr_login": "",
            "id": file_id,
            "fname": file_name,
            "referer": "",
            "method_free": "Free Download >>",
        }
        r1 = self.session.post(self.BASE_URL, data=payload_1, timeout=self.timeout)
        r1.raise_for_status()

        payload_2 = {
            "op": "download2",
            "id": file_id,
            "rand": "",
            "referer": self.BASE_URL,
            "method_free": "Free Download >>",
            "method_premium": "",
            "g_captch__a": "1",
        }
        r2 = self.session.post(
            self.BASE_URL,
            data=payload_2,
            timeout=self.timeout,
            allow_redirects=False,
        )
        r2.raise_for_status()

        direct = self._extract_url(r2)
        return file_id, file_name, direct


@dataclass
class ResolvedLink:
    provider: str
    file_id: str
    file_name: str
    direct_url: str
    size: int = 0


class MultiHostResolver:
    def __init__(self, timeout_seconds: float, gofile_token: str = "") -> None:
        self.timeout = timeout_seconds
        self.gofile_token = gofile_token.strip()
        self.datanodes = DatanodesResolver(timeout_seconds=timeout_seconds)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DatanodesResolver.USER_AGENT})

    def detect_provider(self, source_link: str) -> str:
        parsed = urlparse(source_link if "://" in source_link else f"https://{source_link}")
        host = parsed.netloc.lower()

        if "datanodes.to" in host:
            return "datanodes"
        if "pixeldrain.com" in host:
            return "pixeldrain"
        if "mediafire.com" in host:
            return "mediafire"
        if "gofile.io" in host:
            return "gofile"
        if host:
            return "direct"
        raise ValueError("Unsupported URL format")

    def infer_from_url(self, source_link: str) -> tuple[str, str, str]:
        provider = self.detect_provider(source_link)
        parsed = urlparse(source_link if "://" in source_link else f"https://{source_link}")
        parts = [part for part in parsed.path.split("/") if part]

        if provider == "datanodes":
            file_id, file_name = self.datanodes.parse_link(source_link)
            return provider, file_id, sanitize_file_name(file_name)

        if provider == "pixeldrain":
            file_id = ""
            if len(parts) >= 2 and parts[0] in {"u", "file"}:
                file_id = parts[1]
            elif len(parts) >= 3 and parts[0] == "api" and parts[1] == "file":
                file_id = parts[2]
            file_id = file_id or uuid.uuid4().hex[:8]
            return provider, file_id, f"{file_id}.bin"

        if provider == "mediafire":
            if len(parts) >= 3 and parts[0] == "file":
                return provider, parts[1], sanitize_file_name(parts[2])
            guessed = guess_name_from_url(source_link)
            return provider, uuid.uuid4().hex[:8], guessed

        if provider == "gofile":
            if len(parts) >= 2 and parts[0] == "d":
                content_id = parts[1]
            else:
                content_id = parts[-1] if parts else uuid.uuid4().hex[:8]
            return provider, content_id, f"{content_id}.bin"

        guessed = guess_name_from_url(source_link)
        return provider, uuid.uuid4().hex[:8], guessed

    def resolve(self, source_link: str, depth: int = 0) -> ResolvedLink:
        if depth > 4:
            raise RuntimeError("Too many chained redirects while resolving link")

        provider = self.detect_provider(source_link)
        if provider == "datanodes":
            return self._resolve_datanodes(source_link)
        if provider == "pixeldrain":
            return self._resolve_pixeldrain(source_link)
        if provider == "mediafire":
            return self._resolve_mediafire(source_link)
        if provider == "gofile":
            return self._resolve_gofile(source_link)
        return self._resolve_direct(source_link, depth=depth)

    def _resolve_datanodes(self, source_link: str) -> ResolvedLink:
        file_id, file_name, direct = self.datanodes.resolve(source_link)
        return ResolvedLink(
            provider="datanodes",
            file_id=file_id,
            file_name=sanitize_file_name(file_name),
            direct_url=direct,
        )

    def _resolve_pixeldrain(self, source_link: str) -> ResolvedLink:
        provider, file_id, fallback_name = self.infer_from_url(source_link)
        _ = provider
        direct = f"https://pixeldrain.com/api/file/{file_id}?download"
        file_name = fallback_name
        file_size = 0

        try:
            info = self.session.get(
                f"https://pixeldrain.com/api/file/{file_id}/info",
                timeout=self.timeout,
            )
            if info.ok:
                payload = info.json()
                if isinstance(payload, dict):
                    if payload.get("name"):
                        file_name = sanitize_file_name(str(payload["name"]))
                    if payload.get("size"):
                        file_size = int(payload["size"])
        except Exception:
            pass

        return ResolvedLink(
            provider="pixeldrain",
            file_id=file_id,
            file_name=file_name,
            direct_url=direct,
            size=file_size,
        )

    def _resolve_mediafire(self, source_link: str) -> ResolvedLink:
        response = self.session.get(
            source_link,
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        html = response.text

        patterns = [
            r'class=["\'][^"\']*popsok[^"\']*["\'][^>]*href=["\']([^"\']+)["\']',
            r'id=["\']downloadButton["\'][^>]*href=["\']([^"\']+)["\']',
            r'href=["\'](https?://download[^"\']*mediafire\.com[^"\']+)["\']',
        ]

        direct = ""
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                direct = unescape(match.group(1))
                break

        if not direct:
            raise RuntimeError("MediaFire direct link not found on page")

        direct = urljoin(response.url, direct)
        file_name = guess_name_from_url(direct) or guess_name_from_url(source_link)
        provider, file_id, _ = self.infer_from_url(source_link)
        _ = provider

        return ResolvedLink(
            provider="mediafire",
            file_id=file_id,
            file_name=sanitize_file_name(file_name),
            direct_url=direct,
        )

    def _resolve_gofile(self, source_link: str) -> ResolvedLink:
        if not self.gofile_token:
            raise RuntimeError("GoFile token is required. Add your API token in settings.")

        provider, content_id, _ = self.infer_from_url(source_link)
        _ = provider
        endpoint = f"https://api.gofile.io/contents/{content_id}"

        response = self.session.get(
            endpoint,
            headers={"Authorization": f"Bearer {self.gofile_token}"},
            params={
                "cache": "true",
                "sortField": "createTime",
                "sortDirection": "1",
                "maxdepth": "10",
            },
            timeout=self.timeout,
        )

        if response.status_code == 401:
            raise RuntimeError("GoFile token invalid or expired")

        payload = response.json()
        status = payload.get("status")
        if status != "ok":
            raise RuntimeError(f"GoFile API error: {status}")

        data = payload.get("data", {})
        node = self._extract_first_file(data)
        if not node:
            raise RuntimeError("No downloadable file found in GoFile content")

        direct = str(node.get("link", "")).strip()
        if not direct:
            raise RuntimeError("GoFile did not return a direct file link")

        file_name = sanitize_file_name(str(node.get("name") or f"{content_id}.bin"))
        file_id = str(node.get("id") or content_id)
        size = int(node.get("size") or 0)

        return ResolvedLink(
            provider="gofile",
            file_id=file_id,
            file_name=file_name,
            direct_url=direct,
            size=size,
        )

    def _extract_first_file(self, data: dict[str, Any]) -> dict[str, Any] | None:
        if data.get("type") == "file":
            return data

        children = data.get("children")
        if isinstance(children, dict):
            for child_id in children:
                child = children[child_id]
                if not isinstance(child, dict):
                    continue
                if child.get("type") == "file":
                    return child
                nested = self._extract_first_file(child)
                if nested:
                    return nested

        return None

    def _resolve_direct(self, source_link: str, depth: int = 0) -> ResolvedLink:
        response = self.session.get(
            source_link,
            timeout=self.timeout,
            allow_redirects=True,
            stream=True,
        )

        try:
            final_url = response.url or source_link
            detected = self.detect_provider(final_url)
            if detected != "direct":
                return self.resolve(final_url, depth=depth + 1)

            content_type = response.headers.get("Content-Type", "").lower()
            disposition = response.headers.get("Content-Disposition", "")

            if "text/html" in content_type and "attachment" not in disposition.lower():
                html = response.text
                redirect_match = re.search(
                    r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\']+)["\']',
                    html,
                    re.IGNORECASE,
                )
                if redirect_match:
                    next_url = urljoin(final_url, unescape(redirect_match.group(1).strip()))
                    return self.resolve(next_url, depth=depth + 1)

                href_match = re.search(
                    r'href=["\'](https?://[^"\']+download[^"\']*)["\']',
                    html,
                    re.IGNORECASE,
                )
                if href_match:
                    next_url = unescape(href_match.group(1))
                    return self.resolve(next_url, depth=depth + 1)

                raise RuntimeError(
                    "Unsupported ad/landing page. Add its real host provider to continue."
                )

            file_name = file_name_from_disposition(disposition) or guess_name_from_url(final_url)
            file_name = sanitize_file_name(file_name)
            size = int(response.headers.get("Content-Length", "0") or 0)

            return ResolvedLink(
                provider="direct",
                file_id=uuid.uuid4().hex[:8],
                file_name=file_name,
                direct_url=final_url,
                size=size,
            )
        finally:
            response.close()


class SequentialDownloadEngine:
    def __init__(
        self,
        items: list[QueueItem],
        output_dir: Path,
        settings: AppSettings,
        event_queue: queue.Queue[dict[str, Any]],
        pause_event: threading.Event,
        stop_event: threading.Event,
    ) -> None:
        self.items = items
        self.output_dir = output_dir
        self.settings = settings
        self.event_queue = event_queue
        self.pause_event = pause_event
        self.stop_event = stop_event
        self.resolver = MultiHostResolver(
            timeout_seconds=settings.timeout_seconds,
            gofile_token=settings.gofile_token,
        )
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": DatanodesResolver.USER_AGENT})

    def emit(self, payload: dict[str, Any]) -> None:
        self.event_queue.put(payload)

    def log(self, message: str, level: str = "info") -> None:
        self.emit({"type": "log", "level": level, "message": message})

    def update_item(self, item: QueueItem) -> None:
        item.touch()
        self.emit({"type": "item_update", "item": asdict(item)})

    def run(self) -> None:
        total = len(self.items)
        self.log(f"Queue started with {total} item(s).", "info")

        for item in self.items:
            if self.stop_event.is_set():
                break
            if item.status == STATUS_COMPLETED:
                continue

            while not self.stop_event.is_set():
                try:
                    self._wait_if_paused()
                    self._process_item(item)
                    break
                except PauseSignal:
                    item.status = STATUS_PAUSED
                    self.update_item(item)
                    self.log(f"Paused: {item.source_link}", "warn")
                    continue
                except StopSignal:
                    item.status = STATUS_PAUSED
                    self.update_item(item)
                    break
                except Exception as exc:  # noqa: BLE001
                    item.status = STATUS_FAILED
                    item.error = str(exc)
                    self.update_item(item)
                    self.log(f"Failed: {item.source_link} ({exc})", "error")
                    break

        self.emit({"type": "queue_done"})

    def _wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.2)
        if self.stop_event.is_set():
            raise StopSignal()

    def _process_item(self, item: QueueItem) -> None:
        item.error = ""
        item.speed_bps = 0.0

        self._resolve_direct_link(item)
        self._download_item(item)

    def _resolve_direct_link(self, item: QueueItem) -> None:
        item.status = STATUS_RESOLVING
        self.update_item(item)

        last_error: Exception | None = None
        for attempt in range(self.settings.resolve_retries + 1):
            if self.stop_event.is_set():
                raise StopSignal()
            if self.pause_event.is_set():
                raise PauseSignal()
            try:
                resolved = self.resolver.resolve(item.source_link)
                item.file_id = resolved.file_id
                item.file_name = resolved.file_name
                item.provider = resolved.provider
                item.output_name = item.output_name or sanitize_file_name(resolved.file_name)
                item.direct_link = resolved.direct_url
                if resolved.size > 0:
                    item.total = resolved.size
                    if item.downloaded > 0:
                        item.progress = min(99.0, (item.downloaded / resolved.size) * 100.0)
                item.status = STATUS_READY
                self.update_item(item)
                self.log(f"[{item.provider}] direct link ready: {item.file_name}", "success")
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.settings.resolve_retries:
                    wait_for = 0.8 * (2**attempt)
                    self.log(
                        f"Resolve retry {attempt + 1}/{self.settings.resolve_retries} for {item.file_name or item.source_link}",
                        "warn",
                    )
                    self._interruptible_sleep(wait_for)

        raise RuntimeError(f"Could not resolve direct link: {last_error}")

    def _download_item(self, item: QueueItem) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        filename = item.output_name or sanitize_file_name(item.file_name or f"file_{item.item_id}")
        target_path = self.output_dir / filename
        part_path = target_path.with_suffix(target_path.suffix + ".part")

        for attempt in range(self.settings.download_retries + 1):
            if self.stop_event.is_set():
                raise StopSignal()
            if self.pause_event.is_set():
                raise PauseSignal()

            try:
                self._download_stream(item, target_path, part_path)
                item.status = STATUS_COMPLETED
                item.progress = 100.0
                item.speed_bps = 0.0
                item.error = ""
                item.output_name = filename
                self.update_item(item)
                self.log(f"Completed: {filename}", "success")
                return
            except DirectLinkExpired:
                item.direct_link = ""
                self.log(f"Refreshing expired direct link for {filename}", "warn")
                self._resolve_direct_link(item)
            except PauseSignal:
                raise
            except StopSignal:
                raise
            except Exception as exc:  # noqa: BLE001
                if attempt < self.settings.download_retries:
                    wait_for = 1.0 * (2**attempt)
                    self.log(
                        f"Download retry {attempt + 1}/{self.settings.download_retries} for {filename} ({exc})",
                        "warn",
                    )
                    self._interruptible_sleep(wait_for)
                else:
                    raise RuntimeError(f"Download failed: {exc}") from exc

    def _download_stream(self, item: QueueItem, target_path: Path, part_path: Path) -> None:
        resume_from = part_path.stat().st_size if part_path.exists() else 0
        headers: dict[str, str] = {}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"

        if not item.direct_link:
            raise DirectLinkExpired("Missing direct link")

        response = self.http.get(
            item.direct_link,
            headers=headers,
            stream=True,
            timeout=self.settings.timeout_seconds,
            allow_redirects=True,
        )

        if response.status_code in (401, 403, 404):
            raise DirectLinkExpired(f"HTTP {response.status_code}")

        if response.status_code == 416:
            if part_path.exists():
                if target_path.exists():
                    target_path.unlink()
                part_path.replace(target_path)
            item.downloaded = target_path.stat().st_size if target_path.exists() else 0
            item.total = item.downloaded
            item.progress = 100.0
            self.update_item(item)
            return

        response.raise_for_status()

        if resume_from > 0 and response.status_code == 200:
            # Server ignored range; restart from zero.
            part_path.unlink(missing_ok=True)
            resume_from = 0

        total = detect_total_bytes(response, resume_from)
        item.total = total
        item.downloaded = resume_from
        item.status = STATUS_DOWNLOADING
        self.update_item(item)

        chunk_size = max(64 * 1024, self.settings.chunk_kb * 1024)
        mode = "ab" if resume_from > 0 else "wb"
        last_emit = time.time()
        speed_window_start = time.time()
        speed_window_bytes = 0

        with part_path.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if self.stop_event.is_set():
                    raise StopSignal()
                if self.pause_event.is_set():
                    item.status = STATUS_PAUSED
                    self.update_item(item)
                    raise PauseSignal()
                if not chunk:
                    continue

                handle.write(chunk)
                chunk_len = len(chunk)
                item.downloaded += chunk_len
                speed_window_bytes += chunk_len

                now = time.time()
                if now - speed_window_start >= 0.5:
                    elapsed = max(0.001, now - speed_window_start)
                    item.speed_bps = speed_window_bytes / elapsed
                    speed_window_start = now
                    speed_window_bytes = 0

                if item.total > 0:
                    item.progress = min(100.0, (item.downloaded / item.total) * 100.0)

                if now - last_emit >= 0.2:
                    self.update_item(item)
                    last_emit = now

        if target_path.exists():
            target_path.unlink()
        part_path.replace(target_path)

        item.downloaded = target_path.stat().st_size
        if item.total <= 0:
            item.total = item.downloaded
        item.progress = 100.0
        self.update_item(item)

    def _interruptible_sleep(self, seconds: float) -> None:
        end_time = time.time() + max(0.0, seconds)
        while time.time() < end_time:
            if self.stop_event.is_set():
                raise StopSignal()
            if self.pause_event.is_set():
                raise PauseSignal()
            time.sleep(0.1)


class QueueRow:
    def __init__(self, parent: tk.Widget, item: QueueItem, colors: dict[str, str]) -> None:
        self.item_id = item.item_id
        self.colors = colors

        self.frame = tk.Frame(parent, bg=colors["card"], highlightthickness=1, highlightbackground=colors["line"])
        self.frame.pack(fill="x", padx=8, pady=5)

        self.top = tk.Frame(self.frame, bg=colors["card"])
        self.top.pack(fill="x", padx=10, pady=(8, 4))

        self.source_var = tk.StringVar(value=item.source_link)
        self.status_var = tk.StringVar(value=item.status.upper())
        self.meta_var = tk.StringVar(value="0 B / 0 B")
        self.percent_var = tk.StringVar(value="0%")

        self.source_label = tk.Label(
            self.top,
            textvariable=self.source_var,
            bg=colors["card"],
            fg=colors["text"],
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
        )
        self.source_label.pack(side="left", fill="x", expand=True)

        self.status_chip = tk.Label(
            self.top,
            textvariable=self.status_var,
            bg=colors["chip_pending"],
            fg=colors["chip_text"],
            font=("Segoe UI Semibold", 9),
            padx=8,
            pady=3,
        )
        self.status_chip.pack(side="right")

        self.bottom = tk.Frame(self.frame, bg=colors["card"])
        self.bottom.pack(fill="x", padx=10, pady=(2, 9))

        self.progress = ttk.Progressbar(self.bottom, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)

        self.percent_label = tk.Label(
            self.bottom,
            textvariable=self.percent_var,
            bg=colors["card"],
            fg=colors["muted"],
            font=("Segoe UI", 9),
            width=6,
            anchor="e",
        )
        self.percent_label.pack(side="left", padx=(8, 0))

        self.meta_label = tk.Label(
            self.frame,
            textvariable=self.meta_var,
            bg=colors["card"],
            fg=colors["muted"],
            font=("Consolas", 9),
            anchor="w",
        )
        self.meta_label.pack(fill="x", padx=10, pady=(0, 8))

        self.update(item)

    def update(self, item: QueueItem) -> None:
        provider = item.provider.upper() if item.provider else "AUTO"
        self.source_var.set(f"[{provider}] {item.source_link}")
        self.status_var.set(item.status.upper())
        self.percent_var.set(f"{item.progress:5.1f}%" if item.progress > 0 else "0%")
        self.progress["value"] = item.progress

        status_color = {
            STATUS_PENDING: self.colors["chip_pending"],
            STATUS_RESOLVING: self.colors["chip_running"],
            STATUS_READY: self.colors["chip_running"],
            STATUS_DOWNLOADING: self.colors["chip_running"],
            STATUS_PAUSED: self.colors["chip_paused"],
            STATUS_COMPLETED: self.colors["chip_success"],
            STATUS_FAILED: self.colors["chip_error"],
        }.get(item.status, self.colors["chip_pending"])
        self.status_chip.configure(bg=status_color)

        extra = ""
        if item.speed_bps > 0 and item.status == STATUS_DOWNLOADING:
            extra = f" | {format_speed(item.speed_bps)}"
        if item.error:
            extra = f" | ERR: {item.error}"

        self.meta_var.set(f"{format_bytes(item.downloaded)} / {format_bytes(item.total)}{extra}")


def format_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.2f} {units[idx]}"


def format_speed(value: float) -> str:
    if value <= 0:
        return "0 B/s"
    return f"{format_bytes(int(value))}/s"


def detect_total_bytes(response: requests.Response, resume_from: int) -> int:
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            return int(content_range.split("/")[-1])
        except ValueError:
            pass

    length = response.headers.get("Content-Length")
    if length and length.isdigit():
        size = int(length)
        return size + resume_from if response.status_code == 206 else size

    return 0


def sanitize_file_name(name: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*]+", "_", name).strip(" .")
    cleaned = cleaned or f"file_{uuid.uuid4().hex[:8]}"
    return cleaned[:180]


def guess_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if name and "." in name:
        return sanitize_file_name(name)
    if name:
        return sanitize_file_name(f"{name}.bin")
    return sanitize_file_name(f"file_{uuid.uuid4().hex[:8]}.bin")


def file_name_from_disposition(content_disposition: str) -> str:
    if not content_disposition:
        return ""

    star_match = re.search(r"filename\\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
    if star_match:
        return sanitize_file_name(unquote(star_match.group(1).strip().strip('\"')))

    match = re.search(r'filename=\"?([^\";]+)\"?', content_disposition, re.IGNORECASE)
    if match:
        return sanitize_file_name(match.group(1).strip())

    return ""


class NovaNodeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_NAME} - Multi-Source Downloader")
        self.geometry("1460x880")
        self.minsize(1220, 720)

        self.colors = {
            "bg": "#060F1A",
            "panel": "#0D1626",
            "card": "#142236",
            "line": "#1F334D",
            "text": "#E2ECF7",
            "muted": "#9FB2C8",
            "accent": "#26C4FF",
            "accent_2": "#35E0A1",
            "danger": "#FF6B7A",
            "warning": "#FFB84D",
            "chip_text": "#06101A",
            "chip_pending": "#8CA4BE",
            "chip_running": "#26C4FF",
            "chip_paused": "#FFB84D",
            "chip_success": "#35E0A1",
            "chip_error": "#FF6B7A",
        }

        self.configure(bg=self.colors["bg"])

        self.settings = AppSettings()
        self.output_dir_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.timeout_var = tk.DoubleVar(value=self.settings.timeout_seconds)
        self.resolve_retries_var = tk.IntVar(value=self.settings.resolve_retries)
        self.download_retries_var = tk.IntVar(value=self.settings.download_retries)
        self.chunk_kb_var = tk.IntVar(value=self.settings.chunk_kb)
        self.auto_save_var = tk.BooleanVar(value=True)
        self.gofile_token_var = tk.StringVar(value="")
        self.create_subfolder_var = tk.BooleanVar(value=False)
        self.project_folder_var = tk.StringVar(value="")
        self.auto_resume_var = tk.BooleanVar(value=True)
        self.active_output_dir = str(DEFAULT_OUTPUT_DIR)

        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="Queue: 0 | Completed: 0 | Failed: 0 | Active: 0")

        self.items: list[QueueItem] = []
        self.rows: dict[str, QueueRow] = {}

        self.event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None

        self._build_styles()
        self._build_ui()
        self._load_settings()
        self._drain_events()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if SESSION_FILE.exists():
            if self.auto_resume_var.get():
                self._log("Previous session detected. Auto-restore is enabled.", "info")
                self.after(600, self._auto_restore_and_resume)
            else:
                self._log("Previous session file detected. Use Restore Session to continue later.", "warn")

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("Base.TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])

        style.configure(
            "Primary.TButton",
            background=self.colors["accent"],
            foreground="#03121F",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Primary.TButton", background=[("active", "#66D9FF"), ("disabled", "#0C3F57")])

        style.configure(
            "Success.TButton",
            background=self.colors["accent_2"],
            foreground="#042017",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Success.TButton", background=[("active", "#7DF0BE"), ("disabled", "#1C5A44")])

        style.configure(
            "Warn.TButton",
            background=self.colors["warning"],
            foreground="#2A1300",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Warn.TButton", background=[("active", "#FFD193"), ("disabled", "#855B1E")])

        style.configure(
            "Danger.TButton",
            background=self.colors["danger"],
            foreground="#2A0A0E",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Danger.TButton", background=[("active", "#FF99A6"), ("disabled", "#6D2330")])

        style.configure(
            "Ghost.TButton",
            background=self.colors["card"],
            foreground=self.colors["text"],
            bordercolor=self.colors["line"],
            borderwidth=1,
            padding=(12, 8),
        )
        style.map("Ghost.TButton", background=[("active", "#1D3048")])

        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor="#112033",
            background=self.colors["accent"],
            bordercolor=self.colors["line"],
            darkcolor=self.colors["accent"],
            lightcolor=self.colors["accent"],
        )

    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=self.colors["bg"])
        root.pack(fill="both", expand=True, padx=16, pady=14)

        header = tk.Frame(root, bg=self.colors["bg"])
        header.pack(fill="x", pady=(0, 12))

        title = tk.Label(
            header,
            text=APP_NAME,
            bg=self.colors["bg"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 22),
        )
        title.pack(anchor="w")
        subtitle = tk.Label(
            header,
            text=(
                f"{APP_TAGLINE} | Sequential downloads | Pause now, resume later | "
                "Providers: DataNodes, PixelDrain, MediaFire, GoFile(token), Direct/Redirect"
            ),
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        subtitle.pack(anchor="w")

        controls = tk.Frame(root, bg=self.colors["panel"], highlightthickness=1, highlightbackground=self.colors["line"])
        controls.pack(fill="x", pady=(0, 10))

        top_controls = tk.Frame(controls, bg=self.colors["panel"])
        top_controls.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(top_controls, text="Output folder", bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="left")
        output_entry = ttk.Entry(top_controls, textvariable=self.output_dir_var, width=56)
        output_entry.pack(side="left", padx=(8, 6))
        ttk.Button(top_controls, text="Browse", style="Ghost.TButton", command=self._pick_output_dir).pack(side="left")

        tk.Label(
            top_controls,
            text="Project folder",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(14, 6))
        ttk.Entry(top_controls, textvariable=self.project_folder_var, width=24).pack(side="left")

        ttk.Button(top_controls, text="Save Session", style="Ghost.TButton", command=self._save_session).pack(side="right")
        ttk.Button(top_controls, text="Restore Session", style="Ghost.TButton", command=self._restore_session).pack(
            side="right", padx=(0, 8)
        )

        settings = tk.Frame(controls, bg=self.colors["panel"])
        settings.pack(fill="x", padx=12, pady=(0, 10))

        self._create_setting(settings, "Timeout (s)", self.timeout_var, 0)
        self._create_setting(settings, "Resolve retries", self.resolve_retries_var, 1)
        self._create_setting(settings, "Download retries", self.download_retries_var, 2)
        self._create_setting(settings, "Chunk (KB)", self.chunk_kb_var, 3)

        tk.Label(
            settings,
            text="GoFile API token",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=8, padx=(12, 6), sticky="w")
        token_entry = ttk.Entry(settings, textvariable=self.gofile_token_var, width=34, show="*")
        token_entry.grid(row=0, column=9, padx=(0, 8), sticky="w")

        auto_save = ttk.Checkbutton(settings, text="Auto-save session", variable=self.auto_save_var)
        auto_save.grid(row=0, column=10, padx=(4, 0), sticky="w")
        create_subfolder = ttk.Checkbutton(
            settings,
            text="Create project subfolder",
            variable=self.create_subfolder_var,
        )
        create_subfolder.grid(row=0, column=11, padx=(12, 0), sticky="w")
        auto_resume = ttk.Checkbutton(
            settings,
            text="Auto resume on startup",
            variable=self.auto_resume_var,
        )
        auto_resume.grid(row=0, column=12, padx=(12, 0), sticky="w")

        main = tk.Frame(root, bg=self.colors["bg"])
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg=self.colors["panel"], highlightthickness=1, highlightbackground=self.colors["line"])
        left.pack(side="left", fill="both", expand=False, padx=(0, 8))

        right = tk.Frame(main, bg=self.colors["panel"], highlightthickness=1, highlightbackground=self.colors["line"])
        right.pack(side="left", fill="both", expand=True)

        left_header = tk.Frame(left, bg=self.colors["panel"])
        left_header.pack(fill="x", padx=12, pady=(10, 8))
        tk.Label(left_header, text="Input links", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(
            left_header,
            text="One supported URL per line. Click Add to Queue.",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        self.input_text = ScrolledText(
            left,
            width=52,
            height=20,
            wrap="word",
            bg="#102037",
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.input_text.pack(fill="both", expand=True, padx=12)
        self.input_text.insert(
            "1.0",
            "# Paste supported links here\n"
            "# https://datanodes.to/<id>/<filename>\n"
            "# https://pixeldrain.com/u/<id>\n"
            "# https://www.mediafire.com/file/<id>/<name>/file\n"
            "# https://gofile.io/d/<id>  (requires token)\n",
        )

        left_actions = tk.Frame(left, bg=self.colors["panel"])
        left_actions.pack(fill="x", padx=12, pady=10)

        ttk.Button(left_actions, text="Import .txt", style="Ghost.TButton", command=self._import_txt).pack(side="left")
        ttk.Button(left_actions, text="Add to Queue", style="Primary.TButton", command=self._add_links_to_queue).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(left_actions, text="Clear Input", style="Ghost.TButton", command=self._clear_input).pack(side="left", padx=(6, 0))

        queue_header = tk.Frame(right, bg=self.colors["panel"])
        queue_header.pack(fill="x", padx=12, pady=(10, 8))

        tk.Label(queue_header, text="Download Queue", bg=self.colors["panel"], fg=self.colors["text"], font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(
            queue_header,
            text="One-by-one download with per-link progress bars",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        queue_actions = tk.Frame(right, bg=self.colors["panel"])
        queue_actions.pack(fill="x", padx=12, pady=(0, 8))

        self.start_btn = ttk.Button(queue_actions, text="Start Queue", style="Success.TButton", command=self._start_queue)
        self.start_btn.pack(side="left")

        self.pause_btn = ttk.Button(queue_actions, text="Pause", style="Warn.TButton", command=self._pause_queue, state="disabled")
        self.pause_btn.pack(side="left", padx=(6, 0))

        self.resume_btn = ttk.Button(queue_actions, text="Resume", style="Primary.TButton", command=self._resume_queue)
        self.resume_btn.pack(side="left", padx=(6, 0))

        self.stop_btn = ttk.Button(queue_actions, text="Stop", style="Danger.TButton", command=self._stop_queue, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))

        ttk.Button(queue_actions, text="Retry Failed", style="Ghost.TButton", command=self._retry_failed).pack(side="left", padx=(6, 0))
        ttk.Button(queue_actions, text="Clear Completed", style="Ghost.TButton", command=self._clear_completed).pack(side="left", padx=(6, 0))

        self.queue_canvas = tk.Canvas(
            right,
            bg=self.colors["panel"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.queue_canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 10))

        queue_scroll = ttk.Scrollbar(right, orient="vertical", command=self.queue_canvas.yview)
        queue_scroll.pack(side="right", fill="y", padx=(0, 8), pady=(0, 10))
        self.queue_canvas.configure(yscrollcommand=queue_scroll.set)

        self.queue_inner = tk.Frame(self.queue_canvas, bg=self.colors["panel"])
        self.queue_window = self.queue_canvas.create_window((0, 0), window=self.queue_inner, anchor="nw")

        self.queue_inner.bind("<Configure>", self._on_queue_inner_configure)
        self.queue_canvas.bind("<Configure>", self._on_queue_canvas_configure)

        footer = tk.Frame(root, bg=self.colors["panel"], highlightthickness=1, highlightbackground=self.colors["line"])
        footer.pack(fill="x", pady=(10, 0))

        self.global_progress = ttk.Progressbar(footer, style="Custom.Horizontal.TProgressbar", mode="determinate", maximum=100)
        self.global_progress.pack(fill="x", padx=12, pady=(10, 6))

        info_line = tk.Frame(footer, bg=self.colors["panel"])
        info_line.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(info_line, textvariable=self.status_var, bg=self.colors["panel"], fg=self.colors["accent"], font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(info_line, textvariable=self.summary_var, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)).pack(anchor="w")

        self.log_text = ScrolledText(
            footer,
            height=8,
            wrap="word",
            bg="#091726",
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief="flat",
            borderwidth=0,
            font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.pack(fill="x", padx=12, pady=(0, 12))

    def _create_setting(self, parent: tk.Frame, title: str, var: tk.Variable, col_group: int) -> None:
        base = col_group * 2
        tk.Label(parent, text=title, bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)).grid(
            row=0, column=base, padx=(0, 6), sticky="w"
        )
        entry = ttk.Entry(parent, textvariable=var, width=7)
        entry.grid(row=0, column=base + 1, padx=(0, 12), sticky="w")

    def _on_queue_inner_configure(self, _: tk.Event) -> None:
        self.queue_canvas.configure(scrollregion=self.queue_canvas.bbox("all"))

    def _on_queue_canvas_configure(self, event: tk.Event) -> None:
        self.queue_canvas.itemconfigure(self.queue_window, width=event.width)

    def _compute_effective_output_dir(self, settings: AppSettings) -> Path:
        base = Path(self.output_dir_var.get()).expanduser()
        if settings.create_project_subfolder:
            raw_name = settings.project_folder_name.strip()
            if not raw_name:
                raw_name = datetime.now().strftime("session_%Y%m%d_%H%M%S")
            return base / sanitize_file_name(raw_name)
        return base

    def _auto_restore_and_resume(self) -> None:
        if not SESSION_FILE.exists() or not self.auto_resume_var.get():
            return

        restored = self._restore_session(silent=True)
        if not restored:
            return

        resumable = any(
            item.status in {STATUS_PENDING, STATUS_PAUSED, STATUS_FAILED, STATUS_READY, STATUS_RESOLVING}
            for item in self.items
        )
        if resumable:
            self._log("Auto-resume: restarting previous session queue.", "info")
            self._start_queue()

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.exists():
            return

        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._log("Settings file is invalid. Using defaults.", "warn")
            return

        self.timeout_var.set(float(data.get("timeout_seconds", self.timeout_var.get())))
        self.resolve_retries_var.set(int(data.get("resolve_retries", self.resolve_retries_var.get())))
        self.download_retries_var.set(int(data.get("download_retries", self.download_retries_var.get())))
        self.chunk_kb_var.set(int(data.get("chunk_kb", self.chunk_kb_var.get())))
        self.auto_save_var.set(bool(data.get("auto_save_session", True)))
        self.gofile_token_var.set(str(data.get("gofile_token", "")))
        self.create_subfolder_var.set(bool(data.get("create_project_subfolder", False)))
        self.project_folder_var.set(str(data.get("project_folder_name", "")))
        self.auto_resume_var.set(bool(data.get("auto_resume_on_startup", True)))
        self.output_dir_var.set(str(data.get("output_dir", self.output_dir_var.get())))

    def _save_settings(self) -> None:
        payload = {
            "timeout_seconds": self.timeout_var.get(),
            "resolve_retries": self.resolve_retries_var.get(),
            "download_retries": self.download_retries_var.get(),
            "chunk_kb": self.chunk_kb_var.get(),
            "auto_save_session": self.auto_save_var.get(),
            "gofile_token": self.gofile_token_var.get().strip(),
            "create_project_subfolder": self.create_subfolder_var.get(),
            "project_folder_name": self.project_folder_var.get().strip(),
            "auto_resume_on_startup": self.auto_resume_var.get(),
            "output_dir": self.output_dir_var.get(),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            self._log("Unable to save settings file.", "warn")

    def _build_settings(self) -> AppSettings | None:
        try:
            settings = AppSettings(
                timeout_seconds=float(self.timeout_var.get()),
                resolve_retries=int(self.resolve_retries_var.get()),
                download_retries=int(self.download_retries_var.get()),
                chunk_kb=int(self.chunk_kb_var.get()),
                auto_save_session=bool(self.auto_save_var.get()),
                gofile_token=self.gofile_token_var.get().strip(),
                create_project_subfolder=bool(self.create_subfolder_var.get()),
                project_folder_name=self.project_folder_var.get().strip(),
                auto_resume_on_startup=bool(self.auto_resume_var.get()),
            )
        except (TypeError, ValueError):
            messagebox.showerror("Invalid settings", "One or more setting values are invalid.")
            return None

        if settings.timeout_seconds <= 0:
            messagebox.showerror("Invalid settings", "Timeout must be > 0.")
            return None
        if settings.resolve_retries < 0 or settings.resolve_retries > 10:
            messagebox.showerror("Invalid settings", "Resolve retries must be between 0 and 10.")
            return None
        if settings.download_retries < 0 or settings.download_retries > 10:
            messagebox.showerror("Invalid settings", "Download retries must be between 0 and 10.")
            return None
        if settings.chunk_kb < 64 or settings.chunk_kb > 4096:
            messagebox.showerror("Invalid settings", "Chunk size must be between 64 and 4096 KB.")
            return None

        self.settings = settings
        self._save_settings()
        return settings

    def _pick_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir_var.set(folder)

    def _import_txt(self) -> None:
        path = filedialog.askopenfilename(
            title="Import links from text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Import error", str(exc))
            return

        self.input_text.insert("end", f"\n{content.strip()}\n")
        self._log(f"Imported links from {path}", "info")

    def _clear_input(self) -> None:
        self.input_text.delete("1.0", "end")

    def _extract_links_from_input(self) -> list[str]:
        lines = self.input_text.get("1.0", "end").splitlines()
        links: list[str] = []
        for line in lines:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            links.append(value)
        return links

    def _add_links_to_queue(self) -> None:
        links = self._extract_links_from_input()
        if not links:
            messagebox.showwarning("No links", "Please paste at least one supported URL.")
            return

        existing = {item.source_link for item in self.items}
        resolver = MultiHostResolver(
            timeout_seconds=8,
            gofile_token=self.gofile_token_var.get().strip(),
        )

        added = 0
        invalid = 0
        for link in links:
            if link in existing:
                continue

            try:
                provider, file_id, file_name = resolver.infer_from_url(link)
            except Exception as exc:
                self._log(f"Invalid/unsupported URL skipped: {link} ({exc})", "warn")
                invalid += 1
                continue

            item = QueueItem(
                item_id=uuid.uuid4().hex,
                source_link=link,
                file_id=file_id,
                file_name=file_name,
                provider=provider,
                output_name=sanitize_file_name(file_name),
                status=STATUS_PENDING,
            )
            item.touch()
            self.items.append(item)
            self._add_row(item)
            added += 1

        self._refresh_summary()
        self._update_global_progress()
        if self.auto_save_var.get():
            self._save_session(silent=True)

        if added:
            self._log(f"Added {added} link(s) to queue.", "success")
        if invalid:
            self._log(f"Skipped {invalid} invalid link(s).", "warn")

    def _add_row(self, item: QueueItem) -> None:
        row = QueueRow(self.queue_inner, item, self.colors)
        self.rows[item.item_id] = row

    def _clear_rows(self) -> None:
        for row in self.rows.values():
            row.frame.destroy()
        self.rows.clear()

    def _sync_row(self, item: QueueItem) -> None:
        row = self.rows.get(item.item_id)
        if not row:
            self._add_row(item)
            row = self.rows[item.item_id]
        row.update(item)

    def _find_item(self, item_id: str) -> QueueItem | None:
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    def _start_queue(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        if not self.items:
            messagebox.showwarning("Empty queue", "Add links before starting.")
            return

        settings = self._build_settings()
        if not settings:
            return

        output_dir = self._compute_effective_output_dir(settings)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Output error", f"Cannot access output folder:\n{exc}")
            return
        self.active_output_dir = str(output_dir)

        self.stop_event.clear()
        self.pause_event.clear()

        for item in self.items:
            if item.status == STATUS_FAILED:
                item.status = STATUS_PENDING
                item.error = ""
            if item.status == STATUS_PAUSED:
                item.status = STATUS_PENDING
            self._sync_row(item)

        engine = SequentialDownloadEngine(
            items=self.items,
            output_dir=output_dir,
            settings=settings,
            event_queue=self.event_queue,
            pause_event=self.pause_event,
            stop_event=self.stop_event,
        )

        self.worker_thread = threading.Thread(target=engine.run, daemon=True)
        self.worker_thread.start()

        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Running queue...")
        self._log(f"Queue started. Output: {self.active_output_dir}", "info")

    def _pause_queue(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return
        self.pause_event.set()
        self.status_var.set("Pausing...")
        self._log("Pause requested. Current file will pause safely.", "warn")

    def _resume_queue(self) -> None:
        self.pause_event.clear()
        if self.worker_thread and self.worker_thread.is_alive():
            self.status_var.set("Resuming...")
            self._log("Queue resumed.", "info")
            return

        resumable = any(item.status in {STATUS_PAUSED, STATUS_PENDING, STATUS_FAILED} for item in self.items)
        if resumable:
            self._start_queue()

    def _stop_queue(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return
        self.stop_event.set()
        self.pause_event.clear()
        self.status_var.set("Stopping...")
        self._log("Stop requested.", "warn")

    def _retry_failed(self) -> None:
        reset = 0
        for item in self.items:
            if item.status == STATUS_FAILED:
                item.status = STATUS_PENDING
                item.error = ""
                item.progress = 0.0
                item.speed_bps = 0.0
                self._sync_row(item)
                reset += 1
        self._refresh_summary()
        if reset:
            self._log(f"Reset {reset} failed item(s).", "info")
        else:
            self._log("No failed item to retry.", "warn")

    def _clear_completed(self) -> None:
        before = len(self.items)
        self.items = [item for item in self.items if item.status != STATUS_COMPLETED]
        if len(self.items) == before:
            self._log("No completed item to clear.", "warn")
            return

        self._clear_rows()
        for item in self.items:
            self._add_row(item)

        self._refresh_summary()
        self._update_global_progress()
        self._log("Completed items cleared from queue.", "info")
        if self.auto_save_var.get():
            self._save_session(silent=True)

    def _save_session(self, silent: bool = False) -> None:
        data = {
            "app_name": APP_NAME,
            "saved_at": datetime.utcnow().isoformat(),
            "output_dir": self.output_dir_var.get(),
            "active_output_dir": self.active_output_dir,
            "settings": {
                "timeout_seconds": self.timeout_var.get(),
                "resolve_retries": self.resolve_retries_var.get(),
                "download_retries": self.download_retries_var.get(),
                "chunk_kb": self.chunk_kb_var.get(),
                "auto_save_session": self.auto_save_var.get(),
                "gofile_token": self.gofile_token_var.get().strip(),
                "create_project_subfolder": self.create_subfolder_var.get(),
                "project_folder_name": self.project_folder_var.get().strip(),
                "auto_resume_on_startup": self.auto_resume_var.get(),
            },
            "items": [asdict(item) for item in self.items],
        }

        try:
            SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            if not silent:
                self._log(f"Session saved to {SESSION_FILE.name}", "success")
        except OSError as exc:
            if not silent:
                self._log(f"Could not save session: {exc}", "error")

    def _restore_session(self, silent: bool = False) -> bool:
        if not SESSION_FILE.exists():
            if not silent:
                messagebox.showwarning("No session", "No saved session file found.")
            return False

        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if not silent:
                messagebox.showerror("Session error", f"Cannot read session:\n{exc}")
            else:
                self._log(f"Auto-restore failed: {exc}", "error")
            return False

        self.items.clear()
        self._clear_rows()

        settings = data.get("settings", {})
        self.timeout_var.set(float(settings.get("timeout_seconds", self.timeout_var.get())))
        self.resolve_retries_var.set(int(settings.get("resolve_retries", self.resolve_retries_var.get())))
        self.download_retries_var.set(int(settings.get("download_retries", self.download_retries_var.get())))
        self.chunk_kb_var.set(int(settings.get("chunk_kb", self.chunk_kb_var.get())))
        self.auto_save_var.set(bool(settings.get("auto_save_session", self.auto_save_var.get())))
        self.gofile_token_var.set(str(settings.get("gofile_token", self.gofile_token_var.get())))
        self.create_subfolder_var.set(bool(settings.get("create_project_subfolder", self.create_subfolder_var.get())))
        self.project_folder_var.set(str(settings.get("project_folder_name", self.project_folder_var.get())))
        self.auto_resume_var.set(bool(settings.get("auto_resume_on_startup", self.auto_resume_var.get())))

        self.output_dir_var.set(str(data.get("output_dir", self.output_dir_var.get())))
        self.active_output_dir = str(data.get("active_output_dir", self.output_dir_var.get()))

        loaded = 0
        active_dir = Path(self.active_output_dir).expanduser()
        output_base_dir = Path(self.output_dir_var.get()).expanduser()
        for row in data.get("items", []):
            try:
                item = QueueItem(**row)
            except TypeError:
                continue

            if item.status in {STATUS_DOWNLOADING, STATUS_RESOLVING, STATUS_READY}:
                item.status = STATUS_PAUSED

            target_name = item.output_name or sanitize_file_name(item.file_name)
            output_path = active_dir / target_name
            fallback_output_path = output_base_dir / target_name
            if not output_path.exists() and fallback_output_path.exists():
                output_path = fallback_output_path
            part_path = output_path.with_suffix(output_path.suffix + ".part")

            if item.status == STATUS_COMPLETED and not output_path.exists():
                item.status = STATUS_PENDING
                item.progress = 0.0
                item.downloaded = 0
                item.total = 0

            if item.status in {STATUS_PENDING, STATUS_PAUSED, STATUS_FAILED} and part_path.exists():
                item.downloaded = part_path.stat().st_size
                if item.total > 0:
                    item.progress = min(99.0, (item.downloaded / item.total) * 100)
                else:
                    item.progress = 0.0

            item.speed_bps = 0.0
            item.touch()
            self.items.append(item)
            self._add_row(item)
            loaded += 1

        self._refresh_summary()
        self._update_global_progress()
        if loaded == 0:
            self.status_var.set("Ready")
            if not silent:
                self._log("Session restored, but no valid items were found.", "warn")
            return False

        self.status_var.set("Session restored")
        self._log(f"Session restored: {loaded} item(s). Output: {self.active_output_dir}", "success")
        return True

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get("type")
            if event_type == "log":
                self._log(event.get("message", ""), event.get("level", "info"), from_worker=True)
            elif event_type == "item_update":
                payload = event.get("item", {})
                item_id = str(payload.get("item_id", ""))
                item = self._find_item(item_id)
                if item:
                    item.source_link = str(payload.get("source_link", item.source_link))
                    item.file_id = str(payload.get("file_id", item.file_id))
                    item.file_name = str(payload.get("file_name", item.file_name))
                    item.provider = str(payload.get("provider", item.provider))
                    item.direct_link = str(payload.get("direct_link", item.direct_link))
                    item.status = str(payload.get("status", item.status))
                    item.progress = float(payload.get("progress", item.progress))
                    item.downloaded = int(payload.get("downloaded", item.downloaded))
                    item.total = int(payload.get("total", item.total))
                    item.speed_bps = float(payload.get("speed_bps", item.speed_bps))
                    item.error = str(payload.get("error", item.error))
                    item.output_name = str(payload.get("output_name", item.output_name))
                    item.updated_at = str(payload.get("updated_at", item.updated_at))
                    self._sync_row(item)

                self._refresh_summary()
                self._update_global_progress()
                if self.auto_save_var.get():
                    self._save_session(silent=True)

            elif event_type == "queue_done":
                self.start_btn.configure(state="normal")
                self.pause_btn.configure(state="disabled")
                self.stop_btn.configure(state="disabled")

                active = sum(1 for it in self.items if it.status in {STATUS_DOWNLOADING, STATUS_RESOLVING, STATUS_READY})
                self.status_var.set("Paused" if self.pause_event.is_set() else "Queue finished")
                self._refresh_summary()
                self._update_global_progress()
                if active == 0:
                    done = sum(1 for it in self.items if it.status == STATUS_COMPLETED)
                    failed = sum(1 for it in self.items if it.status == STATUS_FAILED)
                    self._log(f"Queue finished. Completed: {done}, Failed: {failed}", "success")
                if self.auto_save_var.get():
                    self._save_session(silent=True)

        self.after(120, self._drain_events)

    def _refresh_summary(self) -> None:
        total = len(self.items)
        completed = sum(1 for item in self.items if item.status == STATUS_COMPLETED)
        failed = sum(1 for item in self.items if item.status == STATUS_FAILED)
        active = sum(
            1 for item in self.items if item.status in {STATUS_DOWNLOADING, STATUS_RESOLVING, STATUS_READY}
        )
        self.summary_var.set(
            f"Queue: {total} | Completed: {completed} | Failed: {failed} | Active: {active}"
        )

    def _update_global_progress(self) -> None:
        total = len(self.items)
        if total == 0:
            self.global_progress["value"] = 0
            return

        aggregate = sum(item.progress for item in self.items) / total
        self.global_progress["value"] = aggregate

    def _log(self, message: str, level: str = "info", from_worker: bool = False) -> None:
        if not message:
            return

        prefix_map = {
            "info": "[INFO]",
            "warn": "[WARN]",
            "error": "[ERROR]",
            "success": "[OK]",
        }
        prefix = prefix_map.get(level, "[INFO]")
        timestamp = time.strftime("%H:%M:%S")
        line = f"{timestamp} {prefix} {message}\n"

        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

        if not from_worker and self.auto_save_var.get() and level in {"error", "success", "warn"}:
            self._save_session(silent=True)

    def _on_close(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        self._save_settings()
        if self.auto_save_var.get():
            self._save_session(silent=True)
        self.destroy()


def main() -> None:
    app = NovaNodeApp()
    app.mainloop()


if __name__ == "__main__":
    main()
