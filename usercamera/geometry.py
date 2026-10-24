"""All distances in mm, glyph heights in physical image pixels, angles in degrees."""
import math
import numpy as np


def visual_angle_deg(glyph_height_px, ppi, distance_mm):
    if not all(math.isfinite(x) and x > 0 for x in (glyph_height_px, ppi, distance_mm)):
        raise ValueError("glyph_height_px, ppi and distance_mm must be finite and positive")
    h_mm = 25.4 * glyph_height_px / ppi
    return math.degrees(2 * math.atan(h_mm / (2 * distance_mm)))


def gaze_vector(face_center, gaze_target):
    vector = np.asarray(gaze_target, dtype=float) - np.asarray(face_center, dtype=float)
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm < 1e-10:
        raise ValueError("Invalid gaze direction")
    return vector / norm


def angular_errors_deg(predicted, target):
    predicted, target = np.asarray(predicted), np.asarray(target)
    norms = np.linalg.norm(predicted, axis=1) * np.linalg.norm(target, axis=1)
    cosine = np.sum(predicted * target, axis=1) / np.maximum(norms, 1e-12)
    return np.degrees(np.arccos(np.clip(cosine, -1, 1)))


def ray_screen_intersection(eye, direction, origin, normal):
    eye, direction, origin, normal = [np.asarray(x, dtype=float) for x in (eye, direction, origin, normal)]
    denominator = float(normal @ direction)
    if abs(denominator) < 1e-10:
        raise ValueError("Gaze ray is parallel to screen")
    t = float(normal @ (origin - eye)) / denominator
    if t < 0:
        raise ValueError("Screen intersection lies behind eye")
    return eye + t * direction


def contrast_ratio(foreground, background=255):
    def linear(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    a, b = sorted([linear(foreground), linear(background)])
    return (b + 0.05) / (a + 0.05)
