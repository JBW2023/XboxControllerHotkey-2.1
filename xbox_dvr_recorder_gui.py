"""
XboxControllerHotkey v2.1 — GUI Edition
Triggers Win+Alt+G (Xbox Game Bar clip capture) when Back+Start are
pressed simultaneously on an Xbox controller.

Requirements:
    pip install customtkinter pygame pynput pystray Pillow
"""

import os
import queue
import threading
import time
from datetime import datetime

import customtkinter as ctk
import pygame
from pynput.keyboard import Controller as KeyboardController, Key

# Optional: system-tray support (graceful fallback if missing)
try:
    import pystray
    from PIL import Image, ImageDraw

    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# ─── Appearance ───────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG_DARK = "#0a0a0a"
BG_CARD = "#141414"
BG_CARD_HOVER = "#1a1a1a"
ACCENT_GREEN = "#2ecc40"
ACCENT_RED = "#e74c3c"
ACCENT_BLUE = "#0078d7"
TEXT_PRIMARY = "#e0e0e0"
TEXT_DIM = "#666666"
BORDER = "#222222"

APP_TITLE = "XboxControllerHotkey"
APP_VERSION = "2.1"


def _make_tray_icon(color: str = "#0078d7") -> "Image.Image":
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=color)
    draw.text((16, 16), "XC", fill="white")
    return img


# ╔════════════════════════════════════════════════════════════════════╗
# ║  Background polling thread — all pygame work happens here         ║
# ╚════════════════════════════════════════════════════════════════════╝
class ControllerThread(threading.Thread):
    """Polls pygame for joystick events on a background thread so the
    Tk main-loop is never blocked."""

    def __init__(self, ui_queue: queue.Queue) -> None:
        super().__init__(daemon=True)
        self.ui_queue = ui_queue
        self.keyboard = KeyboardController()
        self.running = True

    def run(self) -> None:
        pygame.init()

        connected = False
        joystick = None
        start_btn = False
        select_btn = False
        combo_pressed = False

        while self.running:
            # ── Connection management ─────────────────────────────────
            try:
                joy_count = pygame.joystick.get_count()
            except pygame.error:
                joy_count = 0

            if joy_count == 0 and connected:
                connected = False
                joystick = None
                start_btn = False
                select_btn = False
                self.ui_queue.put(("disconnected", None))

            elif joy_count > 0 and not connected:
                try:
                    joystick = pygame.joystick.Joystick(0)
                    joystick.init()
                    connected = True
                    self.ui_queue.put(("connected", joystick.get_name()))
                except Exception:
                    connected = False

            # ── Event processing ──────────────────────────────────────
            try:
                for event in pygame.event.get():
                    if event.type == pygame.JOYBUTTONDOWN:
                        if event.button == 7:
                            start_btn = True
                        elif event.button == 6:
                            select_btn = True
                    elif event.type == pygame.JOYBUTTONUP:
                        if event.button == 7:
                            start_btn = False
                        elif event.button == 6:
                            select_btn = False
            except pygame.error:
                pass

            # ── Combo detection ───────────────────────────────────────
            if start_btn and select_btn:
                if not combo_pressed:
                    self.keyboard.press(Key.alt_l)
                    self.keyboard.press(Key.cmd)
                    self.keyboard.press("g")
                    self.keyboard.release("g")
                    self.keyboard.release(Key.cmd)
                    self.keyboard.release(Key.alt_l)
                    combo_pressed = True
                    self.ui_queue.put(("clip", None))
            else:
                combo_pressed = False

            time.sleep(0.012)  # ~83 Hz — fast enough, doesn't starve CPU

    def stop(self) -> None:
        self.running = False


# ╔════════════════════════════════════════════════════════════════════╗
# ║  Main Application                                                 ║
# ╚════════════════════════════════════════════════════════════════════╝
class App(ctk.CTk):
    WIDTH = 420
    HEIGHT = 520
    UI_CHECK_MS = 100  # check the queue every 100 ms — plenty fast for UI

    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.minsize(self.WIDTH, self.HEIGHT)
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
        if os.path.isfile(icon_path):
            self.iconbitmap(icon_path)

        self.clip_count = 0
        self.tray_icon: "pystray.Icon | None" = None

        # Thread-safe queue: background thread pushes events, UI drains them
        self._ui_queue: queue.Queue = queue.Queue()

        self._build_ui()

        # Start the background controller thread
        self._controller = ControllerThread(self._ui_queue)
        self._controller.start()

        # Lightweight timer that only reads from the queue
        self.after(self.UI_CHECK_MS, self._drain_queue)

    # ──────────────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 0))

        ctk.CTkLabel(
            header,
            text=APP_TITLE,
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT_DIM,
        ).pack(side="left", padx=(8, 0), pady=(6, 0))

        # ── Status card ───────────────────────────────────────────────
        self.status_card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BORDER
        )
        self.status_card.pack(fill="x", padx=24, pady=(20, 0))

        status_inner = ctk.CTkFrame(self.status_card, fg_color="transparent")
        status_inner.pack(fill="x", padx=20, pady=20)

        dot_row = ctk.CTkFrame(status_inner, fg_color="transparent")
        dot_row.pack(fill="x")

        self.status_dot = ctk.CTkLabel(
            dot_row, text="●", font=ctk.CTkFont(size=16), text_color=ACCENT_RED, width=20
        )
        self.status_dot.pack(side="left")

        self.status_label = ctk.CTkLabel(
            dot_row,
            text="No controller detected",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.status_label.pack(side="left", padx=(6, 0))

        self.status_detail = ctk.CTkLabel(
            status_inner,
            text="Connect an Xbox controller to get started.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT_DIM,
            anchor="w",
            wraplength=340,
        )
        self.status_detail.pack(fill="x", pady=(8, 0))

        # ── Clip counter card ─────────────────────────────────────────
        counter_card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BORDER
        )
        counter_card.pack(fill="x", padx=24, pady=(12, 0))

        counter_inner = ctk.CTkFrame(counter_card, fg_color="transparent")
        counter_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(
            counter_inner,
            text="Clips captured this session",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT_DIM,
            anchor="w",
        ).pack(fill="x")

        self.clip_count_label = ctk.CTkLabel(
            counter_inner,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=36, weight="bold"),
            text_color=ACCENT_BLUE,
            anchor="w",
        )
        self.clip_count_label.pack(fill="x", pady=(2, 0))

        self.last_clip_label = ctk.CTkLabel(
            counter_inner,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=TEXT_DIM,
            anchor="w",
        )
        self.last_clip_label.pack(fill="x")

        # ── Instructions card ─────────────────────────────────────────
        info_card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=12, border_width=1, border_color=BORDER
        )
        info_card.pack(fill="x", padx=24, pady=(12, 0))

        info_inner = ctk.CTkFrame(info_card, fg_color="transparent")
        info_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(
            info_inner,
            text="How it works",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            info_inner,
            text=(
                "Press  Back + Start  simultaneously on your controller "
                "to trigger the Xbox Game Bar clip shortcut (Win+Alt+G).\n\n"
                "Keep this app running in the background while you play."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT_DIM,
            anchor="w",
            justify="left",
            wraplength=340,
        ).pack(fill="x", pady=(6, 0))

        # ── Bottom bar ────────────────────────────────────────────────
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", side="bottom", padx=24, pady=(0, 18))

        if TRAY_AVAILABLE:
            ctk.CTkButton(
                bottom,
                text="Minimize to tray",
                width=130,
                height=32,
                corner_radius=8,
                fg_color=BG_CARD,
                hover_color=BG_CARD_HOVER,
                border_width=1,
                border_color=BORDER,
                text_color=TEXT_DIM,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                command=self._minimize_to_tray,
            ).pack(side="left")

        ctk.CTkButton(
            bottom,
            text="Quit",
            width=70,
            height=32,
            corner_radius=8,
            fg_color=BG_CARD,
            hover_color="#2a1010",
            border_width=1,
            border_color=BORDER,
            text_color=ACCENT_RED,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            command=self._on_close,
        ).pack(side="right")

        link = ctk.CTkLabel(
            bottom,
            text="github.com/jimhatesyou",
            font=ctk.CTkFont(family="Segoe UI", size=11, underline=True),
            text_color=TEXT_DIM,
            cursor="hand2",
        )
        link.pack(side="right", padx=(0, 12))
        link.bind("<Button-1>", lambda _: os.startfile("https://github.com/jimhatesyou"))

    # ──────────────────────────────────────────────────────────────────
    # Queue drain — lightweight, only touches UI when there's a message
    # ──────────────────────────────────────────────────────────────────
    def _drain_queue(self) -> None:
        try:
            while True:
                kind, data = self._ui_queue.get_nowait()
                if kind == "connected":
                    self._set_connected(data or "Controller")
                elif kind == "disconnected":
                    self._set_disconnected()
                elif kind == "clip":
                    self._record_clip()
        except queue.Empty:
            pass
        self.after(self.UI_CHECK_MS, self._drain_queue)

    # ──────────────────────────────────────────────────────────────────
    # Status helpers
    # ──────────────────────────────────────────────────────────────────
    def _set_connected(self, name: str) -> None:
        self.status_dot.configure(text_color=ACCENT_GREEN)
        self.status_label.configure(text=name)
        self.status_detail.configure(text="Ready — press Back + Start to capture a clip.")
        self.status_card.configure(border_color="#1a3a1a")

    def _set_disconnected(self) -> None:
        self.status_dot.configure(text_color=ACCENT_RED)
        self.status_label.configure(text="No controller detected")
        self.status_detail.configure(text="Connect an Xbox controller to get started.")
        self.status_card.configure(border_color=BORDER)

    def _record_clip(self) -> None:
        self.clip_count += 1
        now = datetime.now().strftime("%I:%M:%S %p")
        self.clip_count_label.configure(text=str(self.clip_count))
        self.last_clip_label.configure(text=f"Last clip at {now}")
        self.clip_count_label.configure(text_color=ACCENT_GREEN)
        self.after(400, lambda: self.clip_count_label.configure(text_color=ACCENT_BLUE))

    # ──────────────────────────────────────────────────────────────────
    # System tray
    # ──────────────────────────────────────────────────────────────────
    def _minimize_to_tray(self) -> None:
        if not TRAY_AVAILABLE:
            return
        self.withdraw()
        icon_img = _make_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._restore_from_tray, default=True),
            pystray.MenuItem("Quit", self._on_close),
        )
        self.tray_icon = pystray.Icon(APP_TITLE, icon_img, APP_TITLE, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _restore_from_tray(self, *_args) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.after(0, self.deiconify)

    # ──────────────────────────────────────────────────────────────────
    # Shutdown
    # ──────────────────────────────────────────────────────────────────
    def _on_close(self, *_args) -> None:
        self._controller.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        pygame.quit()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
