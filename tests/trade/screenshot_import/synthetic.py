"""Synthetic trade-calculator screenshots for the screenshot-import tests.

Each scenario is drawn with Pillow (no real site's branding or layout is
copied) and saved under ``tests/fixtures/screenshot_import/<name>/`` as
``image.png`` + ``expected.json``.  Regenerate with::

    python -m tests.trade.screenshot_import.synthetic

The committed PNGs are what the real-tesseract tests and
``scripts/screenshot_import_eval.py`` read, so results do not depend on the
fonts installed on the machine running them.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "screenshot_import"
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)

# (text, x, y) in a W x H canvas; "bold" rows drawn larger.
SCENARIOS: dict[str, dict] = {
    "light_two_column": {
        "size": (1240, 760),
        "dark": False,
        "font_size": 30,
        "texts": [
            ("Trade Calculator", 60, 20),
            ("You give", 60, 100),
            ("You get", 680, 100),
            ("Patrick Mahomes QB KC", 60, 180),
            ("9,999", 480, 180),
            ("2027 1st", 60, 250),
            ("4,512", 480, 250),
            ("Quay Walker LB LV", 60, 320),
            ("2,100", 480, 320),
            ("Bijan Robinson", 680, 180),
            ("8,100", 1100, 180),
            ("Jaxon Smith-Njigba", 680, 250),
            ("6,050", 1100, 250),
            ("2028 Early 2nd", 680, 320),
            ("1,200", 1100, 320),
            ("Suggested", 680, 430),
            ("Chris Jones DT KC", 680, 500),
            ("2,300", 1100, 500),
            ("Total", 60, 640),
            ("16,611", 480, 640),
        ],
        "expected": {
            "layoutKind": "two_column",
            "sides": [
                {
                    "label": "You give",
                    "assets": [
                        {"text": "Patrick Mahomes", "boardName": "Patrick Mahomes"},
                        {"text": "2027 1st", "boardName": "2027 Round 1"},
                        {"text": "Quay Walker", "boardName": "Quay Walker"},
                    ],
                },
                {
                    "label": "You get",
                    "assets": [
                        {"text": "Bijan Robinson", "boardName": "Bijan Robinson"},
                        {"text": "Jaxon Smith-Njigba", "boardName": "Jaxon Smith-Njigba"},
                        {"text": "2028 Early 2nd", "boardName": "2028 Early 2nd"},
                    ],
                },
            ],
            "mustBeIgnored": ["Chris Jones"],
        },
    },
    "dark_two_column": {
        "size": (1240, 700),
        "dark": True,
        "font_size": 30,
        "texts": [
            ("Sending", 60, 80),
            ("Receiving", 680, 80),
            ("Josh Allen QB BUF", 60, 160),
            ("8,800", 480, 160),
            ("2027 Early 1st", 60, 230),
            ("5,100", 480, 230),
            ("Travis Hunter", 680, 160),
            ("6,400", 1100, 160),
            ("Jordan Davis DL PHI", 680, 230),
            ("1,900", 1100, 230),
            ("2027 1st", 680, 300),
            ("4,512", 1100, 300),
            ("Add to even", 60, 420),
            ("Marvin Harrison Jr. WR ARI", 60, 490),
        ],
        "expected": {
            "layoutKind": "two_column",
            "sides": [
                {
                    "label": "Sending",
                    "assets": [
                        {"text": "Josh Allen", "boardName": "Josh Allen"},
                        {"text": "2027 Early 1st", "boardName": "2027 Early 1st"},
                    ],
                },
                {
                    "label": "Receiving",
                    "assets": [
                        {"text": "Travis Hunter", "boardName": "Travis Hunter"},
                        {"text": "Jordan Davis", "boardName": "Jordan Davis"},
                        {"text": "2027 1st", "boardName": "2027 Round 1"},
                    ],
                },
            ],
            "mustBeIgnored": ["Marvin Harrison"],
        },
    },
    "stacked_mobile": {
        "size": (760, 1500),
        "dark": False,
        "font_size": 34,
        "texts": [
            ("Team A", 40, 80),
            ("Bijan Robinson", 40, 170),
            ("8,100", 600, 170),
            ("2027 1st", 40, 250),
            ("4,512", 600, 250),
            ("2027 1st", 40, 330),
            ("4,512", 600, 330),
            ("Team B", 40, 480),
            ("Patrick Mahomes", 40, 570),
            ("9,999", 600, 570),
            ("Jordan Davis DL PHI", 40, 650),
            ("1,900", 600, 650),
            ("Recommended", 40, 820),
            ("Brian Thomas Jr.", 40, 900),
            ("7,700", 600, 900),
            ("Accept", 40, 1200),
            ("Decline", 400, 1200),
        ],
        "expected": {
            "layoutKind": "stacked",
            "sides": [
                {
                    "label": "Team A",
                    "assets": [
                        {"text": "Bijan Robinson", "boardName": "Bijan Robinson"},
                        {"text": "2027 1st", "boardName": "2027 Round 1"},
                        {"text": "2027 1st", "boardName": "2027 Round 1"},
                    ],
                },
                {
                    "label": "Team B",
                    "assets": [
                        {"text": "Patrick Mahomes", "boardName": "Patrick Mahomes"},
                        {"text": "Jordan Davis", "boardName": "Jordan Davis"},
                    ],
                },
            ],
            "mustBeIgnored": ["Brian Thomas"],
        },
    },
    "small_no_anchor_columns": {
        "size": (900, 420),
        "dark": False,
        "font_size": 18,
        "texts": [
            ("Patrick Mahomes", 30, 60),
            ("2029 3rd", 30, 110),
            ("Byron Young", 30, 160),
            ("Bijan Robinson", 520, 60),
            ("2027 Mid 1st", 520, 110),
        ],
        "expected": {
            "layoutKind": "two_column",
            "strict": False,
            "sides": [
                {
                    "label": "Side A",
                    "assets": [
                        {"text": "Patrick Mahomes", "boardName": "Patrick Mahomes"},
                        {"text": "2029 3rd", "boardName": "2029 Round 3"},
                        {"text": "Byron Young", "boardName": None, "status": "needs_confirmation"},
                    ],
                },
                {
                    "label": "Side B",
                    "assets": [
                        {"text": "Bijan Robinson", "boardName": "Bijan Robinson"},
                        {"text": "2027 Mid 1st", "boardName": "2027 Mid 1st"},
                    ],
                },
            ],
            "mustBeIgnored": [],
        },
    },
}


def _font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render(name: str):
    """The scenario as an RGB PIL image."""
    from PIL import Image, ImageDraw

    spec = SCENARIOS[name]
    bg, fg = ((24, 26, 32), (235, 235, 240)) if spec["dark"] else ((255, 255, 255), (20, 20, 20))
    img = Image.new("RGB", spec["size"], bg)
    draw = ImageDraw.Draw(img)
    font = _font(spec["font_size"])
    for text, x, y in spec["texts"]:
        draw.text((x, y), text, font=font, fill=fg)
    return img


def write_fixtures(out_dir: Path = FIXTURE_DIR) -> list[Path]:
    written = []
    for name, spec in SCENARIOS.items():
        d = out_dir / name
        d.mkdir(parents=True, exist_ok=True)
        render(name).save(d / "image.png", format="PNG")
        (d / "expected.json").write_text(
            json.dumps(spec["expected"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(d)
    return written


if __name__ == "__main__":
    for path in write_fixtures():
        print(path)
