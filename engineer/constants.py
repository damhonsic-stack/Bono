"""Číselníky F1 25 (anglické názvy jako ve hře) a přibližné referenční časy tratí."""

TRACKS = {
    0: 'Melbourne', 2: 'Shanghai', 3: 'Bahrain', 4: 'Barcelona', 5: 'Monaco',
    6: 'Montreal', 7: 'Silverstone', 9: 'Hungaroring', 10: 'Spa-Francorchamps', 11: 'Monza',
    12: 'Singapore', 13: 'Suzuka', 14: 'Abu Dhabi', 15: 'Austin (COTA)', 16: 'Interlagos',
    17: 'Austria', 19: 'Mexico City', 20: 'Baku', 26: 'Zandvoort', 27: 'Imola',
    29: 'Jeddah', 30: 'Miami', 31: 'Las Vegas', 32: 'Qatar',
    39: 'Silverstone (Reverse)', 40: 'Austria (Reverse)', 41: 'Zandvoort (Reverse)',
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
    0: 'Unknown', 1: 'Practice 1', 2: 'Practice 2', 3: 'Practice 3', 4: 'Short Practice',
    5: 'Q1', 6: 'Q2', 7: 'Q3', 8: 'Short Qualifying', 9: 'One-Shot Qualifying',
    10: 'Sprint Shootout 1', 11: 'Sprint Shootout 2', 12: 'Sprint Shootout 3',
    13: 'Short Sprint Shootout', 14: 'One-Shot Sprint Shootout',
    15: 'Race', 16: 'Race 2', 17: 'Race 3', 18: 'Time Trial',
}
PRACTICE = {1, 2, 3, 4}
QUALI = {5, 6, 7, 8, 9, 10, 11, 12, 13, 14}
RACE = {15, 16, 17}
TIME_TRIAL = 18

WEATHER = {0: 'Clear', 1: 'Light Cloud', 2: 'Overcast', 3: 'Light Rain',
           4: 'Heavy Rain', 5: 'Storm'}

VISUAL_COMPOUND = {16: 'Soft', 17: 'Medium', 18: 'Hard', 7: 'Intermediate', 8: 'Wet'}
ACTUAL_COMPOUND = {16: 'C5', 17: 'C4', 18: 'C3', 19: 'C2', 20: 'C1', 21: 'C0',
                   22: 'C6', 7: 'Intermediate', 8: 'Wet'}

# Kolik % času na kolo přibližně odpovídá 1 bodu obtížnosti AI.
# Komunitní zkušenost: ~10 bodů ≈ 1–1,5 s na kole kolem 1:30.
AI_PCT_PER_POINT = 0.0012

WHEELS = ['RL', 'RR', 'FL', 'FR']
