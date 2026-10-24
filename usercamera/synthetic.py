"""Source-derived controlled redraws; no public face image is paired with a GUI."""
import itertools
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .geometry import contrast_ratio, visual_angle_deg
from .io import read_jsonl, sha256, write_json, write_jsonl


SCREEN_FEATURES = ["glyph_height_px", "contrast_ratio", "element_count", "target_x", "target_y"]
ACTION_FEATURES = ["elapsed_s", "clicks", "backs"]
USER_FEATURES = ["distance_estimate_mm", "head_yaw_deg", "head_pitch_deg"]


def load_font(size, font_path=None):
    candidates = [font_path] if font_path else [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size), candidate
    raise ValueError("No font available; pass --font /path/to/font.ttf")


def proxy_labels(angle, contrast, count, config):
    small = angle < config["angle_threshold_deg"]
    faint = contrast < config["contrast_threshold"]
    crowded = count >= config["density_count_threshold"]
    difficulty = "visual" if small or faint else "navigation_proxy" if crowded else "none"
    action = "hint" if faint else "zoom" if small else "hint" if crowded else "none"
    return difficulty, action


def synthesize(root, config_path, font_path=None, render=True):
    root = Path(root)
    config = json.loads(Path(config_path).read_text())
    for key in ("variants_per_screen", "max_screens_per_source", "width_px", "height_px", "ppi"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive")
    rng = np.random.default_rng(config["seed"])
    sources, counts, app_counts = [], {}, {}
    for screen in read_jsonl(root / "processed/screens.jsonl"):
        source = screen["source"]
        app = source + ":" + screen["app_id"]
        if (screen["elements"] and counts.get(source, 0) < config["max_screens_per_source"]
                and app_counts.get(app, 0) < config.get("max_screens_per_app", 3)):
            sources.append(screen)
            counts[source] = counts.get(source, 0) + 1
            app_counts[app] = app_counts.get(app, 0) + 1
    if not sources:
        raise ValueError("No annotated screens available")
    width, height = config["width_px"], config["height_px"]
    rows, previews = [], []
    font_cache = {s: load_font(s, font_path) for s in config["font_sizes_px"]}
    header_font, _ = load_font(24, font_path)
    factors = list(itertools.product(config["font_sizes_px"], config["distance_mm"],
                                     config["foreground_gray"], config["element_counts"]))
    if config["variants_per_screen"] > len(factors):
        raise ValueError("variants_per_screen exceeds number of unique factor combinations")
    output = root / "synthetic"
    for screen_index, source in enumerate(sources):
        source_hash = sha256(source["image_path"])
        # Every source receives randomized factors independently of its app and source ID.
        picks = rng.choice(len(factors), config["variants_per_screen"], replace=False)
        labels = [e["text"][:12] for e in source["elements"] if e.get("text")]
        # FunUI grounding boxes do not contain transcriptions: use disclosed template text.
        text_origin = "source hierarchy text" if labels else "template Chinese task vocabulary"
        if not labels:
            labels = ["医保支付", "医疗健康", "出行服务", "生活缴费", "扫一扫", "我的账单"]
        for variant, pick in enumerate(picks):
            size, distance, gray, count = factors[pick]
            font, actual_font = font_cache[size]
            cols = 2 if count <= 12 else 3
            nrows = math.ceil(count / cols)
            target_index = int(rng.integers(count))
            cell_w, cell_h = (width - 48) / cols, (height - 140) / nrows
            # Unique suffixes avoid ambiguous repeated targets in dense screens.
            displayed_texts = [labels[i % len(labels)][:3] + f"{i + 1:02d}" for i in range(count)]
            target_text = displayed_texts[target_index]
            measured = font.getbbox(target_text)
            glyph_height = measured[3] - measured[1]
            angle = visual_angle_deg(glyph_height, config["ppi"], distance)
            contrast = contrast_ratio(gray)
            difficulty, action = proxy_labels(angle, contrast, count, config)
            cx = 24 + (target_index % cols + 0.5) * cell_w
            cy = 100 + (target_index // cols + 0.5) * cell_h
            image_path = output / "images" / f"{screen_index:04d}_{variant:03d}.png"
            target_bbox = None
            if render:
                image = Image.new("RGB", (width, height), "white")
                draw = ImageDraw.Draw(image)
                draw.text((24, 25), "查找：" + target_text, fill=(20, 20, 20), font=header_font)
                for index in range(count):
                    text = displayed_texts[index]
                    x = 24 + (index % cols + 0.5) * cell_w
                    y = 100 + (index // cols + 0.5) * cell_h
                    # Draw exactly the font used to measure glyph height; no screenshot rescaling.
                    bounds = draw.textbbox((x, y), text, font=font, anchor="mm")
                    if not (0 <= bounds[0] < bounds[2] <= width and 80 <= bounds[1] < bounds[3] <= height):
                        raise ValueError("Synthetic text overflows screen; change density/font settings")
                    if index == target_index:
                        target_bbox = list(bounds)
                    draw.text((x, y), text, fill=(gray, gray, gray), font=font, anchor="mm")
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(image_path)
            row = {
                "id": f"synthetic:{screen_index}:{variant}", "evidence_tier": "synthetic_proxy",
                "source_screen_id": source["id"], "source_app_id": source["app_id"],
                "group_id": source["source"] + ":" + source["app_id"],
                "source_dataset": source["source"], "source_image_sha256": source_hash,
                "rendering": "controlled redraw; source text when available, otherwise template text",
                "text_origin": text_origin + "; truncated to 3 characters + unique numeric suffix", "font_path": actual_font,
                "target_text": target_text,
                "image_path": str(image_path.resolve()) if render else None, "target_bbox_px": target_bbox,
                "screen": {"glyph_height_px": glyph_height, "contrast_ratio": contrast,
                           "element_count": count, "target_x": cx / width, "target_y": cy / height},
                # Simulate actions independently of the labels, avoiding outcome-to-label leakage.
                "actions": {"elapsed_s": float(rng.uniform(1, 15)), "clicks": int(rng.integers(0, 5)),
                            "backs": int(rng.integers(0, 3))},
                "user": {"distance_estimate_mm": max(50, float(distance + rng.normal(0, config["distance_noise_sd_mm"]))),
                         "head_yaw_deg": float(rng.normal(0, 8)), "head_pitch_deg": float(rng.normal(0, 8))},
                "simulation_truth": {"distance_mm": distance, "ppi": config["ppi"], "visual_angle_deg": angle,
                                     "camera_feature_origin": "simulated geometry, not public face images"},
                "difficulty": difficulty, "intervention": action,
                "label_provenance": "deterministic configurable proxy rule, not human difficulty",
            }
            rows.append(row)
            if len(previews) < config["preview_count"] and render:
                previews.append(row)
    write_jsonl(output / "scenarios.jsonl", rows)
    if render and previews:
        sheet = Image.new("RGB", (4 * 180, math.ceil(len(previews) / 4) * 350), "#dddddd")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(previews):
            with Image.open(row["image_path"]) as image:
                tile = image.resize((180, 320))
            x, y = (i % 4) * 180, (i // 4) * 350
            sheet.paste(tile, (x, y))
            draw.text((x + 3, y + 322), row["intervention"] + " " + str(round(row["simulation_truth"]["visual_angle_deg"], 2)), fill="black")
        sheet.save(output / "contact_sheet.png")
    manifest = {"evidence_tier": "synthetic_proxy", "rows": len(rows), "source_screens": len(sources),
                "groups": len({r["group_id"] for r in rows}), "config": config,
                "input_screens_sha256": sha256(root / "processed/screens.jsonl"),
                "supports_real_H2_or_H3": False,
                "note": "Distance is simulated. A gain tests the chosen label mechanism, not camera usefulness."}
    write_json(output / "manifest.json", manifest)
    return manifest
