#!/usr/bin/env python3
"""
DN Direct Link Downloader - Python GUI Edition

Desktop application for converting datanodes.to links into direct links.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


CONFIG_FILE = Path(__file__).with_name("downloader_gui_config.json")
DEFAULT_OUTPUT_FILE = "results.txt"


@dataclass
class DownloaderSettings:
    delay_ms: int = 500
    max_retries: int = 3
    timeout_seconds: float = 30.0
    workers: int = 4
    output_file: str = DEFAULT_OUTPUT_FILE


class DatanodesClient:
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
            raise ValueError("Invalid datanodes link")

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Link format is invalid. Expected: datanodes.to/<id>/<name>")

        return parts[0], parts[1]

    @staticmethod
    def _clean_url(value: str) -> str:
        cleaned = unquote(value).replace("\r", "").replace("\n", "").replace("\t", "").strip()
        return cleaned

    def _extract_direct_url(self, response: requests.Response) -> str:
        redirect_header = response.headers.get("Location")
        if redirect_header:
            return self._clean_url(redirect_header)

        try:
            payload = response.json()
            if isinstance(payload, dict):
                for key in ("url", "link", "direct", "direct_url"):
                    maybe = payload.get(key)
                    if isinstance(maybe, str) and maybe.strip():
                        return self._clean_url(maybe)
        except ValueError:
            pass

        text = response.text.strip()
        if text.startswith("http://") or text.startswith("https://"):
            return self._clean_url(text)

        match = re.search(r"https?://[^\s\"'<>]+", text)
        if match:
            return self._clean_url(match.group(0))

        raise ValueError("No direct URL found in server response")

    def get_direct_link(self, source_link: str, delay_ms: int) -> str:
        file_id, file_name = self.parse_link(source_link)

        first_payload = {
            "op": "download1",
            "usr_login": "",
            "id": file_id,
            "fname": file_name,
            "referer": "",
            "method_free": "Free Download >>",
        }
        first = self.session.post(self.BASE_URL, data=first_payload, timeout=self.timeout)
        first.raise_for_status()

        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        second_payload = {
            "op": "download2",
            "id": file_id,
            "rand": "",
            "referer": self.BASE_URL,
            "method_free": "Free Download >>",
            "method_premium": "",
            "g_captch__a": "1",
        }
        second = self.session.post(
            self.BASE_URL, data=second_payload, timeout=self.timeout, allow_redirects=False
        )
        second.raise_for_status()

        return self._extract_direct_url(second)


class DownloaderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("DN Direct Link Downloader - Python GUI")
        self.geometry("1300x780")
        self.minsize(1080, 680)

        self.colors = {
            "bg": "#0F172A",
            "panel": "#111827",
            "card": "#1F2937",
            "text": "#E5E7EB",
            "muted": "#9CA3AF",
            "accent": "#22D3EE",
            "success": "#34D399",
            "warning": "#FBBF24",
            "danger": "#F87171",
            "line": "#374151",
        }

        self.configure(bg=self.colors["bg"])
        self.style = ttk.Style(self)
        self._apply_styles()

        self.delay_var = tk.IntVar(value=500)
        self.retries_var = tk.IntVar(value=3)
        self.timeout_var = tk.DoubleVar(value=30.0)
        self.workers_var = tk.IntVar(value=4)
        self.output_var = tk.StringVar(value=DEFAULT_OUTPUT_FILE)

        self.status_var = tk.StringVar(value="Ready")
        self.stats_var = tk.StringVar(value="Success: 0 | Failed: 0 | Total: 0")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None

        self.success_links: list[str] = []
        self.failed_items: list[tuple[str, str]] = []

        self._build_ui()
        self._load_config()
        self.after(120, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_styles(self) -> None:
        self.style.theme_use("clam")

        self.style.configure(
            ".",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            fieldbackground=self.colors["card"],
            bordercolor=self.colors["line"],
            font=("Segoe UI", 10),
        )
        self.style.configure("Main.TFrame", background=self.colors["bg"])
        self.style.configure("Panel.TFrame", background=self.colors["panel"])
        self.style.configure(
            "Card.TLabelframe",
            background=self.colors["panel"],
            bordercolor=self.colors["line"],
            relief="solid",
        )
        self.style.configure(
            "Card.TLabelframe.Label",
            background=self.colors["panel"],
            foreground=self.colors["accent"],
            font=("Segoe UI Semibold", 10),
        )
        self.style.configure(
            "Header.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            font=("Segoe UI Semibold", 17),
        )
        self.style.configure(
            "SubHeader.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        self.style.configure(
            "Accent.TButton",
            background=self.colors["accent"],
            foreground="#06242A",
            borderwidth=0,
            padding=(12, 8),
            font=("Segoe UI Semibold", 10),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#67E8F9"), ("disabled", "#155E75")],
            foreground=[("disabled", "#A5F3FC")],
        )
        self.style.configure(
            "Neutral.TButton",
            background=self.colors["card"],
            foreground=self.colors["text"],
            bordercolor=self.colors["line"],
            borderwidth=1,
            padding=(10, 8),
        )
        self.style.map("Neutral.TButton", background=[("active", "#334155")])
        self.style.configure(
            "Danger.TButton",
            background=self.colors["danger"],
            foreground="#2B0E11",
            borderwidth=0,
            padding=(10, 8),
            font=("Segoe UI Semibold", 10),
        )
        self.style.map("Danger.TButton", background=[("active", "#FCA5A5"), ("disabled", "#7F1D1D")])
        self.style.configure(
            "Stats.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["muted"],
            font=("Segoe UI", 10),
        )
        self.style.configure(
            "Status.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["accent"],
            font=("Segoe UI Semibold", 10),
        )
        self.style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor=self.colors["card"],
            background=self.colors["accent"],
            bordercolor=self.colors["line"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Main.TFrame", padding=16)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="DN Direct Link Downloader", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            root,
            text="Python GUI completee a partir du repo original (DataNodes direct links)",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(2, 10))

        settings = ttk.LabelFrame(root, text="Settings", style="Card.TLabelframe", padding=12)
        settings.pack(fill="x", pady=(0, 12))

        self._add_setting(settings, "Delay (ms)", self.delay_var, 0, 20000, 0)
        self._add_setting(settings, "Retries", self.retries_var, 0, 12, 1)
        self._add_setting(settings, "Timeout (s)", self.timeout_var, 5, 120, 2, is_float=True)
        self._add_setting(settings, "Workers", self.workers_var, 1, 16, 3)

        ttk.Label(settings, text="Output file").grid(row=0, column=8, padx=(20, 6), pady=2, sticky="w")
        output_entry = ttk.Entry(settings, textvariable=self.output_var, width=28)
        output_entry.grid(row=0, column=9, padx=(0, 6), sticky="w")
        ttk.Button(settings, text="Browse", style="Neutral.TButton", command=self._pick_output).grid(
            row=0, column=10, padx=(0, 4), sticky="w"
        )

        for idx in range(11):
            settings.columnconfigure(idx, weight=0)
        settings.columnconfigure(7, weight=1)

        controls = ttk.Frame(root, style="Main.TFrame")
        controls.pack(fill="x", pady=(0, 10))

        self.start_btn = ttk.Button(
            controls, text="Start", style="Accent.TButton", command=self._start_processing
        )
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            controls, text="Stop", style="Danger.TButton", command=self._stop_processing, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(8, 8))

        ttk.Button(controls, text="Import .txt", style="Neutral.TButton", command=self._import_links).pack(
            side="left"
        )
        ttk.Button(controls, text="Clear input", style="Neutral.TButton", command=self._clear_input).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(controls, text="Clear results", style="Neutral.TButton", command=self._clear_results).pack(
            side="left", padx=(8, 0)
        )

        paned = ttk.PanedWindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(paned, text="Datanodes links (one per line)", style="Card.TLabelframe", padding=10)
        self.input_text = ScrolledText(
            left,
            wrap="word",
            bg=self.colors["card"],
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.input_text.pack(fill="both", expand=True)
        self.input_text.insert(
            "1.0",
            "# Paste your datanodes links here, one per line.\n"
            "# Example: https://datanodes.to/<id>/<filename>",
        )
        paned.add(left, weight=1)

        right = ttk.LabelFrame(paned, text="Processing center", style="Card.TLabelframe", padding=10)
        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)

        results_tab = ttk.Frame(notebook, style="Panel.TFrame")
        links_tab = ttk.Frame(notebook, style="Panel.TFrame")
        logs_tab = ttk.Frame(notebook, style="Panel.TFrame")

        notebook.add(results_tab, text="Results")
        notebook.add(links_tab, text="Direct links")
        notebook.add(logs_tab, text="Logs")

        columns = ("status", "source", "direct", "error")
        self.result_tree = ttk.Treeview(results_tab, columns=columns, show="headings")
        self.result_tree.heading("status", text="Status")
        self.result_tree.heading("source", text="Source link")
        self.result_tree.heading("direct", text="Direct URL")
        self.result_tree.heading("error", text="Error")
        self.result_tree.column("status", width=88, anchor="center")
        self.result_tree.column("source", width=250, anchor="w")
        self.result_tree.column("direct", width=340, anchor="w")
        self.result_tree.column("error", width=220, anchor="w")
        self.result_tree.pack(fill="both", expand=True)
        self.result_tree.tag_configure("ok", foreground=self.colors["success"])
        self.result_tree.tag_configure("ko", foreground=self.colors["danger"])

        links_toolbar = ttk.Frame(links_tab, style="Panel.TFrame")
        links_toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(
            links_toolbar, text="Copy all", style="Neutral.TButton", command=self._copy_direct_links
        ).pack(side="left")
        ttk.Button(
            links_toolbar, text="Export links", style="Neutral.TButton", command=self._export_direct_links
        ).pack(side="left", padx=(8, 0))

        self.direct_text = ScrolledText(
            links_tab,
            wrap="none",
            bg=self.colors["card"],
            fg=self.colors["success"],
            insertbackground=self.colors["accent"],
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.direct_text.pack(fill="both", expand=True)

        self.log_text = ScrolledText(
            logs_tab,
            wrap="word",
            bg="#0B1220",
            fg=self.colors["text"],
            insertbackground=self.colors["accent"],
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

        paned.add(right, weight=2)

        footer = ttk.Frame(root, style="Main.TFrame")
        footer.pack(fill="x", pady=(10, 0))

        self.progress = ttk.Progressbar(
            footer,
            style="Custom.Horizontal.TProgressbar",
            variable=self.progress_var,
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(footer, textvariable=self.stats_var, style="Stats.TLabel").pack(anchor="w")

    def _add_setting(
        self,
        parent: ttk.LabelFrame,
        label: str,
        variable: tk.Variable,
        min_v: float,
        max_v: float,
        column_group: int,
        is_float: bool = False,
    ) -> None:
        base_col = column_group * 2
        ttk.Label(parent, text=label).grid(row=0, column=base_col, padx=(0, 6), pady=2, sticky="w")
        if is_float:
            entry = ttk.Entry(parent, textvariable=variable, width=8)
            entry.grid(row=0, column=base_col + 1, padx=(0, 12), pady=2, sticky="w")
        else:
            spin = ttk.Spinbox(parent, from_=min_v, to=max_v, textvariable=variable, width=8)
            spin.grid(row=0, column=base_col + 1, padx=(0, 12), pady=2, sticky="w")

    def _pick_output(self) -> None:
        target = filedialog.asksaveasfilename(
            title="Choose output file",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=self.output_var.get() or DEFAULT_OUTPUT_FILE,
        )
        if target:
            self.output_var.set(target)

    def _load_config(self) -> None:
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        self.delay_var.set(int(data.get("delay_ms", 500)))
        self.retries_var.set(int(data.get("max_retries", 3)))
        self.timeout_var.set(float(data.get("timeout_seconds", 30.0)))
        self.workers_var.set(int(data.get("workers", 4)))
        self.output_var.set(str(data.get("output_file", DEFAULT_OUTPUT_FILE)))

    def _save_config(self) -> None:
        settings = {
            "delay_ms": self.delay_var.get(),
            "max_retries": self.retries_var.get(),
            "timeout_seconds": self.timeout_var.get(),
            "workers": self.workers_var.get(),
            "output_file": self.output_var.get(),
        }
        try:
            CONFIG_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError:
            self._log("Could not save GUI config file.", level="warn")

    def _collect_links(self) -> list[str]:
        lines = self.input_text.get("1.0", "end").splitlines()
        links = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        return links

    def _import_links(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Import links from .txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not file_path:
            return

        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Import error", f"Unable to read file:\n{exc}")
            return

        existing = self.input_text.get("1.0", "end").strip()
        append_prefix = "\n" if existing else ""
        self.input_text.insert("end", f"{append_prefix}{content.strip()}\n")
        self._log(f"Imported links from {file_path}")

    def _clear_input(self) -> None:
        self.input_text.delete("1.0", "end")
        self._log("Input cleared.")

    def _clear_results(self) -> None:
        self.success_links.clear()
        self.failed_items.clear()
        self.result_tree.delete(*self.result_tree.get_children())
        self.direct_text.delete("1.0", "end")
        self.progress_var.set(0)
        self.status_var.set("Results cleared")
        self.stats_var.set("Success: 0 | Failed: 0 | Total: 0")
        self._log("Results cleared.")

    def _read_settings(self) -> DownloaderSettings | None:
        try:
            settings = DownloaderSettings(
                delay_ms=int(self.delay_var.get()),
                max_retries=int(self.retries_var.get()),
                timeout_seconds=float(self.timeout_var.get()),
                workers=int(self.workers_var.get()),
                output_file=self.output_var.get().strip() or DEFAULT_OUTPUT_FILE,
            )
        except (TypeError, ValueError):
            messagebox.showerror("Invalid settings", "Please check all settings values.")
            return None

        if settings.delay_ms < 0:
            messagebox.showerror("Invalid settings", "Delay must be >= 0 ms.")
            return None
        if settings.max_retries < 0:
            messagebox.showerror("Invalid settings", "Retries must be >= 0.")
            return None
        if settings.timeout_seconds <= 0:
            messagebox.showerror("Invalid settings", "Timeout must be > 0.")
            return None
        if settings.workers < 1 or settings.workers > 32:
            messagebox.showerror("Invalid settings", "Workers must be between 1 and 32.")
            return None

        return settings

    def _start_processing(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        links = self._collect_links()
        if not links:
            messagebox.showwarning("No links", "Paste at least one datanodes link.")
            return

        settings = self._read_settings()
        if not settings:
            return

        self._save_config()
        self._clear_results()
        self.stop_event.clear()

        total = len(links)
        self.status_var.set(f"Running... 0/{total}")
        self.stats_var.set(f"Success: 0 | Failed: 0 | Total: {total}")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._log(f"Started processing {total} links with {settings.workers} worker(s).")

        self.worker_thread = threading.Thread(
            target=self._worker_main, args=(links, settings), daemon=True
        )
        self.worker_thread.start()

    def _stop_processing(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return
        self.stop_event.set()
        self._log("Stop requested by user.", level="warn")
        self.status_var.set("Stopping...")

    def _interruptible_sleep(self, seconds: float) -> bool:
        end_time = time.time() + max(0.0, seconds)
        while time.time() < end_time:
            if self.stop_event.is_set():
                return True
            time.sleep(0.08)
        return self.stop_event.is_set()

    def _process_one_link(self, link: str, settings: DownloaderSettings) -> str:
        last_error: Exception | None = None
        client = DatanodesClient(timeout_seconds=settings.timeout_seconds)

        for attempt in range(settings.max_retries + 1):
            if self.stop_event.is_set():
                raise RuntimeError("Stopped by user")
            try:
                return client.get_direct_link(link, settings.delay_ms)
            except Exception as exc:
                last_error = exc
                if attempt < settings.max_retries:
                    wait_time = 0.6 * (2**attempt)
                    self.event_queue.put(
                        {
                            "type": "log",
                            "message": (
                                f"Retry {attempt + 1}/{settings.max_retries} "
                                f"for {link} ({exc})"
                            ),
                            "level": "warn",
                        }
                    )
                    if self._interruptible_sleep(wait_time):
                        raise RuntimeError("Stopped by user") from exc

        raise RuntimeError(str(last_error) if last_error else "Unknown error")

    def _worker_main(self, links: list[str], settings: DownloaderSettings) -> None:
        total = len(links)
        completed = 0
        success_count = 0
        failed_count = 0

        local_successes: list[str] = []

        self.event_queue.put({"type": "log", "message": "Connection initialized.", "level": "info"})

        try:
            with ThreadPoolExecutor(max_workers=settings.workers) as executor:
                future_map = {
                    executor.submit(self._process_one_link, link, settings): (idx, link)
                    for idx, link in enumerate(links, start=1)
                }

                for future in as_completed(future_map):
                    index, link = future_map[future]
                    if self.stop_event.is_set():
                        for pending in future_map:
                            pending.cancel()
                        break

                    completed += 1
                    try:
                        direct = future.result()
                        success_count += 1
                        local_successes.append(direct)
                        self.event_queue.put(
                            {
                                "type": "result",
                                "ok": True,
                                "index": index,
                                "source": link,
                                "direct": direct,
                                "error": "",
                            }
                        )
                    except Exception as exc:
                        failed_count += 1
                        self.event_queue.put(
                            {
                                "type": "result",
                                "ok": False,
                                "index": index,
                                "source": link,
                                "direct": "",
                                "error": str(exc),
                            }
                        )

                    self.event_queue.put(
                        {
                            "type": "progress",
                            "completed": completed,
                            "total": total,
                            "success": success_count,
                            "failed": failed_count,
                        }
                    )

            output_path = ""
            if local_successes:
                output = Path(settings.output_file).expanduser()
                if output.parent and not output.parent.exists():
                    output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("\n".join(local_successes), encoding="utf-8")
                output_path = str(output.resolve())

            self.event_queue.put(
                {
                    "type": "done",
                    "stopped": self.stop_event.is_set(),
                    "success": success_count,
                    "failed": failed_count,
                    "total": total,
                    "output_path": output_path,
                }
            )
        except Exception as exc:
            self.event_queue.put({"type": "log", "message": f"Fatal worker error: {exc}", "level": "error"})
            self.event_queue.put(
                {
                    "type": "done",
                    "stopped": True,
                    "success": success_count,
                    "failed": failed_count,
                    "total": total,
                    "output_path": "",
                }
            )

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get("type")
            if event_type == "log":
                self._log(event.get("message", ""), level=event.get("level", "info"))
            elif event_type == "result":
                self._apply_result_event(event)
            elif event_type == "progress":
                self._apply_progress_event(event)
            elif event_type == "done":
                self._apply_done_event(event)

        self.after(120, self._drain_events)

    def _apply_result_event(self, event: dict[str, Any]) -> None:
        ok = bool(event.get("ok"))
        source = str(event.get("source", ""))
        direct = str(event.get("direct", ""))
        error = str(event.get("error", ""))
        status = "OK" if ok else "FAILED"

        if ok and direct:
            self.success_links.append(direct)
            self.direct_text.insert("end", f"{direct}\n")
            self._log(f"OK: {source}", level="success")
        else:
            self.failed_items.append((source, error))
            self._log(f"FAILED: {source} -> {error}", level="error")

        tag = "ok" if ok else "ko"
        self.result_tree.insert("", "end", values=(status, source, direct, error), tags=(tag,))

    def _apply_progress_event(self, event: dict[str, Any]) -> None:
        completed = int(event.get("completed", 0))
        total = int(event.get("total", 0))
        success = int(event.get("success", 0))
        failed = int(event.get("failed", 0))

        pct = (completed / total * 100.0) if total else 0.0
        self.progress_var.set(pct)
        self.status_var.set(f"Running... {completed}/{total}")
        self.stats_var.set(f"Success: {success} | Failed: {failed} | Total: {total}")

    def _apply_done_event(self, event: dict[str, Any]) -> None:
        stopped = bool(event.get("stopped"))
        success = int(event.get("success", 0))
        failed = int(event.get("failed", 0))
        total = int(event.get("total", 0))
        output_path = str(event.get("output_path", ""))

        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

        if stopped:
            self.status_var.set("Stopped")
            self._log("Processing stopped.", level="warn")
        else:
            self.status_var.set("Completed")
            self.progress_var.set(100.0 if total else 0.0)
            self._log("Processing completed.", level="success")

        if output_path:
            self._log(f"Saved direct links to: {output_path}", level="success")

        summary = f"Done.\n\nSuccess: {success}\nFailed: {failed}\nTotal: {total}"
        if output_path:
            summary += f"\n\nOutput file:\n{output_path}"
        messagebox.showinfo("DN Downloader", summary)

    def _copy_direct_links(self) -> None:
        payload = "\n".join(self.success_links)
        if not payload:
            messagebox.showwarning("Nothing to copy", "No direct links available.")
            return
        self.clipboard_clear()
        self.clipboard_append(payload)
        self._log("Direct links copied to clipboard.")

    def _export_direct_links(self) -> None:
        if not self.success_links:
            messagebox.showwarning("No links", "No direct links to export.")
            return

        target = filedialog.asksaveasfilename(
            title="Export direct links",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=Path(self.output_var.get() or DEFAULT_OUTPUT_FILE).name,
        )
        if not target:
            return

        try:
            Path(target).write_text("\n".join(self.success_links), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Export error", f"Could not save file:\n{exc}")
            return

        self._log(f"Direct links exported to: {target}", level="success")

    def _log(self, message: str, level: str = "info") -> None:
        if not message:
            return

        timestamp = time.strftime("%H:%M:%S")
        prefix = {
            "info": "[INFO]",
            "warn": "[WARN]",
            "error": "[ERROR]",
            "success": "[OK]",
        }.get(level, "[INFO]")
        line = f"{timestamp} {prefix} {message}\n"

        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        self.stop_event.set()
        self._save_config()
        self.destroy()


def main() -> None:
    app = DownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
