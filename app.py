from flask import Flask, render_template, jsonify, request
import requests
from bs4 import BeautifulSoup
from math import inf

app = Flask(__name__)

#active split standings links
URLS = {
    "lpl": "https://lol.fandom.com/wiki/LPL/2025_Season/Split_3",
    "lck": "https://lol.fandom.com/wiki/LCK/2025_Season/Rounds_3-5",
    "lta": "https://lol.fandom.com/wiki/LTA_North/2025_Season/Split_3",
    "lec": "https://lol.fandom.com/wiki/LEC/2025_Season/Summer_Season"
}

# function to scrape standings
def scrape_standings(url):

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")
    # standings table found by class 
    tables = soup.select("table.wikitable2.standings")
    results = []

    for table in tables:
        rows = table.find_all("tr")

        if not rows:
            continue
        # get group name 
        first_tr = rows[0]
        group_name = " ".join(first_tr.get_text(" ", strip=True).split()[:2])
        #print(group_name)
        # create headers we only care about
        headers = ["Rank", "Team", "Series"]
        # find team data rows
        keys = ["rank", "team", "series"]
        team_rows = []
        for r in rows[2:]:
            #filter data
            cols = [td.get_text(" ", strip=True) for td in r.find_all("td")]
            cols = [td.get_text(" ", strip=True).replace("\u2060", "") for td in r.find_all("td")]
            if not cols:
                continue
            joined = " ".join(cols).lower()
            # remove legend data 
            if any(word in joined for word in ["seed", "qualified", "playoffs", "bracket", "play-in"]):
                continue
            row_dict = {k: cols[i] if i < len(cols) else "" for i, k in enumerate(keys)}
            #print(row_dict)
            team_rows.append(row_dict)
            #print(team_rows)
        if team_rows:
            results.append({
                "group": group_name,
                "headers": headers,
                "standings": team_rows
            })
        #print(results)
    return results
#route for getting csv from dk 
@app.route("/fetch_csv")
def fetch_csv():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        r = requests.get(url)
        r.raise_for_status()
        return r.text  
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# home route
@app.route("/")
def index():
    return render_template("home.html")

#standings route 
@app.route("/standings/<league>")
def standings(league):
    url = URLS.get(league)
    if not url:
        return jsonify({"error": "Invalid league"}), 400
    return jsonify(scrape_standings(url))

#optimize/create lineups route
@app.route("/optimize", methods=["POST"])
def optimize():
    data = request.get_json(force=True)
    game = data.get("game","")
    mode = data.get("mode","")
    raw_players = data.get("players", [])

    # normalize helper
    def normalize(s):
        return (s or "").strip()

    # normalize input sets
    included_names = {normalize(n) for n in (data.get("included", []) or [])}
    excluded_names = {normalize(n) for n in (data.get("excluded", []) or [])}

    players = []
    for p in raw_players:
        try:
            name = normalize(p.get("Name", ""))
            roster_pos = normalize(p.get("RosterPosition"))
            pos = normalize(p.get("Position"))
            team = normalize(p.get("TeamAbbrev"))
            salary = int(p.get("Salary"))
            avgpts = float(p.get("AvgPointsPerGame") or p.get("AvgPointsPerGame\r") or 0.0)
        except Exception:
            continue

        if not name or not team or not pos:
            continue

        combo = f"{name}|{roster_pos}"

        # exclusion always wins
        if combo in excluded_names or name in excluded_names:
            continue

        players.append({
            "Name": name,
            "RosterPosition": roster_pos,
            "Position": pos,
            "Team": team,
            "Salary": salary,
            "AvgPts": avgpts
        })

    if not players:
        return jsonify({"lineups": []})

    # hard filter on included players
    if included_names:
        players = [
            p for p in players
            if (p["Name"] in included_names or f"{p['Name']}|{p['RosterPosition']}" in included_names)
        ]

    # apply exclusion again in case someone is both included + excluded
    players = [
        p for p in players
        if not (
            p["Name"] in excluded_names or f"{p['Name']}|{p['RosterPosition']}" in excluded_names
        )
    ]

    if not players:
        return jsonify({"lineups": []})

    # classic rules
    if game =="lol" and mode=="classic":
        PLAYER_ROLES = ["TOP", "JNG", "MID", "ADC", "SUP"]
        REQUIRED_ROLES = PLAYER_ROLES + ["TEAM"]  
        SALARY_CAP = 50000
        MAX_PLAYERS_PER_TEAM = 4 
        slots = ["CPT", "TOP", "JNG", "MID", "ADC", "SUP", "TEAM"]
    elif game =="lol" and mode =="showdown":
        PLAYER_ROLES = ["CPT", "FLEX"]
        REQUIRED_ROLES = PLAYER_ROLES
        SALARY_CAP = 50000
        MAX_PLAYERS_PER_TEAM = 2
        slots = ["CPT", "CPT", "FLEX", "FLEX"]
    else:
        return jsonify({"error": "Unsupported game/mode"}), 400



    # organize players by role
    by_role = {r: [] for r in REQUIRED_ROLES}
    capt_candidates = []  
    for p in players:
        rpos = p["RosterPosition"]
        if rpos == "CPT":
            capt_candidates.append(p)
        elif rpos in by_role:
            by_role[rpos].append(p)

    # sorting algorithm
    def sort_key(p):
        eff = (p["AvgPts"] / p["Salary"]) if p["Salary"] else 0
        return (p["AvgPts"], eff)

    for r in by_role:
        by_role[r].sort(key=sort_key, reverse=True)
    capt_candidates.sort(key=sort_key, reverse=True)

    lineups = []
    seen_signatures = set()

    def backtrack(slot_idx, lineup, used_names, team_player_counts, total_salary):
        if len(lineups) >= 3:
            return
        if slot_idx == len(slots):
            # showdown-specific validation
            if game == "lol" and mode == "showdown":
                teams_in_cpt = {e["Team"] for e in lineup if e["Pos"] == "CPT"}
                teams_in_flex = {e["Team"] for e in lineup if e["Pos"] == "FLEX"}
                if teams_in_cpt != teams_in_flex:
                    return
            # classic-specific validation
            if game == "lol" and mode == "classic":
                # must span at least 2 different games (in practice, different "Team" values here)
                if len({e["Team"] for e in lineup}) < 2:
                    return

            sig = tuple(sorted((f'{e["Pos"]}:{e["Player"]}' for e in lineup)))
            if sig in seen_signatures:
                return
            seen_signatures.add(sig)
            lineups.append(list(lineup))
            return


        slot = slots[slot_idx]
        candidates = capt_candidates if slot == "CPT" else by_role.get(slot, [])

        for c in candidates:
            name = c["Name"]
            team = c["Team"]
            base_salary = c["Salary"]
            base_pts = c["AvgPts"]

            if name in used_names:
                continue
            
            # showdown-specific: prevent duplicate CPTs from same team
            if game == "lol" and mode == "showdown" and slot == "CPT":
                if any(e["Pos"] == "CPT" and e["Team"] == team for e in lineup):
                    continue

            if slot == "CPT":
                sal = base_salary
                pts = base_pts * 1.5
            else:
                sal = base_salary
                pts = base_pts

            if total_salary + sal > SALARY_CAP:
                continue
            if team_player_counts.get(team, 0) >= MAX_PLAYERS_PER_TEAM:
                continue

            new_team_counts = dict(team_player_counts)
            new_team_counts[team] = new_team_counts.get(team, 0) + 1

            entry = {
                "Pos": slot,
                "Player": name,
                "Team": team,
                "Salary": sal,
                "AvgPts": pts
            }

            lineup.append(entry)
            used_names.add(name)

            backtrack(
                slot_idx + 1,
                lineup,
                used_names,
                new_team_counts,
                total_salary + sal
            )
            lineup.pop()
            used_names.remove(name)
            if len(lineups) >= 3:
                return
            
    backtrack(
        slot_idx=0,
        lineup=[],
        used_names=set(),
        team_player_counts={},
        total_salary=0
    )
    return jsonify({"lineups": lineups})

if __name__ == "__main__":
    app.run(debug=True)
