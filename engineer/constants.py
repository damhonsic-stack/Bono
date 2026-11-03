"""Číselníky F1 25 a přibližné referenční časy tratí."""

TRACKS = {
    0: 'Melbourne', 2: 'Shanghai', 3: 'Bahrajn', 4: 'Barcelona', 5: 'Monako',
    6: 'Montreal', 7: 'Silverstone', 9: 'Hungaroring', 10: 'Spa', 11: 'Monza',
    12: 'Singapur', 13: 'Suzuka', 14: 'Abu Dhabi', 15: 'Austin', 16: 'Interlagos',
    17: 'Rakousko', 19: 'Mexiko', 20: 'Baku', 26: 'Zandvoort', 27: 'Imola',
    29: 'Džidda', 30: 'Miami', 31: 'Las Vegas', 32: 'Katar',
    39: 'Silverstone (obráceně)', 40: 'Rakousko (obráceně)', 41: 'Zandvoort (obráceně)',
}

# Přibližný čas na pole position ≈ výchozí odhad pro AI 100 (sekundy).
# Jde jen o startovní odhad – aplikace se kalibruje podle skutečných časů AI,
# které uvidí v tvých kvalifikacích a trénincích.
POLE_BASELINE = {
    0: 75.1, 2: 90.6, 3: 89.8, 4: 71.5, 5: 70.0, 6: 70.9, 7: 84.9, 9: 75.4,
    10: 100.6, 11: 78.8, 12: 89.2, 13: 87.0, 14: 82.2, 15: 92.5, 16: 69.5,
    17: 64.0, 19: 75.6, 20: 101.1, 26: 68.7, 27: 74.7, 29: 87.3, 30: 86.2,
    31: 92.3, 32: 79.4,
}

SESSION_TYPES = {
    0: 'Neznámá', 1: 'Trénink 1', 2: 'Trénink 2', 3: 'Trénink 3', 4: 'Krátký trénink',
    5: 'Q1', 6: 'Q2', 7: 'Q3', 8: 'Krátká kvalifikace', 9: 'Kvalifikace na 1 kolo',
    10: 'Sprint shootout 1', 11: 'Sprint shootout 2', 12: 'Sprint shootout 3',
    13: 'Krátký sprint shootout', 14: 'Sprint shootout na 1 kolo',
    15: 'Závod', 16: 'Závod 2', 17: 'Závod 3', 18: 'Time Trial',
}
PRACTICE = {1, 2, 3, 4}
QUALI = {5, 6, 7, 8, 9, 10, 11, 12, 13, 14}
RACE = {15, 16, 17}
TIME_TRIAL = 18

WEATHER = {0: 'Jasno', 1: 'Polojasno', 2: 'Zataženo', 3: 'Slabý déšť',
           4: 'Silný déšť', 5: 'Bouřka'}

VISUAL_COMPOUND = {16: 'Soft', 17: 'Medium', 18: 'Hard', 7: 'Inter', 8: 'Wet'}
ACTUAL_COMPOUND = {16: 'C5', 17: 'C4', 18: 'C3', 19: 'C2', 20: 'C1', 21: 'C0',
                   22: 'C6', 7: 'Inter', 8: 'Wet'}

# Kolik % času na kolo přibližně odpovídá 1 bodu obtížnosti AI.
# Komunitní zkušenost: ~10 bodů ≈ 1–1,5 s na kole kolem 1:30.
AI_PCT_PER_POINT = 0.0012

WHEELS = ['RL', 'RR', 'FL', 'FR']
