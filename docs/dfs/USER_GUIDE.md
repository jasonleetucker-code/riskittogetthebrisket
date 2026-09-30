# DFS Workspace — user guide (current slice)

Open **DFS → DFS Workspace** (`/dfs`). Sign-in required.

1. **Pick sport and platform.** The badge says what is possible: *Research only — rules
   unverified* (you can build; the rule set has not been checked against the official page) or
   *Not available yet* (no rules encoded — nothing can be built). Today only NFL Classic on
   DraftKings and FanDuel can build.
2. **Import the slate.** Download the platform's salary / player-list CSV for your contest and
   choose it (or paste it). Add your projection CSV: columns `ID` (platform player ID) or
   `Name` + `Team` (+ optional `Position`), and `Projection`. Rows that match two players, match
   nobody, or disagree with each other are listed and **not** applied. Optionally tick *use the
   platform season average* for players you have no projection for — it is labelled "avg" and is
   not a forecast. Players with no projection are never counted as 0; they are left out.
3. **Set rules.** Lock / Exclude per player; lineups, minimum unique players, max exposure % (the
   count shown is rounded down), minimum salary, max players per team, and an optional QB stack
   with bring-back.
4. **Build.** *Optimal Lineup* builds one lineup; *Build Portfolio* builds the number you set.
   Both maximize **projected points** — not contest EV. *optimal* means no higher projected
   total exists under your rules. If your rules conflict, you get the conflicting set; nothing
   is relaxed.
5. **Export.** *Download upload CSV* writes platform IDs in slot order. The upload format has not
   been verified against an official template yet — check it before uploading. Downloading
   submits nothing.
