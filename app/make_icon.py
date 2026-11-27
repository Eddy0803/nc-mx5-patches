"""Draws NC Patcher's icon (app/ncpatcher.ico + app/ncpatcher.png): a rev counter with the redline and needle in the app's
coral accent, on the app's dark background. Each size is drawn on its own (4x supersampled), simpler at small sizes.
usage: python app/make_icon.py   (needs Pillow; only to regenerate the icon, not to run the app)"""
import math, os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BG, BORDER, ARC, TEXT, ACCENT = '#262624', '#4A4944', '#C2C0B6', '#F5F4EF', '#D97757'
START, SWEEP, RED_FROM, NEEDLE = 135.0, 270.0, 345.0, 322.0      # degrees, PIL convention (0 = 3 o'clock, clockwise)
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def draw(size):
    S = size * 4
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    u = lambda f: f * S
    small = size <= 32
    # background tile
    d.rounded_rectangle([u(0.02), u(0.02), u(0.98), u(0.98)], radius=u(0.2), fill=BG,
                        outline=None if small else BORDER, width=max(1, int(u(0.018))))
    cx, cy, r = u(0.5), u(0.53 if not small else 0.52), u(0.34 if not small else 0.39)
    w = max(4, int(u(0.075 if small else 0.06)))
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, START, RED_FROM, fill=ARC, width=w)                 # rev range
    d.arc(box, RED_FROM, START + SWEEP, fill=ACCENT, width=w)       # redline
    if not small:                                                   # tick marks every 1000 rpm (8 of them)
        for i in range(9):
            a = math.radians(START + SWEEP * i / 8)
            r1, r2 = r - w * 1.2, r - w * (2.4 if i % 2 == 0 else 1.9)
            d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a), cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
                   fill=ACCENT if START + SWEEP * i / 8 >= RED_FROM else ARC, width=max(2, int(u(0.018))))
    # needle
    a = math.radians(NEEDLE); L = r - w * (1.0 if small else 2.0)
    d.line([cx - u(0.05) * math.cos(a), cy - u(0.05) * math.sin(a), cx + L * math.cos(a), cy + L * math.sin(a)],
           fill=ACCENT, width=max(4, int(u(0.06 if small else 0.045))))
    hub = u(0.075 if small else 0.06)
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=ACCENT)
    d.ellipse([cx - hub * 0.45, cy - hub * 0.45, cx + hub * 0.45, cy + hub * 0.45], fill=BG)
    if size >= 48:                                                  # "NC" under the hub
        font = None
        for f in ('segoeuib.ttf', 'arialbd.ttf'):
            try:
                font = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', f), int(u(0.17))); break
            except OSError:
                pass
        font = font or ImageFont.load_default()
        tb = d.textbbox((0, 0), 'NC', font=font)
        d.text((cx - (tb[2] - tb[0]) / 2 - tb[0], u(0.86) - (tb[3] - tb[1]) - tb[1]), 'NC', font=font, fill=TEXT)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    imgs = {s: draw(s) for s in SIZES}
    ico = os.path.join(HERE, 'ncpatcher.ico'); png = os.path.join(HERE, 'ncpatcher.png')
    imgs[256].save(ico, format='ICO', sizes=[(s, s) for s in SIZES], append_images=[imgs[s] for s in SIZES if s != 256])
    imgs[256].save(png)
    print('wrote', ico, 'and', png)
