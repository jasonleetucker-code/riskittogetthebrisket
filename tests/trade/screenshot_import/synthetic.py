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

# (text, x, y) in a W x H canvas, or (text, x, y, {"fill": rgb, "size": px})
# for a row with its own colour / size.  Optional "boxes":
# [(x0, y0, x1, y1, rgb)] are filled first — dark header bars, sidebars,
# buttons and ad blocks, the page furniture of an UNCROPPED screenshot.
_WHITE = (255, 255, 255)
_BAR = (88, 92, 99)
_NAV = (24, 60, 98)
_GREY = (120, 120, 120)

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


# Full-page scenarios: the trade sits inside ordinary page furniture, with
# OTHER board players in the navigation, an insights widget and an ad, which
# must never be imported.
SCENARIOS.update(
    {
        "fullpage_desktop_multi": {
            "size": (1600, 1000),
            "dark": False,
            "font_size": 22,
            "boxes": [
                (0, 0, 1600, 70, (40, 40, 46)),
                (0, 70, 230, 1000, _NAV),
                (270, 180, 750, 235, _BAR),
                (800, 180, 1280, 235, _BAR),
                (270, 700, 1280, 750, (226, 238, 250)),
                (520, 780, 760, 830, (40, 140, 220)),
                (800, 780, 1040, 830, _BAR),
                (1320, 170, 1580, 470, (243, 246, 250)),
                (270, 870, 1280, 990, (246, 246, 246)),
            ],
            "texts": [
                ("TradeLab", 20, 22, {"fill": _WHITE}),
                ("Rankings", 300, 22, {"fill": _WHITE}),
                ("Leagues", 450, 22, {"fill": _WHITE}),
                ("Sign in", 1460, 22, {"fill": _WHITE}),
                ("Dashboard", 20, 110, {"fill": _WHITE}),
                ("Waivers", 20, 160, {"fill": _WHITE}),
                ("Trending", 20, 260, {"fill": _WHITE}),
                ("Chris Jones", 20, 300, {"fill": _WHITE}),
                ("Kenneth Walker III", 20, 340, {"fill": _WHITE}),
                ("Dynasty Trade Calculator", 270, 100, {"size": 34}),
                ("Team A gets...", 290, 194, {"fill": _WHITE}),
                ("Team B gets...", 820, 194, {"fill": _WHITE}),
                ("Search for a player", 290, 262, {"fill": _GREY}),
                ("Search for a player", 820, 262, {"fill": _GREY}),
                ("Patrick Mahomes", 290, 330),
                ("QB · KC · 30 y.o.", 520, 333, {"fill": _GREY, "size": 18}),
                ("8,412", 680, 330),
                ("Quay Walker", 290, 390),
                ("LB · LV · 26 y.o.", 520, 393, {"fill": _GREY, "size": 18}),
                ("2,100", 680, 390),
                ("Jaxon Smith-Njigba", 290, 450),
                ("6,050", 680, 450),
                ("2027 Early 1st", 290, 510),
                ("5,100", 680, 510),
                ("2028 2nd", 290, 570),
                ("1,900", 680, 570),
                ("Bijan Robinson", 820, 330),
                ("RB · ATL · 24 y.o.", 1040, 333, {"fill": _GREY, "size": 18}),
                ("8,100", 1200, 330),
                ("Travis Hunter", 820, 390),
                ("6,400", 1200, 390),
                ("Jordan Davis", 820, 450),
                ("DL · PHI · 26 y.o.", 1040, 453, {"fill": _GREY, "size": 18}),
                ("1,900", 1200, 450),
                ("2027 Mid 1st", 820, 510),
                ("4,600", 1200, 510),
                ("2029 3rd", 820, 570),
                ("700", 1200, 570),
                ("5 Total Pieces", 290, 640, {"fill": _GREY}),
                ("23,562", 660, 640),
                ("5 Total Pieces", 820, 640, {"fill": _GREY}),
                ("21,700", 1180, 640),
                ("Slightly favors Team A", 650, 712, {"fill": (30, 90, 160)}),
                ("Copy Trade URL", 545, 793, {"fill": _WHITE}),
                ("Clear Calculator", 820, 793, {"fill": _WHITE}),
                ("INSIGHTS", 1340, 185, {"size": 18}),
                ("Biggest riser", 1340, 225, {"size": 18}),
                ("Brian Thomas Jr.", 1340, 260),
                ("WR · JAX", 1340, 292, {"fill": _GREY, "size": 18}),
                ("Biggest faller", 1340, 345, {"size": 18}),
                ("Josh Allen", 1340, 380),
                ("QB · BUF", 1340, 412, {"fill": _GREY, "size": 18}),
                ("SHOP THE SALE", 300, 900, {"size": 32}),
                ("Free shipping on every order", 700, 910),
            ],
            "expected": {
                "layoutKind": "two_column",
                "sides": [
                    {
                        "label": "Team A gets",
                        "assets": [
                            {"text": "Patrick Mahomes", "boardName": "Patrick Mahomes"},
                            {"text": "Quay Walker", "boardName": "Quay Walker"},
                            {"text": "Jaxon Smith-Njigba", "boardName": "Jaxon Smith-Njigba"},
                            {"text": "2027 Early 1st", "boardName": "2027 Early 1st"},
                            {"text": "2028 2nd", "boardName": "2028 Round 2"},
                        ],
                    },
                    {
                        "label": "Team B gets",
                        "assets": [
                            {"text": "Bijan Robinson", "boardName": "Bijan Robinson"},
                            {"text": "Travis Hunter", "boardName": "Travis Hunter"},
                            {"text": "Jordan Davis", "boardName": "Jordan Davis"},
                            {"text": "2027 Mid 1st", "boardName": "2027 Mid 1st"},
                            {"text": "2029 3rd", "boardName": "2029 Round 3"},
                        ],
                    },
                ],
                "mustBeIgnored": ["Chris Jones", "Kenneth Walker", "Brian Thomas", "Josh Allen"],
                "forbiddenWarnings": ["missing_side", "trade_region_not_detected"],
            },
        },
        "fullpage_mobile_stacked": {
            "size": (1080, 2200),
            "dark": False,
            "font_size": 40,
            "boxes": [
                (0, 80, 1080, 200, (30, 34, 40)),
                (30, 260, 1050, 350, _BAR),
                (30, 820, 1050, 910, _BAR),
                (30, 1480, 1050, 1570, (226, 238, 250)),
                (30, 1880, 1050, 2150, (246, 246, 246)),
            ],
            "texts": [
                ("9:41", 40, 20, {"size": 34}),
                ("Trade Calculator", 40, 115, {"fill": _WHITE, "size": 44}),
                ("Menu", 900, 120, {"fill": _WHITE}),
                ("Team 1 gets...", 60, 282, {"fill": _WHITE}),
                ("Search for a player", 60, 392, {"fill": _GREY}),
                ("Kenneth Walker III", 60, 480),
                ("RB · KC", 560, 486, {"fill": _GREY, "size": 32}),
                ("4,100", 880, 480),
                ("2027 Late 1st", 60, 600),
                ("3,900", 880, 600),
                ("2 Total Pieces", 60, 720, {"fill": _GREY}),
                ("Team 2 gets...", 60, 842, {"fill": _WHITE}),
                ("Search for a player", 60, 952, {"fill": _GREY}),
                ("Josh Hines-Allen", 60, 1040),
                ("3,300", 880, 1040),
                ("Marvin Harrison Jr.", 60, 1160),
                ("4,800", 880, 1160),
                ("2026 1.05", 60, 1280),
                ("2,950", 880, 1280),
                ("3 Total Pieces", 60, 1400, {"fill": _GREY}),
                ("Fair Trade", 420, 1502, {"fill": (30, 90, 160)}),
                ("Trending players", 60, 1640, {"size": 36}),
                ("Bijan Robinson", 60, 1710),
                ("Patrick Mahomes", 60, 1780),
                ("LIMITED TIME OFFER", 60, 1950),
                ("Shop now", 60, 2040),
            ],
            "expected": {
                "layoutKind": "stacked",
                "sides": [
                    {
                        "label": "Team 1 gets",
                        "assets": [
                            {"text": "Kenneth Walker III", "boardName": "Kenneth Walker III"},
                            {"text": "2027 Late 1st", "boardName": "2027 Late 1st"},
                        ],
                    },
                    {
                        "label": "Team 2 gets",
                        "assets": [
                            {"text": "Josh Hines-Allen", "boardName": "Josh Hines-Allen"},
                            {"text": "Marvin Harrison Jr.", "boardName": "Marvin Harrison Jr."},
                            {"text": "2026 1.05", "boardName": "2026 Pick 1.05"},
                        ],
                    },
                ],
                "mustBeIgnored": ["Bijan Robinson", "Patrick Mahomes"],
                "forbiddenWarnings": ["missing_side", "trade_region_not_detected"],
            },
        },
        # Only ONE side label is visible: its own left-aligned list takes its
        # side; the other column and the widget are NOT given a side.
        "fullpage_single_header": {
            "size": (1400, 760),
            "dark": False,
            "font_size": 24,
            "boxes": [
                (0, 0, 1400, 60, (40, 40, 46)),
                (60, 120, 560, 175, _BAR),
                (1120, 110, 1380, 330, (243, 246, 250)),
            ],
            "texts": [
                ("TradeLab", 20, 18, {"fill": _WHITE}),
                ("You give", 80, 133, {"fill": _WHITE}),
                ("Patrick Mahomes", 80, 220),
                ("2027 1st", 80, 290),
                ("Bijan Robinson", 640, 220),
                ("Insights", 1140, 125, {"size": 18}),
                ("Brian Thomas Jr.", 1140, 170),
                ("Share this trade with your league", 80, 600),
            ],
            "expected": {
                "layoutKind": "single",
                "sides": [
                    {
                        "label": "You give",
                        "assets": [
                            {"text": "Patrick Mahomes", "boardName": "Patrick Mahomes"},
                            {"text": "2027 1st", "boardName": "2027 Round 1"},
                        ],
                    },
                ],
                "unassigned": [
                    {"text": "Bijan Robinson", "boardName": "Bijan Robinson"},
                    {"text": "Brian Thomas Jr.", "boardName": "Brian Thomas Jr."},
                ],
                "mustBeIgnored": [],
                "requiredWarnings": ["missing_side"],
            },
        },
        # No side labels at all: nothing is placed on a side, and the page's
        # unrecognised text is filtered instead of offered as "needs a side".
        "fullpage_no_headers": {
            "size": (1400, 760),
            "dark": False,
            "font_size": 24,
            "boxes": [(0, 0, 230, 760, _NAV)],
            "texts": [
                ("Dashboard", 20, 40, {"fill": _WHITE}),
                ("League Power Rankings", 20, 90, {"fill": _WHITE, "size": 20}),
                ("Weekly Trade Ideas", 300, 40, {"size": 34}),
                ("Patrick Mahomes", 300, 160),
                ("Hot Summer Deals", 700, 220),
                ("$19.99", 700, 270),
                ("Bijan Robinson", 1000, 300),
                ("Exclusive Member Pricing", 420, 420),
                ("Quay Walker", 560, 560),
            ],
            "expected": {
                "layoutKind": "unknown",
                "sides": [],
                "unassigned": [
                    {"text": "Patrick Mahomes", "boardName": "Patrick Mahomes"},
                    {"text": "Bijan Robinson", "boardName": "Bijan Robinson"},
                    {"text": "Quay Walker", "boardName": "Quay Walker"},
                ],
                "mustBeIgnored": ["Hot Summer Deals", "Exclusive Member Pricing"],
                "requiredWarnings": ["trade_region_not_detected", "low_layout_confidence"],
            },
        },
    }
)


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
    for x0, y0, x1, y1, fill in spec.get("boxes", ()):
        draw.rectangle((x0, y0, x1, y1), fill=fill)
    for row in spec["texts"]:
        text, x, y = row[:3]
        opts = row[3] if len(row) > 3 else {}
        font = _font(opts.get("size", spec["font_size"]))
        draw.text((x, y), text, font=font, fill=opts.get("fill", fg))
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
