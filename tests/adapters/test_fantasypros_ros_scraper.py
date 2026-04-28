"""FantasyPros ROS adapter parser test.

Loads a captured fixture HTML snippet (inline below to avoid bundling
binary fixtures) and runs the inline-JSON extractor.  The fixture is
trimmed to two players so the test stays fast and the expected output
is easy to eyeball.
"""
from __future__ import annotations

import unittest

from src.ros.sources.fantasypros_ros_sf import _extract_players


# Minimal fixture — the live HTML page embeds a much larger
# ``ecrData`` blob, but the extractor only cares about two structural
# things: the regex match against ``var ecrData = {...};`` and the
# nested ``players`` array.  Both are present below.
_FIXTURE_HTML = """
<html><body>
<script>
var ecrData = {
  "rankings_type": "DSF",
  "players": [
    {
      "rank_ecr": 1,
      "player_name": "Josh Allen",
      "player_short_name": "J. Allen",
      "player_position_id": "QB",
      "player_team_id": "BUF"
    },
    {
      "rank_ecr": 2,
      "player_name": "Lamar Jackson",
      "player_short_name": "L. Jackson",
      "player_position_id": "QB",
      "player_team_id": "BAL"
    }
  ]
};
var sportLink = "/nfl/";
</script>
</body></html>
"""


class TestFantasyProsRosExtract(unittest.TestCase):
    def test_extracts_players_from_ecr_blob(self):
        rows = _extract_players(_FIXTURE_HTML)
        self.assertEqual(len(rows), 2)
        names = [r.get("player_name") for r in rows]
        self.assertEqual(names, ["Josh Allen", "Lamar Jackson"])

    def test_returns_empty_when_blob_missing(self):
        rows = _extract_players("<html>no ecrData here</html>")
        self.assertEqual(rows, [])

    def test_returns_empty_when_blob_malformed(self):
        bad = """<script>var ecrData = { not valid json }; var x;</script>"""
        rows = _extract_players(bad)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
