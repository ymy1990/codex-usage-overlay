import math
import struct
import zlib
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parent / "assets"
PNG_PATH = OUT_DIR / "codex_usage_overlay_icon.png"
ICO_PATH = OUT_DIR / "codex_usage_overlay_icon.ico"


def clamp(value, low=0, high=255):
    return max(low, min(high, int(round(value))))


def mix(a, b, t):
    return a + (b - a) * t


def rgba(r, g, b, a=255):
    return (clamp(r), clamp(g), clamp(b), clamp(a))


def over(dst, src):
    sr, sg, sb, sa = src
    dr, dg, db, da = dst
    sa_f = sa / 255
    da_f = da / 255
    out_a = sa_f + da_f * (1 - sa_f)
    if out_a <= 0:
        return (0, 0, 0, 0)
    out_r = (sr * sa_f + dr * da_f * (1 - sa_f)) / out_a
    out_g = (sg * sa_f + dg * da_f * (1 - sa_f)) / out_a
    out_b = (sb * sa_f + db * da_f * (1 - sa_f)) / out_a
    return rgba(out_r, out_g, out_b, out_a * 255)


def rounded_rect_sdf(x, y, cx, cy, half_w, half_h, radius):
    qx = abs(x - cx) - (half_w - radius)
    qy = abs(y - cy) - (half_h - radius)
    ox = max(qx, 0)
    oy = max(qy, 0)
    outside = math.hypot(ox, oy)
    inside = min(max(qx, qy), 0)
    return outside + inside - radius


def line_alpha(px, py, ax, ay, bx, by, width):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    denom = vx * vx + vy * vy
    t = 0 if denom == 0 else max(0, min(1, (wx * vx + wy * vy) / denom))
    dx = px - (ax + t * vx)
    dy = py - (ay + t * vy)
    distance = math.hypot(dx, dy)
    return max(0, min(1, (width / 2 + 1 - distance)))


STATUS_COLORS = {
    "red": (248, 82, 92),
    "yellow": (250, 196, 61),
    "green": (66, 224, 137),
}


def render_icon(size, status="all"):
    pixels = []

    for y in range(size):
        row = []
        for x in range(size):
            nx = (x + 0.5) / size * 256
            ny = (y + 0.5) / size * 256
            d = rounded_rect_sdf(nx, ny, 128, 128, 112, 112, 42)
            alpha = max(0, min(1, 0.5 - d))
            if alpha <= 0:
                row.append((0, 0, 0, 0))
                continue

            radial = min(1, math.hypot(nx - 128, ny - 116) / 158)
            top_light = max(0, 1 - ny / 256)
            bg = rgba(
                mix(15, 5, radial) + top_light * 8,
                mix(29, 13, radial) + top_light * 9,
                mix(44, 28, radial) + top_light * 16,
                alpha * 255,
            )

            ring_r = math.hypot(nx - 128, ny - 128)
            ring_alpha = max(0, 1 - abs(ring_r - 91) / 6)
            if ring_alpha:
                bg = over(bg, rgba(135, 235, 239, 190 * ring_alpha))

            lights = [
                ("red", 73, 128),
                ("yellow", 128, 128),
                ("green", 183, 128),
            ]

            for name, cx, cy in lights:
                active = status in {"all", name}
                color = STATUS_COLORS[name] if active else (48, 63, 75)
                distance = math.hypot(nx - cx, ny - cy)
                if active:
                    glow = max(0, min(1, 1 - (distance - 27) / 20))
                    if glow:
                        bg = over(bg, rgba(*color, 68 * glow))

                dot_alpha = max(0, min(1, 28.5 - distance))
                if dot_alpha:
                    bg = over(bg, rgba(*color, (250 if active else 145) * dot_alpha))

                edge_alpha = max(0, 1 - abs(distance - 28) / 3)
                if edge_alpha:
                    edge = (255, 255, 255) if active else (91, 112, 123)
                    bg = over(bg, rgba(*edge, (145 if active else 70) * edge_alpha))

                highlight = max(0, min(1, 7 - math.hypot(nx - (cx - 8), ny - (cy - 8))))
                if active and highlight:
                    bg = over(bg, rgba(255, 255, 255, 175 * highlight))

            border = max(0, 1 - abs(d + 0.5) / 2.2)
            if border:
                bg = over(bg, rgba(160, 248, 255, 85 * border))

            row.append(bg)
        pixels.append(row)
    return pixels


def write_png(path, pixels):
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for r, g, b, a in row:
            raw.extend((r, g, b, a))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
    png.extend(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
    png.extend(chunk(b"IEND", b""))
    path.write_bytes(png)
    return bytes(png)


def write_ico(path, images):
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = bytearray()
    payload = bytearray()
    offset = 6 + 16 * len(images)

    for size, data in images:
        width_byte = 0 if size >= 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                width_byte,
                width_byte,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payload.extend(data)
        offset += len(data)

    path.write_bytes(header + entries + payload)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sizes = (16, 24, 32, 48, 64, 128, 256)

    for status in ("all", "red", "yellow", "green"):
        suffix = "" if status == "all" else f"_{status}"
        images = []
        for size in sizes:
            png_path = OUT_DIR / f"codex_usage_overlay_icon{suffix}_{size}.png"
            png = write_png(png_path, render_icon(size, status))
            images.append((size, png))
        preview_path = OUT_DIR / f"codex_usage_overlay_icon{suffix}.png"
        ico_path = OUT_DIR / f"codex_usage_overlay_icon{suffix}.ico"
        write_png(preview_path, render_icon(256, status))
        write_ico(ico_path, images)

    print(ICO_PATH)


if __name__ == "__main__":
    main()
