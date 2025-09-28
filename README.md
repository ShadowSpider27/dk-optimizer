# dk-optimizer
This is a web project to create dk lineups for various sports and display tournament stats 

This project, currently shows league of legends standings for the current season/split for various leagues, it allows population of a match set using a csv, and selection of players with team selects on match cards and includes and excludes, it optimizes lineups using the best captain candidate and resultant choices. It allows for classic mode with the rules(one of each role + captain + team, no more than 4 players from one team, at least 2 matches, and a salary cap) and showdown mode(2 captains from different teams, and 2 flex players from different teams), lineups displayed currently use metrics from avg points per set as the main metric to determine best lineups. 
To use: download the required files(static folder, templates folder, app.py), run using python with required imports, populate a valid csv from dk for a match set, choose players to include or exclude and generate lineups
Additions: More standings data, adjustable points, smart optimize(using some predictions of the given match set to determine given no choices)
