#!/usr/bin/env python3
"""
MemReduct untuk Ubuntu - pembersih memori ringan dengan ikon tray (terinspirasi Mem Reduct).

Dependensi (biasanya sudah ada di Ubuntu Desktop):
    sudo apt install python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 \
                     gir1.2-ayatanaappindicator3-0.1 libnotify-bin

Jalankan:
    python3 memreduct.py            # tampilkan jendela
    python3 memreduct.py --hidden   # langsung ke tray
"""
import getpass
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except Exception:
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    except Exception:
        AppIndicator = None

try:
    import cairo
except Exception:
    sys.exit("Butuh pycairo. Pasang: sudo apt install python3-cairo python3-gi-cairo")

# ---------------------------------------------------------------- konstanta
APP_ID = "id.memreduct.linux"
SCRIPT = os.path.abspath(__file__)
CONFIG_DIR = os.path.expanduser("~/.config/memreduct")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
ICON_DIR = os.path.expanduser("~/.cache/memreduct/icons")
AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/memreduct.desktop")
MENU_FILE = os.path.expanduser("~/.local/share/applications/memreduct.desktop")
PKG_HELPER = "/usr/lib/memreduct/memreduct-clean"
PACKAGED = os.path.exists(PKG_HELPER)  # True bila dipasang lewat paket .deb
HELPER = PKG_HELPER if PACKAGED else "/usr/local/sbin/memreduct-clean"
SUDOERS = "/etc/sudoers.d/memreduct"
EXEC_CMD = "memreduct" if PACKAGED else f"python3 {SCRIPT}"
ICON_NAME = "memreduct" if PACKAGED else "utilities-system-monitor"
COOLDOWN = 60  # detik, jeda minimal antar pembersihan otomatis berbasis persen
TICK_MS = 2000

# Palet
C_BG, C_CARD, C_TRACK = "#0e1014", "#171a21", "#262b36"
C_TEXT, C_MUTED, C_ACCENT = "#e8eaf0", "#8b93a5", "#818cf8"
LEVEL_COLORS = [("#34d399", "#22d3ee"), ("#fbbf24", "#fb923c"), ("#f87171", "#f43f5e")]
LEVEL_NAMES = ["Normal", "Tinggi", "Kritis"]
CHIP_CLASSES = ("chip-ok", "chip-warn", "chip-danger")

DEFAULTS = {
    "auto_pct": True, "auto_pct_value": 80,
    "auto_interval": False, "auto_interval_min": 30,
    "clean_on_start": False,
    "notify": True, "start_hidden": False, "autostart": False,
    "count_cache": True,
    "warn": 60, "danger": 80,
    "area_pagecache": True, "area_slab": True, "area_compact": False, "area_swap": False,
}

# Skrip helper yang dijalankan sebagai root. Hanya menerima kata kunci tetap.
HELPER_SCRIPT = """#!/bin/bash
# MemReduct helper - dijalankan sebagai root, hanya menerima kata kunci tetap.
[ "$(id -u)" -eq 0 ] || { echo "butuh root" >&2; exit 1; }
sync
for a in "$@"; do
  case "$a" in
    pagecache) echo 1 > /proc/sys/vm/drop_caches ;;
    slab) echo 2 > /proc/sys/vm/drop_caches ;;
    compact) [ -w /proc/sys/vm/compact_memory ] && echo 1 > /proc/sys/vm/compact_memory ;;
    swap)
      st=$(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{print t-f}' /proc/meminfo)
      av=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
      if [ "$st" -gt 0 ] && [ "$av" -gt $((st*11/10)) ]; then swapoff -a && swapon -a; fi ;;
    *) echo "argumen tidak dikenal: $a" >&2; exit 2 ;;
  esac
done
exit 0
"""

# $1 = isi helper, $2 = nama user
SETUP_SCRIPT = """set -e
trap 'rm -f /etc/sudoers.d/memreduct.tmp' ERR
mkdir -p /usr/local/sbin
printf '%s\\n' "$1" > /usr/local/sbin/memreduct-clean
chown root:root /usr/local/sbin/memreduct-clean
chmod 0755 /usr/local/sbin/memreduct-clean
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/memreduct-clean\\n' "$2" > /etc/sudoers.d/memreduct.tmp
chmod 0440 /etc/sudoers.d/memreduct.tmp
visudo -cf /etc/sudoers.d/memreduct.tmp >/dev/null
mv /etc/sudoers.d/memreduct.tmp /etc/sudoers.d/memreduct
"""

CSS = b"""
window { background-color: #0e1014; color: #e8eaf0; }
headerbar { background-color: #0e1014; background-image: none; border: none;
            box-shadow: none; color: #e8eaf0; }
headerbar .title { font-weight: 700; }
headerbar .subtitle { color: #8b93a5; font-size: 11px; }
headerbar button { background-image: none; background-color: #171a21; border: none;
                   border-radius: 10px; color: #e8eaf0; box-shadow: none; }
headerbar button:hover { background-color: #262b36; }

.card { background-color: #171a21; border-radius: 20px; padding: 14px 16px; }
.tile { background-color: #171a21; border-radius: 16px; padding: 10px 14px; }
.tile-title { color: #8b93a5; font-size: 11px; }
.tile-value { font-weight: 700; font-size: 15px; }
.muted { color: #8b93a5; font-size: 11px; }
.card-title { font-weight: 700; }

.chip { border-radius: 20px; padding: 3px 14px; font-size: 11px; font-weight: 700; }
.chip-ok { background-color: rgba(52,211,153,0.15); color: #34d399; }
.chip-warn { background-color: rgba(251,191,36,0.15); color: #fbbf24; }
.chip-danger { background-color: rgba(248,113,113,0.15); color: #f87171; }

button.clean { background-image: linear-gradient(135deg, #6366f1, #8b5cf6);
               background-color: transparent; border: none; border-radius: 16px;
               padding: 14px; box-shadow: 0 6px 18px rgba(99,102,241,0.35);
               text-shadow: none; }
button.clean:hover { background-image: linear-gradient(135deg, #7c7ff5, #9d6bfb); }
button.clean:disabled { opacity: 0.55; }
button.clean label, button.clean image { color: #ffffff; font-weight: 700; }

switch { background-color: #262b36; border: none; border-radius: 20px; }
switch:checked { background-color: #6366f1; }
switch slider { background-color: #ffffff; background-image: none; border: none;
                border-radius: 20px; box-shadow: none; }

.setting-row { padding: 10px 2px; border-bottom: 1px solid rgba(255,255,255,0.06); }
spinbutton { background-color: #171a21; border-radius: 10px; border: none; }
"""


# ---------------------------------------------------------------- util
def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def meminfo():
    d = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            d[k] = int(v.split()[0])
    return d


def read_stats(count_cache=True):
    m = meminfo()
    total = m["MemTotal"]
    free = m["MemFree"] if count_cache else m["MemAvailable"]
    used = total - free
    cache = m.get("Cached", 0) + m.get("Buffers", 0) + m.get("SReclaimable", 0)
    st_total = m.get("SwapTotal", 0)
    st_used = st_total - m.get("SwapFree", 0)
    return {
        "total": total // 1024, "used": used // 1024, "pct": round(used * 100 / total),
        "avail": m["MemAvailable"] // 1024,
        "cache": cache // 1024, "cache_pct": round(cache * 100 / total),
        "swap_total": st_total // 1024, "swap_used": st_used // 1024,
        "swap_pct": round(st_used * 100 / st_total) if st_total else 0,
    }


def fmt(mb):
    return f"{mb / 1024:.1f} GB" if abs(mb) >= 1024 else f"{mb} MB"


def notify(msg):
    try:
        subprocess.Popen(["notify-send", "-i", ICON_NAME, "MemReduct", msg],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def make_icon(pct, level):
    """Buat ikon tray PNG berisi angka persen. Mengembalikan (folder, nama_tanpa_ekstensi)."""
    name = f"mr_{pct}_{level}"
    path = os.path.join(ICON_DIR, name + ".png")
    if not os.path.exists(path):
        os.makedirs(ICON_DIR, exist_ok=True)
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
        c = cairo.Context(s)
        r, x, y, w, h = 14, 2, 2, 60, 60
        c.new_sub_path()
        c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        c.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        c.close_path()
        g = cairo.LinearGradient(0, 0, 64, 64)
        c1, c2 = LEVEL_COLORS[level]
        g.add_color_stop_rgb(0, *rgb(c1))
        g.add_color_stop_rgb(1, *rgb(c2))
        c.set_source(g)
        c.fill()
        c.set_source_rgb(0.05, 0.06, 0.08)
        c.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        txt = str(pct)
        c.set_font_size(42 if len(txt) < 3 else 32)
        e = c.text_extents(txt)
        c.move_to(32 - e.width / 2 - e.x_bearing, 32 - e.height / 2 - e.y_bearing)
        c.show_text(txt)
        s.write_to_png(path)
    return ICON_DIR, name


def run_helper(flags, allow_prompt):
    """Jalankan helper pembersih. Mengembalikan (ok, pesan_error)."""
    if os.geteuid() == 0:
        r = subprocess.run(["bash", "-c", HELPER_SCRIPT, "memreduct"] + flags,
                           capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip()
    r = subprocess.run(["sudo", "-n", HELPER] + flags, capture_output=True, text=True)
    if r.returncode == 0:
        return True, ""
    err = r.stderr.lower()
    needs_auth = any(k in err for k in ("password", "not allowed", "may not run"))
    if not needs_auth:
        return False, r.stderr.strip()
    if not allow_prompt:
        return False, "izin belum disiapkan (buka Pengaturan > Umum > Siapkan izin)"
    r2 = subprocess.run(["pkexec", HELPER] + flags, capture_output=True, text=True)
    if r2.returncode in (126, 127):
        return False, "dibatalkan"
    return r2.returncode == 0, r2.stderr.strip()


def text_center(cr, txt, x, y, size, color, bold=False, alpha=1.0):
    cr.select_font_face("Ubuntu", cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)
    e = cr.text_extents(txt)
    cr.set_source_rgba(*rgb(color), alpha)
    cr.move_to(x - e.width / 2 - e.x_bearing, y)
    cr.show_text(txt)


# ---------------------------------------------------------------- aplikasi
class MemReduct(Gtk.Application):
    def __init__(self, hidden=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.hidden_arg = hidden
        self.cfg = load_config()
        self.win = None
        self.indicator = None
        self.cur_icon = None
        self.busy = False
        self.last_clean = -1e9
        self.last_interval = time.monotonic()
        self.st = read_stats(self.cfg["count_cache"])
        self.history = deque([self.st["pct"]], maxlen=60)
        self.disp = 0.0          # nilai gauge yang ditampilkan (animasi)
        self._anim_id = 0
        self.perm_label = None

    # ---- siklus hidup
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        prov = Gtk.CssProvider()
        try:
            prov.load_from_data(CSS)
        except GLib.Error as e:
            print("Peringatan CSS:", e.message, file=sys.stderr)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.ensure_menu_entry()
        self.build_tray()
        GLib.timeout_add(TICK_MS, self.tick)
        if self.cfg["clean_on_start"]:
            GLib.timeout_add_seconds(4, lambda: (self.do_clean("auto"), False)[1])

    def do_activate(self):
        if self.win is None:
            self.build_window()
            if AppIndicator is None or not (self.hidden_arg or self.cfg["start_hidden"]):
                self.show_window()
        else:
            self.show_window()

    # ---- tray
    def build_tray(self):
        self.tray_menu = Gtk.Menu()
        self.tray_info = Gtk.MenuItem(label="RAM: -")
        self.tray_info.set_sensitive(False)
        self.tray_menu.append(self.tray_info)
        self.tray_menu.append(Gtk.SeparatorMenuItem())
        for label, cb in (("Tampilkan jendela", lambda *_: self.show_window()),
                          ("Bersihkan memori", lambda *_: self.do_clean("manual")),
                          ("Pengaturan", lambda *_: self.show_settings())):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", cb)
            self.tray_menu.append(it)
        self.tray_menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Keluar")
        quit_item.connect("activate", lambda *_: self.quit())
        self.tray_menu.append(quit_item)
        self.tray_menu.show_all()

        if AppIndicator is None:
            return
        d, name = make_icon(self.st["pct"], self.level(self.st["pct"]))
        self.cur_icon = name
        self.indicator = AppIndicator.Indicator.new_with_path(
            APP_ID, name, AppIndicator.IndicatorCategory.SYSTEM_SERVICES, d)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.tray_menu)

    def refresh_tray(self):
        st = self.st
        self.tray_info.set_label(f"RAM: {st['pct']}%  ({fmt(st['used'])} / {fmt(st['total'])})")
        if self.indicator:
            d, name = make_icon(st["pct"], self.level(st["pct"]))
            if name != self.cur_icon:
                self.cur_icon = name
                self.indicator.set_icon_full(name, f"RAM {st['pct']}%")

    # ---- komponen UI
    @staticmethod
    def css(widget, *classes):
        ctx = widget.get_style_context()
        for c in classes:
            ctx.add_class(c)
        return widget

    def card(self, parent, spacing=8):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.css(box, "card")
        parent.pack_start(box, False, False, 0)
        return box

    def make_tile(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.css(box, "tile")
        box.pack_start(self.css(Gtk.Label(label=title, xalign=0), "tile-title"), False, False, 0)
        val = self.css(Gtk.Label(label="-", xalign=0), "tile-value")
        box.pack_start(val, False, False, 0)
        return box, val

    # ---- jendela utama
    def build_window(self):
        w = Gtk.ApplicationWindow(application=self, title="MemReduct")
        w.set_default_size(400, -1)
        w.set_resizable(False)
        w.set_icon_name(ICON_NAME)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "MemReduct"
        hb.props.subtitle = "Pembersih memori"
        b = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        b.set_tooltip_text("Pengaturan")
        b.connect("clicked", lambda *_: self.show_settings())
        hb.pack_end(b)
        w.set_titlebar(hb)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("start", "end", "top", "bottom"):
            getattr(root, f"set_margin_{side}")(16)

        # kartu utama: gauge
        hero = self.card(root, spacing=6)
        self.gauge = Gtk.DrawingArea()
        self.gauge.set_size_request(340, 228)
        self.gauge.connect("draw", self.draw_gauge)
        hero.pack_start(self.gauge, False, False, 0)
        self.chip = self.css(Gtk.Label(label="Normal", halign=Gtk.Align.CENTER), "chip")
        hero.pack_start(self.chip, False, False, 0)

        # kartu riwayat
        hist = self.card(root, spacing=6)
        top = Gtk.Box(spacing=6)
        top.pack_start(self.css(Gtk.Label(label="Riwayat 2 menit terakhir", xalign=0), "muted"),
                       True, True, 0)
        self.peak = self.css(Gtk.Label(label="", xalign=1), "muted")
        top.pack_end(self.peak, False, False, 0)
        hist.pack_start(top, False, False, 0)
        self.spark = Gtk.DrawingArea()
        self.spark.set_size_request(340, 70)
        self.spark.connect("draw", self.draw_spark)
        hist.pack_start(self.spark, False, False, 0)

        # tile statistik
        grid = Gtk.Grid(column_spacing=10, column_homogeneous=True)
        self.tiles = {}
        for i, (key, title) in enumerate((("avail", "Tersedia"), ("cache", "Cache"), ("swap", "Swap"))):
            tile, val = self.make_tile(title)
            self.tiles[key] = val
            grid.attach(tile, i, 0, 1, 1)
        root.pack_start(grid, False, False, 0)

        # saklar cepat pembersihan otomatis
        auto = self.card(root)
        row = Gtk.Box(spacing=10)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.pack_start(self.css(Gtk.Label(label="Bersihkan otomatis", xalign=0), "card-title"),
                        False, False, 0)
        self.auto_sub = self.css(Gtk.Label(label="", xalign=0), "muted")
        left.pack_start(self.auto_sub, False, False, 0)
        row.pack_start(left, True, True, 0)
        self.auto_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.auto_sw.set_active(self.cfg["auto_pct"])
        self.auto_sw_id = self.auto_sw.connect("notify::active", self.on_quick_auto)
        row.pack_end(self.auto_sw, False, False, 0)
        auto.pack_start(row, False, False, 0)

        # tombol bersihkan
        self.btn_clean = Gtk.Button()
        self.css(self.btn_clean, "clean")
        bx = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        bx.pack_start(Gtk.Image.new_from_icon_name("edit-clear-all-symbolic", Gtk.IconSize.BUTTON),
                      False, False, 0)
        self.btn_label = Gtk.Label(label="Bersihkan Memori")
        bx.pack_start(self.btn_label, False, False, 0)
        self.btn_clean.add(bx)
        self.btn_clean.connect("clicked", lambda *_: self.do_clean("manual"))
        root.pack_start(self.btn_clean, False, False, 0)

        self.status = self.css(Gtk.Label(label="Belum ada pembersihan", halign=Gtk.Align.CENTER), "muted")
        root.pack_start(self.status, False, False, 0)

        w.add(root)
        w.connect("delete-event", self.on_delete)
        self.win = w

    def on_quick_auto(self, sw, _pspec):
        self.set_opt("auto_pct", sw.get_active())

    def show_window(self):
        self.win.show_all()
        self.win.present()
        self.refresh_ui()

    def on_delete(self, win, _event):
        if self.indicator:
            win.hide()
            return True
        self.quit()
        return False

    def level(self, pct):
        return 2 if pct >= self.cfg["danger"] else 1 if pct >= self.cfg["warn"] else 0

    # ---- gambar: gauge
    def draw_gauge(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cx, cy = w / 2, h / 2 + 6
        r = min(w, h) / 2 - 26
        s0, sweep, lw = math.radians(135), math.radians(270), 18
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        cr.set_line_width(lw)
        cr.set_source_rgb(*rgb(C_TRACK))
        cr.arc(cx, cy, r, s0, s0 + sweep)
        cr.stroke()

        frac = max(0.0, min(1.0, self.disp / 100))
        lvl = self.level(self.st["pct"])
        if frac > 0.004:
            c1, c2 = LEVEL_COLORS[lvl]
            cr.set_line_width(lw + 14)
            cr.set_source_rgba(*rgb(c1), 0.12)
            cr.arc(cx, cy, r, s0, s0 + sweep * frac)
            cr.stroke()
            g = cairo.LinearGradient(cx - r, cy + r, cx + r, cy - r)
            g.add_color_stop_rgb(0, *rgb(c1))
            g.add_color_stop_rgb(1, *rgb(c2))
            cr.set_line_width(lw)
            cr.set_source(g)
            cr.arc(cx, cy, r, s0, s0 + sweep * frac)
            cr.stroke()

        # penanda ambang pembersihan otomatis
        a = s0 + sweep * self.cfg["auto_pct_value"] / 100
        cr.set_line_width(3)
        cr.set_source_rgba(1, 1, 1, 0.85 if self.cfg["auto_pct"] else 0.3)
        cr.move_to(cx + (r - 17) * math.cos(a), cy + (r - 17) * math.sin(a))
        cr.line_to(cx + (r + 17) * math.cos(a), cy + (r + 17) * math.sin(a))
        cr.stroke()

        text_center(cr, f"{round(self.disp)}%", cx, cy + 16, 54, C_TEXT, bold=True)
        text_center(cr, "RAM terpakai", cx, cy + 42, 12, C_MUTED)
        text_center(cr, f"{fmt(self.st['used'])} / {fmt(self.st['total'])}", cx, cy + 62, 12, C_TEXT, alpha=0.85)

    # ---- gambar: grafik riwayat
    def draw_spark(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        pad = 6
        thr_y = h - pad - (h - 2 * pad) * self.cfg["auto_pct_value"] / 100
        cr.set_line_width(1)
        cr.set_dash([4, 4])
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.move_to(0, thr_y)
        cr.line_to(w, thr_y)
        cr.stroke()
        cr.set_dash([])

        n = len(self.history)
        if n < 2:
            return
        step = (w - 8) / (self.history.maxlen - 1)
        x0 = w - 4 - (n - 1) * step
        pts = [(x0 + i * step, h - pad - (h - 2 * pad) * v / 100) for i, v in enumerate(self.history)]

        def path():
            cr.move_to(*pts[0])
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                mx = (x1 + x2) / 2
                cr.curve_to(mx, y1, mx, y2, x2, y2)

        path()
        cr.line_to(pts[-1][0], h)
        cr.line_to(pts[0][0], h)
        cr.close_path()
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgba(0, *rgb(C_ACCENT), 0.35)
        g.add_color_stop_rgba(1, *rgb(C_ACCENT), 0.0)
        cr.set_source(g)
        cr.fill()

        path()
        cr.set_line_width(2)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_source_rgb(*rgb(C_ACCENT))
        cr.stroke()

        cr.arc(pts[-1][0], pts[-1][1], 3.5, 0, 2 * math.pi)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    # ---- animasi gauge
    def start_anim(self):
        if not self._anim_id:
            self._anim_id = GLib.timeout_add(33, self._anim_step)

    def _anim_step(self):
        diff = self.st["pct"] - self.disp
        if abs(diff) < 0.2 or not self.win.get_visible():
            self.disp = float(self.st["pct"])
            self._anim_id = 0
            self.gauge.queue_draw()
            return False
        self.disp += diff * 0.18
        self.gauge.queue_draw()
        return True

    # ---- perbarui tampilan
    def refresh_ui(self):
        if self.win is None or not self.win.get_visible():
            return
        st = self.st
        lvl = self.level(st["pct"])
        ctx = self.chip.get_style_context()
        for c in CHIP_CLASSES:
            ctx.remove_class(c)
        ctx.add_class(CHIP_CLASSES[lvl])
        self.chip.set_text(LEVEL_NAMES[lvl])

        self.tiles["avail"].set_text(fmt(st["avail"]))
        self.tiles["cache"].set_text(fmt(st["cache"]))
        self.tiles["swap"].set_text(fmt(st["swap_used"]) if st["swap_total"] else "Tidak ada")

        if self.auto_sw.get_active() != self.cfg["auto_pct"]:
            self.auto_sw.handler_block(self.auto_sw_id)
            self.auto_sw.set_active(self.cfg["auto_pct"])
            self.auto_sw.handler_unblock(self.auto_sw_id)
        self.auto_sub.set_text(f"Saat RAM mencapai {self.cfg['auto_pct_value']}%"
                               if self.cfg["auto_pct"] else "Dimatikan")
        self.peak.set_text(f"maks {max(self.history)}%")

        if abs(st["pct"] - self.disp) >= 0.2:
            self.start_anim()
        self.gauge.queue_draw()
        self.spark.queue_draw()

    # ---- loop utama
    def tick(self):
        self.st = read_stats(self.cfg["count_cache"])
        self.history.append(self.st["pct"])
        self.refresh_ui()
        self.refresh_tray()
        now = time.monotonic()
        if not self.busy:
            if self.cfg["auto_pct"] and self.st["pct"] >= self.cfg["auto_pct_value"] \
                    and now - self.last_clean >= COOLDOWN:
                self.do_clean("auto")
            elif self.cfg["auto_interval"] \
                    and now - self.last_interval >= self.cfg["auto_interval_min"] * 60:
                self.do_clean("auto")
        return True

    # ---- pembersihan
    def area_flags(self):
        return [k for k in ("pagecache", "slab", "compact", "swap") if self.cfg.get("area_" + k)]

    def do_clean(self, source):
        if self.busy:
            return
        now = time.monotonic()
        flags = self.area_flags()
        if not flags:
            if source == "manual":
                self.message("Pilih minimal satu area pembersihan di Pengaturan > Pembersihan.")
            self.last_clean = self.last_interval = now
            return
        if os.geteuid() != 0 and not os.path.exists(HELPER):
            self.last_clean = self.last_interval = now
            if source == "manual":
                if self.confirm("Pembersihan memori memerlukan izin administrator.\n\n"
                                "Siapkan sekarang? (sekali saja, meminta password admin)"):
                    self.setup_helper(then=lambda: self.do_clean("manual"))
            return
        self.busy = True
        self.last_clean = self.last_interval = now
        if self.win:
            self.btn_label.set_text("Membersihkan...")
            self.btn_clean.set_sensitive(False)

        def work():
            before = read_stats(self.cfg["count_cache"])
            ok, err = run_helper(flags, allow_prompt=(source == "manual"))
            time.sleep(0.4)
            after = read_stats(self.cfg["count_cache"])
            GLib.idle_add(self.clean_done, source, ok, err, before, after)

        threading.Thread(target=work, daemon=True).start()

    def clean_done(self, source, ok, err, before, after):
        self.busy = False
        self.st = after
        self.history.append(after["pct"])
        if self.win:
            self.btn_label.set_text("Bersihkan Memori")
            self.btn_clean.set_sensitive(True)
        if ok:
            saved = before["used"] - after["used"]
            tail = f"hemat {fmt(saved)}" if saved > 0 else "tidak ada yang bisa dibebaskan"
            msg = f"{before['pct']}% -> {after['pct']}% ({tail})"
            if self.win:
                self.status.set_text(f"Terakhir {time.strftime('%H:%M:%S')}  |  {msg}")
            if self.cfg["notify"]:
                notify(("Pembersihan otomatis: " if source == "auto" else "Memori dibersihkan: ") + msg)
        else:
            if self.win:
                self.status.set_text(f"Gagal: {err or 'tidak diketahui'}")
            if source == "manual":
                self.message(f"Pembersihan gagal: {err or 'tidak diketahui'}")
        self.refresh_ui()
        self.refresh_tray()
        return False

    # ---- izin (helper + sudoers)
    def setup_helper(self, then=None):
        user = getpass.getuser()
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
            self.message("Nama user tidak didukung untuk penyiapan otomatis.")
            return

        def work():
            try:
                r = subprocess.run(["pkexec", "bash", "-c", SETUP_SCRIPT, "bash", HELPER_SCRIPT, user],
                                   capture_output=True, text=True)
                ok, err = r.returncode == 0, r.stderr.strip()
            except FileNotFoundError:
                ok, err = False, "pkexec tidak ditemukan"
            GLib.idle_add(done, ok, err)

        def done(ok, err):
            self.update_perm_label()
            if ok:
                if then:
                    then()
            else:
                self.message(f"Gagal menyiapkan izin: {err or 'dibatalkan'}")
            return False

        threading.Thread(target=work, daemon=True).start()

    def remove_helper(self):
        def work():
            try:
                subprocess.run(["pkexec", "rm", "-f", HELPER, SUDOERS], capture_output=True)
            except FileNotFoundError:
                pass
            GLib.idle_add(lambda: (self.update_perm_label(), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def update_perm_label(self):
        if self.perm_label:
            ok = os.path.exists(HELPER) and os.path.exists(SUDOERS)
            self.perm_label.set_text("Izin: aktif (tanpa password)" if ok else "Izin: belum disiapkan")

    # ---- dialog bantu
    def message(self, text):
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK, text=text)
        d.run()
        d.destroy()

    def confirm(self, text):
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.YES_NO, text=text)
        r = d.run()
        d.destroy()
        return r == Gtk.ResponseType.YES

    # ---- pengaturan
    def set_opt(self, key, value):
        self.cfg[key] = value
        save_config(self.cfg)
        if key == "autostart":
            self.write_autostart(value)
        if key == "count_cache":
            self.st = read_stats(self.cfg["count_cache"])
        self.refresh_ui()
        self.refresh_tray()

    def setting_row(self, box, title, sub=None):
        r = Gtk.Box(spacing=12)
        self.css(r, "setting-row")
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
        if sub:
            s = self.css(Gtk.Label(label=sub, xalign=0), "muted")
            s.set_line_wrap(True)
            s.set_max_width_chars(36)
            left.pack_start(s, False, False, 0)
        r.pack_start(left, True, True, 0)
        box.pack_start(r, False, False, 0)
        return r

    def switch_row(self, box, key, title, sub=None):
        r = self.setting_row(box, title, sub)
        sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        sw.set_active(self.cfg[key])
        sw.connect("notify::active", lambda w, _p: self.set_opt(key, w.get_active()))
        r.pack_end(sw, False, False, 0)

    def spin_row(self, box, key_on, key_val, title, lo, hi, suffix, sub=None):
        r = self.setting_row(box, title, sub)
        if key_on:
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            sw.set_active(self.cfg[key_on])
            sw.connect("notify::active", lambda w, _p: self.set_opt(key_on, w.get_active()))
            r.pack_end(sw, False, False, 0)
        r.pack_end(self.css(Gtk.Label(label=suffix), "muted"), False, False, 0)
        spin = Gtk.SpinButton.new_with_range(lo, hi, 1)
        spin.set_value(self.cfg[key_val])
        spin.connect("value-changed", lambda w: self.set_opt(key_val, int(w.get_value())))
        r.pack_end(spin, False, False, 0)

    def page(self):
        p = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for side in ("start", "end", "top", "bottom"):
            getattr(p, f"set_margin_{side}")(14)
        return p

    def show_settings(self):
        d = Gtk.Dialog(title="Pengaturan", transient_for=self.win, modal=True, use_header_bar=True)
        d.add_button("Tutup", Gtk.ResponseType.CLOSE)
        d.set_default_size(460, 560)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        g = self.page()
        self.switch_row(g, "autostart", "Jalankan saat login", "Mulai otomatis di tray setiap kali login")
        self.switch_row(g, "start_hidden", "Mulai tersembunyi", "Langsung ke tray tanpa membuka jendela")
        self.switch_row(g, "notify", "Notifikasi", "Tampilkan hasil setiap selesai membersihkan")
        self.switch_row(g, "count_cache", "Hitung cache sebagai terpakai", "Seperti perintah `free`; matikan "
                        "untuk menghitung RAM yang benar-benar dipakai aplikasi")
        self.spin_row(g, None, "warn", "Warna kuning mulai", 10, 98, "%")
        self.spin_row(g, None, "danger", "Warna merah mulai", 20, 99, "%")
        pr = self.setting_row(g, "Izin pembersihan")
        self.perm_label = self.css(Gtk.Label(label="", xalign=1), "muted")
        pr.pack_end(self.perm_label, False, False, 0)
        if not PACKAGED:
            brow = Gtk.Box(spacing=8, margin_top=10)
            b1 = Gtk.Button(label="Siapkan izin")
            b1.connect("clicked", lambda *_: self.setup_helper())
            b2 = Gtk.Button(label="Hapus izin")
            b2.connect("clicked", lambda *_: self.remove_helper())
            brow.pack_start(b1, False, False, 0)
            brow.pack_start(b2, False, False, 0)
            g.pack_start(brow, False, False, 0)
        self.update_perm_label()
        stack.add_titled(g, "umum", "Umum")

        c = self.page()
        self.spin_row(c, "auto_pct", "auto_pct_value", "Saat pemakaian mencapai", 30, 99, "%",
                      "Pembersihan otomatis berbasis ambang RAM")
        self.spin_row(c, "auto_interval", "auto_interval_min", "Berkala setiap", 1, 1440, "menit")
        self.switch_row(c, "clean_on_start", "Bersihkan saat dimulai")
        self.switch_row(c, "area_pagecache", "Page cache", "Cache isi file")
        self.switch_row(c, "area_slab", "Dentries & inodes", "Cache struktur file")
        self.switch_row(c, "area_compact", "Kompaksi memori", "Defragmentasi memori fisik")
        self.switch_row(c, "area_swap", "Bersihkan swap", "Hanya dijalankan jika RAM cukup")
        stack.add_titled(c, "bersih", "Pembersihan")

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(420)
        sw.add(stack)

        switcher = Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.CENTER, margin_top=10)
        area = d.get_content_area()
        area.pack_start(switcher, False, False, 0)
        area.pack_start(sw, True, True, 0)
        d.show_all()
        d.run()
        d.destroy()
        self.perm_label = None

    # ---- autostart & menu aplikasi
    def write_autostart(self, enable):
        if enable:
            os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
            with open(AUTOSTART_FILE, "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=MemReduct\n"
                        f"Exec={EXEC_CMD} --hidden\nIcon={ICON_NAME}\n"
                        "X-GNOME-Autostart-enabled=true\n")
        else:
            try:
                os.remove(AUTOSTART_FILE)
            except FileNotFoundError:
                pass

    def ensure_menu_entry(self):
        if PACKAGED or os.path.exists(MENU_FILE):
            return
        try:
            os.makedirs(os.path.dirname(MENU_FILE), exist_ok=True)
            with open(MENU_FILE, "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=MemReduct\n"
                        "Comment=Pembersih memori\n"
                        f"Exec=python3 {SCRIPT}\nIcon=utilities-system-monitor\n"
                        "Categories=System;Monitor;\n")
        except OSError:
            pass


if __name__ == "__main__":
    app = MemReduct(hidden="--hidden" in sys.argv)
    sys.exit(app.run([sys.argv[0]]))
