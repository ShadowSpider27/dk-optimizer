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
        #get group name 
        first_tr = rows[0]
        group_name = " ".join(first_tr.get_text(" ", strip=True).split()[:2])
        #print(group_name)
        # create headers only the ones we care about
        headers = ["Rank", "Team", "Series"]
        # find team data rows
        keys = ["rank", "team", "series"]
        team_rows = []
        for r in rows[2:]:
            cols = [td.get_text(" ", strip=True) for td in r.find_all("td")]
            #print(cols)
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

#optimize/create lineups
@app.route("/optimize", methods=["POST"])
def optimize():
    data = request.get_json(force=True)
    raw_players = data.get("players", [])
    included_names = {n.strip() for n in (data.get("included", []) or [])}
    excluded_names = {n.strip() for n in (data.get("excluded", []) or [])}
    # get players
    players = []
    for p in raw_players:
        try:
            name = p.get("Name", "").strip()
            pos = (p.get("Position") or "").strip().upper()
            team = (p.get("TeamAbbrev") or "").strip().upper()
            salary = int(p.get("Salary"))
            avgpts = float(p.get("AvgPointsPerGame") or p.get("AvgPointsPerGame\r") or 0.0)
        except Exception:
            continue
        if not name or not team or not pos:
            continue
        if name in excluded_names:
            continue
        #print(excluded_names)
        players.append({
            "Name": name,
            "Position": pos,
            "Team": team,
            "Salary": salary,
            "AvgPts": avgpts
        })
        #print(players)

    if not players:
        return jsonify({"lineups": []})

    # classic rules
    PLAYER_ROLES = ["TOP", "JNG", "MID", "ADC", "SUP"]
    REQUIRED_ROLES = PLAYER_ROLES + ["TEAM"]  
    SALARY_CAP = 50000
    MAX_PLAYERS_PER_TEAM = 4  

    # roles
    by_role = {r: [] for r in REQUIRED_ROLES}
    capt_candidates = []  
    for p in players:
        r = p["Position"]
        if r in by_role:
            by_role[r].append(p)
        if r in PLAYER_ROLES:
            capt_candidates.append(p)
    # sorting algo
    def sort_key(p):
        eff = (p["AvgPts"] / p["Salary"]) if p["Salary"] else 0
        return (p["AvgPts"], eff)

    for r in by_role:
        by_role[r].sort(key=sort_key, reverse=True)
    capt_candidates.sort(key=sort_key, reverse=True)

    # prio included players
    def prioritize_included(lst):
        return sorted(lst, key=lambda x: (x["Name"] not in included_names,
                                          -x["AvgPts"],
                                          -(x["AvgPts"] / x["Salary"] if x["Salary"] else 0)))
    for r in by_role:
        by_role[r] = prioritize_included(by_role[r])
    capt_candidates = prioritize_included(capt_candidates)

    lineups = []
    seen_signatures = set()

    #backtracking search
    slots = ["CPT", "TOP", "JNG", "MID", "ADC", "SUP", "TEAM"]

    def backtrack(slot_idx, lineup, used_names, team_player_counts, total_salary, included_remaining):
        # generated 3 lineups
        if len(lineups) >= 3:
            return
        if slot_idx == len(slots):           
            if included_remaining:
                return
            
            sig = tuple(sorted((f'{e["Pos"]}:{e["Player"]}' for e in lineup)))
            if sig in seen_signatures:
                return
            seen_signatures.add(sig)
            lineups.append(list(lineup))
            return

        slot = slots[slot_idx]

        
        if slot == "CPT":
            candidates = capt_candidates
        else:
            candidates = by_role.get(slot, [])
        
        candidates = prioritize_included(candidates)

        for c in candidates:
            name = c["Name"]
            team = c["Team"]
            base_salary = c["Salary"]
            base_pts = c["AvgPts"]

            if name in used_names:
                continue

            # salary + team limit checks
            if slot == "CPT":
                sal = int(round(base_salary * 1.5))
                pts = base_pts * 1.5
                if total_salary + sal > SALARY_CAP:
                    continue
                if team_player_counts.get(team, 0) >= MAX_PLAYERS_PER_TEAM:
                    continue
                new_team_counts = dict(team_player_counts)
                new_team_counts[team] = new_team_counts.get(team, 0) + 1
            elif slot == "TEAM":
                sal = base_salary
                pts = base_pts
                if total_salary + sal > SALARY_CAP:
                    continue
                if team_player_counts.get(team, 0) >= MAX_PLAYERS_PER_TEAM:
                    continue
                new_team_counts = team_player_counts
                new_team_counts[team] = new_team_counts.get(team, 0) + 1
            else:
                sal = base_salary
                pts = base_pts
                # player slot -> counts
                if total_salary + sal > SALARY_CAP:
                    continue
                if team_player_counts.get(team, 0) >= MAX_PLAYERS_PER_TEAM:
                    continue
                new_team_counts = dict(team_player_counts)
                new_team_counts[team] = new_team_counts.get(team, 0) + 1

            entry = {
                "Pos": slot if slot != "CPT" else "CPT",
                "Player": name,
                "Team": team,
                "Salary": sal,
                "AvgPts": pts
            }

            #  included tracking
            new_included_remaining = set(included_remaining)
            if name in new_included_remaining:
                new_included_remaining.remove(name)

            lineup.append(entry)
            used_names.add(name)

            backtrack(
                slot_idx + 1,
                lineup,
                used_names,
                new_team_counts,
                total_salary + sal,
                new_included_remaining
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
        total_salary=0,
        included_remaining=set(n for n in included_names if n not in excluded_names)
    )

    return jsonify({"lineups": lineups})



if __name__ == "__main__":
    app.run(debug=True)
