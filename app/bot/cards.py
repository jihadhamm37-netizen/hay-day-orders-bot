"""Generated images: the store banner and one card per farm type (Latin text only — no shaping needed)."""
from __future__ import annotations

import hashlib
import io
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
CARD_VERSION = "v3"

BG_TOP = (14, 52, 31)
BG_BOTTOM = (31, 112, 58)
CREAM = (247, 243, 230)
MINT = (190, 230, 200)
GOLD = (242, 193, 78)
WHITE = (255, 255, 255)
TILE = (255, 255, 255, 26)
TILE_LINE = (255, 255, 255, 60)


@lru_cache(maxsize=32)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Poppins-{weight}.ttf"), size)


def _gradient(w: int, h: int) -> Image.Image:
    col = Image.new("RGB", (1, 256))
    for y in range(256):
        k = y / 255
        col.putpixel((0, y), tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * k) for i in range(3)))
    img = col.resize((w, h), Image.BILINEAR).convert("RGBA")
    light = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(light).ellipse((w * 0.35, -h * 0.4, w * 1.2, h * 0.7), fill=(255, 255, 255, 22))
    img.alpha_composite(light.filter(ImageFilter.GaussianBlur(80)))
    return img.convert("RGB")


def _farm_scene(draw: ImageDraw.ImageDraw, w: int, h: int, scale: float = 1.0) -> None:
    """Minimal flat illustration: hills, a barn and a silo along the bottom edge."""
    s = scale
    draw.ellipse((-0.2 * w, h - 120 * s, 0.75 * w, h + 260 * s), fill=(44, 140, 70))
    draw.ellipse((0.45 * w, h - 90 * s, 1.3 * w, h + 280 * s), fill=(38, 125, 63))
    bx, by = w - 330 * s, h - 150 * s
    # barn
    draw.rectangle((bx, by, bx + 150 * s, by + 110 * s), fill=(196, 58, 44))
    draw.polygon([(bx - 12 * s, by + 4 * s), (bx + 75 * s, by - 62 * s), (bx + 162 * s, by + 4 * s)], fill=(160, 40, 32))
    draw.rectangle((bx + 52 * s, by + 46 * s, bx + 98 * s, by + 110 * s), fill=CREAM)
    draw.line((bx + 52 * s, by + 46 * s, bx + 98 * s, by + 110 * s), fill=(196, 58, 44), width=int(5 * s))
    draw.line((bx + 98 * s, by + 46 * s, bx + 52 * s, by + 110 * s), fill=(196, 58, 44), width=int(5 * s))
    # silo
    sx = bx + 175 * s
    draw.rectangle((sx, by - 40 * s, sx + 62 * s, by + 110 * s), fill=(214, 214, 205))
    draw.pieslice((sx, by - 72 * s, sx + 62 * s, by - 8 * s), 180, 360, fill=(150, 160, 160))
    for i in range(1, 5):
        yy = by - 40 * s + i * 30 * s
        draw.line((sx, yy, sx + 62 * s, yy), fill=(185, 185, 175), width=int(3 * s))


def _rounded_panel(base: Image.Image, box, radius: int, fill, outline=None) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2 if outline else 0)
    base.alpha_composite(layer)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _num(n) -> str:
    return f"{int(n or 0):,}"


# ------------------------------------------------------------------ banner
def banner_hash(store_name: str) -> str:
    return hashlib.sha1(f"banner|{CARD_VERSION}|{store_name}".encode()).hexdigest()[:16]


def render_banner(store_name: str = "HD FARM STORE") -> bytes:
    w, h = 1280, 640
    img = _gradient(w, h).convert("RGBA")
    d = ImageDraw.Draw(img)
    # sun glow
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((w - 430, 40, w - 170, 300), fill=(255, 214, 102, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40)))
    d = ImageDraw.Draw(img)
    d.ellipse((w - 360, 100, w - 240, 220), fill=(255, 214, 102))
    _farm_scene(d, w, h, 1.15)
    d.text((80, 120), "HAY DAY", font=font("Medium", 40), fill=MINT)
    title = store_name.upper()
    size = 104
    while font("Bold", size).getlength(title) > w - 520 and size > 50:
        size -= 4
    d.text((76, 168), title, font=font("Bold", size), fill=WHITE)
    tags = ["INSTANT DELIVERY", "USDT WALLET", "BINANCE PAY"]
    x = 82
    y = 168 + size + 40
    for tag in tags:
        tw = font("Medium", 26).getlength(tag)
        _rounded_panel(img, (x, y, x + tw + 44, y + 50), 25, (255, 255, 255, 34), (255, 255, 255, 90))
        ImageDraw.Draw(img).text((x + 22, y + 9), tag, font=font("Medium", 26), fill=CREAM)
        x += tw + 64
    return _png(img)


# --------------------------------------------------------------- farm card
def card_hash(tp: dict) -> str:
    key = f"card|{CARD_VERSION}|{tp['lvl']}|{tp['barn']}|{tp['silo']}|{tp.get('tools') or 0}|{Decimal(tp['price'])}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _icon(d: ImageDraw.ImageDraw, kind: str, x: int, y: int, c=CREAM) -> None:
    if kind == "barn":
        d.rectangle((x + 6, y + 22, x + 50, y + 52), fill=c)
        d.polygon([(x, y + 24), (x + 28, y), (x + 56, y + 24)], fill=c)
        d.rectangle((x + 20, y + 34, x + 36, y + 52), fill=BG_TOP)
    elif kind == "silo":
        d.rectangle((x + 14, y + 16, x + 42, y + 52), fill=c)
        d.pieslice((x + 14, y + 2, x + 42, y + 30), 180, 360, fill=c)
        d.line((x + 14, y + 30, x + 42, y + 30), fill=BG_TOP, width=3)
        d.line((x + 14, y + 41, x + 42, y + 41), fill=BG_TOP, width=3)
    elif kind == "tools":
        d.polygon([(x + 8, y + 46), (x + 36, y + 18), (x + 42, y + 24), (x + 14, y + 52)], fill=c)
        d.rounded_rectangle((x + 28, y + 2, x + 54, y + 22), radius=4, fill=c)
    elif kind == "price":
        d.ellipse((x + 4, y + 4, x + 52, y + 52), outline=GOLD, width=5)
        d.text((x + 28, y + 28), "$", font=font("Bold", 30), fill=GOLD, anchor="mm")


def render_farm_card(tp: dict, store_name: str = "HD FARM STORE") -> bytes:
    w, h = 1280, 720
    img = _gradient(w, h).convert("RGBA")
    d = ImageDraw.Draw(img)
    _farm_scene(d, w, h, 0.8)
    d = ImageDraw.Draw(img)
    d.text((72, 56), store_name.upper(), font=font("Medium", 30), fill=MINT)
    d.text((68, 96), "LEVEL", font=font("Medium", 44), fill=CREAM)
    d.text((64, 140), str(tp["lvl"]), font=font("Bold", 150), fill=WHITE)
    # price badge
    price = f"{Decimal(tp['price']):.2f}".rstrip("0").rstrip(".")
    ptxt = f"{price} USDT"
    pw = font("Bold", 54).getlength(ptxt)
    _rounded_panel(img, (w - pw - 140, 70, w - 64, 160), 45, (242, 193, 78, 255))
    d = ImageDraw.Draw(img)
    d.text((w - 102, 115), ptxt, font=font("Bold", 54), fill=BG_TOP, anchor="rm")
    # stat tiles
    stats = [("barn", "BARN", _num(tp["barn"])), ("silo", "SILO", _num(tp["silo"])),
             ("tools", "TOOLS", _num(tp.get("tools")))]
    tw, th, gap, top = 352, 190, 32, 360
    for i, (kind, label, value) in enumerate(stats):
        x0 = 64 + i * (tw + gap)
        _rounded_panel(img, (x0, top, x0 + tw, top + th), 28, TILE, TILE_LINE)
        d = ImageDraw.Draw(img)
        _icon(d, kind, x0 + 30, top + 30)
        d.text((x0 + 104, top + 40), label, font=font("Medium", 30), fill=MINT)
        vs = 68
        while font("Bold", vs).getlength(value) > tw - 60 and vs > 36:
            vs -= 4
        d.text((x0 + 30, top + 100), value, font=font("Bold", vs), fill=WHITE)
    return _png(img)
