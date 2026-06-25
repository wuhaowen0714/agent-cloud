"""生成 app 启动图标素材(火花 logo)。

产出 assets/icon/ 下三张 1024 PNG,供 flutter_launcher_icons 使用:
- foreground.png: 白火花 + 透明底(自适应图标前景,居中在安全区内)
- background.png : teal 渐变(自适应图标背景)
- icon.png       : 渐变圆角方 + 白火花(legacy 全图)

跑法: cd apps/mobile && python3 tool/gen_icon.py
"""

import math
import os

from PIL import Image, ImageDraw

OUT = "assets/icon"
S = 1024
SS = 2  # 超采样抗锯齿
size = S * SS

C1 = (45, 212, 191)  # teal-400 #2DD4BF
C2 = (15, 118, 110)  # teal-700 #0F766E


def spark(draw, cx, cy, tip, fill):
    """四角火花(8 点星):tip = 长半径,谷 = 0.36*tip。"""
    valley = tip * 0.36
    pts = []
    for i in range(8):
        ang = math.radians(90 - i * 45)
        rad = tip if i % 2 == 0 else valley
        pts.append((cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def teal_gradient(sz):
    """对角 teal 渐变;低分辨率算好再放大(平滑)。"""
    base = 64
    img = Image.new("RGB", (base, base))
    px = img.load()
    for y in range(base):
        for x in range(base):
            t = (x / base + y / base) / 2
            px[x, y] = (
                int(C1[0] + (C2[0] - C1[0]) * t),
                int(C1[1] + (C2[1] - C1[1]) * t),
                int(C1[2] + (C2[2] - C1[2]) * t),
            )
    return img.resize((sz, sz), Image.BILINEAR)


def main():
    os.makedirs(OUT, exist_ok=True)
    cx = cy = size / 2

    # background.png — 渐变铺满
    teal_gradient(size).resize((S, S), Image.LANCZOS).save(f"{OUT}/background.png")

    # foreground.png — 白火花 + 透明底(占中心 ~60%,落在自适应安全区内)
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    spark(ImageDraw.Draw(fg), cx, cy, size * 0.30, (255, 255, 255, 255))
    fg.resize((S, S), Image.LANCZOS).save(f"{OUT}/foreground.png")

    # icon.png — 渐变圆角方 + 白火花(legacy)
    grad = teal_gradient(size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255
    )
    ic = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ic.paste(grad, (0, 0), mask)
    spark(ImageDraw.Draw(ic), cx, cy, size * 0.30, (255, 255, 255, 255))
    ic.resize((S, S), Image.LANCZOS).save(f"{OUT}/icon.png")

    print("✓ 生成", os.listdir(OUT))


if __name__ == "__main__":
    main()
