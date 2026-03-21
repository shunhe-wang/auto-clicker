"""
human_mouse.py — Bezier-curve mouse movement and human-like typing.

Generates realistic pointer paths (with overshoot, micro-jitter, and
speed easing) so automated interaction looks less robotic.
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Tuple


# ---------------------------------------------------------------------------
# Bezier path generation
# ---------------------------------------------------------------------------

Point = Tuple[float, float]


def _cubic_bezier(t: float, p0: Point, p1: Point, p2: Point, p3: Point) -> Point:
    """Evaluate a cubic Bezier curve at parameter *t* ∈ [0, 1]."""
    mt = 1.0 - t
    x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
    y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
    return (x, y)


def build_mouse_path(
    start: Point,
    end: Point,
    steps: int | None = None,
    overshoot_prob: float = 0.30,
) -> list[Point]:
    """
    Return a list of (x, y) waypoints from *start* to *end* that
    approximates how a human moves a mouse:

    - Cubic Bezier with randomised control points
    - Per-point Gaussian micro-jitter
    - Optional slight overshoot past the target, then correction
    """
    dist = math.hypot(end[0] - start[0], end[1] - start[1])
    if steps is None:
        steps = max(12, int(dist / 7) + random.randint(2, 6))

    deviation = max(20.0, dist * 0.28)

    cp1: Point = (
        start[0] + random.uniform(-deviation, deviation),
        start[1] + random.uniform(-deviation, deviation),
    )
    cp2: Point = (
        end[0] + random.uniform(-deviation, deviation),
        end[1] + random.uniform(-deviation, deviation),
    )

    jitter_scale = max(0.5, dist * 0.004)
    path: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        px, py = _cubic_bezier(t, start, cp1, cp2, end)
        px += random.gauss(0, jitter_scale)
        py += random.gauss(0, jitter_scale)
        path.append((px, py))

    # Optional overshoot: slightly past the target, then nudge back
    if dist > 80 and random.random() < overshoot_prob:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy) or 1.0
        over_d = random.uniform(4.0, 18.0)
        overshoot: Point = (end[0] + dx / length * over_d, end[1] + dy / length * over_d)
        path.append(overshoot)
        # Smooth correction back to end
        for k in range(1, 4):
            t = k / 3.0
            path.append((
                overshoot[0] + (end[0] - overshoot[0]) * t,
                overshoot[1] + (end[1] - overshoot[1]) * t,
            ))

    path.append(end)
    return path


# ---------------------------------------------------------------------------
# High-level async helpers
# ---------------------------------------------------------------------------

async def human_move(page, x: float, y: float, current: Point | None = None) -> Point:
    """
    Move the Playwright mouse to *(x, y)* along a human-like Bezier path.
    Speed follows a bell curve (slow at start/end, fast in the middle).
    Returns the new position so callers can chain moves.
    """
    if current is None:
        # We don't know where the cursor is — start from a plausible spot
        current = (random.uniform(300, 900), random.uniform(200, 700))

    path = build_mouse_path(current, (x, y))
    n = len(path)

    for i, (px, py) in enumerate(path):
        await page.mouse.move(px, py)
        t = i / max(n - 1, 1)
        speed = 4 * t * (1 - t)          # peaks at t=0.5
        delay = random.uniform(0.004, 0.012) * (1 + (1 - speed) * 1.8)
        await asyncio.sleep(delay)

    return (x, y)


async def human_click(
    page,
    x: float,
    y: float,
    current: Point | None = None,
    button: str = "left",
) -> Point:
    """
    Move to *(x, y)* with human-like motion, then click with a realistic
    hold duration.  Returns the new cursor position.
    """
    new_pos = await human_move(page, x, y, current)

    await asyncio.sleep(random.uniform(0.04, 0.14))   # pre-click pause
    await page.mouse.down(button=button)
    await asyncio.sleep(random.uniform(0.05, 0.13))   # hold duration
    await page.mouse.up(button=button)

    return new_pos


async def human_type(
    locator,
    text: str,
    clear_first: bool = True,
    typo_chance: float = 0.0,
) -> None:
    """
    Type *text* into a Playwright Locator with per-character delays that
    mimic human typing rhythm.  Optionally clears the field first.

    Parameters
    ----------
    typo_chance:
        Probability (0–1) of injecting a random typo + Backspace correction
        on any given character.  Default 0.0 (disabled).  Enable only on
        plain text fields — never on email, phone, or validated inputs.
    """
    if clear_first:
        await locator.fill("")
        await asyncio.sleep(random.uniform(0.08, 0.22))

    for i, ch in enumerate(text):
        # Optional typo + self-correction
        if typo_chance > 0 and random.random() < typo_chance and i < len(text) - 1:
            wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
            await locator.type(wrong, delay=0)
            await asyncio.sleep(random.uniform(0.08, 0.22))
            await locator.press("Backspace")
            await asyncio.sleep(random.uniform(0.04, 0.12))

        await locator.type(ch, delay=0)

        # Rhythm: spaces and punctuation cause a slightly longer pause
        if ch == " ":
            delay = random.uniform(0.07, 0.18)
        elif ch in ".,!?;:@":
            delay = random.uniform(0.09, 0.22)
        else:
            delay = max(0.02, min(0.22, random.gauss(0.065, 0.028)))

        await asyncio.sleep(delay)

        # Rare mid-word hesitation
        if random.random() < 0.015:
            await asyncio.sleep(random.uniform(0.25, 0.70))
