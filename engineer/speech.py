"""Převod textu hlášení na přirozenou mluvenou řeč (hlavně čeština).

Na obrazovce zůstává technický zápis („0:58.806“, „+0,47 s“, „T4“, „gap ahead“), ale český
hlas by ho četl divně. Tady se z něj stane věta, jak by ji řekl inženýr v rádiu:
  „Lap 0:58.806. Delta +0,47 s na referenci.“ → „Kolo padesát osm celá osm. O pět desetin pomaleji.“
"""
import re

# anglické F1 pojmy → jak je přirozeně řekne český inženýr (delší fráze první)
CS_TERMS = [
    ('Front left wing', 'Levá strana předního křídla'), ('Front right wing', 'Pravá strana předního křídla'),
    ('Rear wing', 'Zadní křídlo'), ('Front wing', 'Přední křídlo'),
    ('Drž delta kladnou', 'Drž deltu kladnou'), ('v lapu', 'v kole'), ('šetři deploy', 'šetři baterii'),
    ('Box this lap, box box', 'Box, box. Tohle kolo jdeš do boxu'),
    ('box box', 'box, box'), ('Box next lap', 'Příští kolo do boxu'),
    ('Radio check', 'Zkouška spojení'), ('Loud and clear', 'Slyším tě dobře'),
    ('Personal best', 'Osobní rekord'), ('Session best', 'Nejlepší kolo'),
    ('Theoretical best', 'Ideální kolo'),
    ('overtake mode enabled', 'overtejk mód zapnutý'), ('overtake mode disabled', 'overtejk mód vypnutý'),
    ('Gap ahead', 'Odstup dopředu'), ('gap ahead', 'odstup dopředu'),
    ('Gap behind', 'Odstup za tebou'), ('gap behind', 'odstup za tebou'),
    ('Fuel delta', 'Rezerva paliva'), ('fuel delta', 'rezerva paliva'),
    ('Tyre wear', 'Opotřebení gum'), ('tyre wear', 'opotřebení gum'), ('tyre age', 'stáří gum'),
    ('braking point', 'brzdný bod'), ('minimum speed', 'minimální rychlost'),
    ('exit speed', 'výjezdová rychlost'), ('full throttle', 'plný plyn'),
    ('v apexu', 've vrcholu zatáčky'), ('apex', 'vrchol'),
    ('reference gear', 'reference má převod'), ('gear', 'převod'),
    ('lift and coast', 'lift and coast'),
    ('Overtake mode', 'Overtejk mód'), ('overtake mode', 'overtejk mód'),
    ('Straight mode', 'Strejt mód'), ('straight mode', 'strejt mód'),
    ('Safety car', 'Sejfty kár'), ('safety car', 'sejfty kár'),
    ('Virtual safety car', 'Virtuální sejfty kár'),
    ('Race control', 'Řízení závodu'), ('Track limits warning', 'Varování za limity trati'),
    ('track limits', 'limity trati'), ('Blue flag', 'Modrá vlajka'), ('Yellow flag', 'Žlutá vlajka'),
    ('Red flag, red flag', 'Červená vlajka'), ('Green flag, green flag', 'Zelená vlajka'),
    ('undercut', 'andrkat'), ('overcut', 'ouvrkat'), ('Undercut', 'Andrkat'),
    ('Defend', 'Braň se'), ('Push now, push push', 'Teď naplno, push, push'),
    ('Watch it', 'Pozor'), ('Out lap', 'Zahřívací kolo'), ('Tyre temps', 'Teploty gum'),
    ('Battery', 'Baterie'), ('battery', 'baterie'), ('harvest', 'nabíjení'), ('Harvest', 'Nabíjej'),
    ('deploy mode', 'režim baterie'), ('Plan is', 'Plán je'),
    ('Pit window', 'Okno pro zastávku'), ('pit stop', 'zastávka'),
    ('front left', 'přední levá'), ('front right', 'přední pravá'),
    ('rear left', 'zadní levá'), ('rear right', 'zadní pravá'),
    ('damage', 'poškození'),
    ('Intermediate', 'přechodové'), ('Wet', 'mokré'), ('Lap invalid', 'Kolo neplatné'),
    ('tyres', 'gumy'), ('Tyres', 'Gumy'), ('gap', 'odstup'), ('Race', 'Závod'),
    ('laps', 'kol'), ('lapů', 'kol'), ('za lap', 'za kolo'), ('lapu', 'kola'), ('lap', 'kolo'),
    ('Lap', 'Kolo'), ('Delta', 'Rozdíl'), ('pace', 'tempo'), ('target', 'cíl'),
    ('AI difficulty', 'obtížnost AI'), ('session', 'session'),
]

_N = {5: 'pět', 6: 'šest', 7: 'sedm', 8: 'osm', 9: 'devět'}
DESETIN = {1: 'jednu desetinu', 2: 'dvě desetiny', 3: 'tři desetiny', 4: 'čtyři desetiny'}
DESETIN.update({k: v + ' desetin' for k, v in _N.items()})
SETIN = {1: 'jednu setinu', 2: 'dvě setiny', 3: 'tři setiny', 4: 'čtyři setiny'}
SETIN.update({k: v + ' setin' for k, v in _N.items()})


def cs_seconds(secs):
    """0.47 → 'pět desetin', 0.04 → 'čtyři setiny', 1.2 → 'jedna celá dvě sekundy'."""
    secs = abs(secs)
    if secs < 0.095:
        n = max(1, round(secs * 100))
        return SETIN.get(n, '%d setin' % n)
    if secs < 0.95:
        n = round(secs * 10)
        return DESETIN.get(n, '%d desetin' % n)
    if secs < 10:
        txt = ('%.1f' % secs).replace('.', ',')
        if txt.endswith(',0'):
            n = int(txt[:-2])
            return {1: 'jedna sekunda', 2: 'dvě sekundy', 3: 'tři sekundy',
                    4: 'čtyři sekundy'}.get(n, '%d sekund' % n)
        return txt + ' sekundy'
    return '%d sekund' % round(secs)


def cs_laptime(m, s, ms):
    tenth = int(ms) // 100
    sec = '%d,%d' % (int(s), tenth)
    if int(m) == 0:
        return sec
    return '%s minuta %s' % (m, sec) if int(m) == 1 else '%s minuty %s' % (m, sec)


def to_speech(text, lang='cs'):
    if not text:
        return text
    t = re.sub(r'\s*\((Gemini|offline)[^)]*\)', '', text)
    t = re.sub(r'[\U0001F300-\U0001FAFF☀-➿]', '', t)
    if lang != 'cs':
        t = re.sub(r'\b(\d+):(\d{2})\.(\d)\d{2}\b',
                   lambda m: ('%s %s.%s' % (m.group(1), m.group(2), m.group(3)))
                   if m.group(1) != '0' else '%s.%s' % (m.group(2), m.group(3)), t)
        t = re.sub(r'\bT(\d+)\b', r'turn \1', t)
        t = re.sub(r'\bP(\d+)\b', r'P \1', t)
        return t.strip()
    # časy kola 1:21.345 / 0:58.806
    t = re.sub(r'\b(\d+):(\d{2})[.,](\d{3})\b', lambda m: cs_laptime(*m.groups()), t)
    # rozdíly „+0,47 s“ / „-0,12 s“ / „0,47 s“ (případně bez „s“ ve spojení „za kolo“)
    t = re.sub(r'Plus ([\d,]+) s na referenci', lambda m: 'O %s pomaleji než reference' %
               cs_seconds(float(m.group(1).replace(',', '.'))), t)
    t = re.sub(r'Delta \+([\d,]+) s na referenci', lambda m: 'O %s pomaleji než reference' %
               cs_seconds(float(m.group(1).replace(',', '.'))), t)
    t = re.sub(r'Delta -([\d,]+) s, rychlejší než reference!', lambda m: 'O %s rychleji než reference!' %
               cs_seconds(float(m.group(1).replace(',', '.'))), t)
    t = re.sub(r'([+-]?)(\d+,\d+) ?s\b', lambda m: ('plus ' if m.group(1) == '+' else
               'mínus ' if m.group(1) == '-' else '') + cs_seconds(float(m.group(2).replace(',', '.'))), t)
    t = re.sub(r'([+-])(\d+,\d+)\b', lambda m: ('plus ' if m.group(1) == '+' else 'mínus ') +
               m.group(2), t)
    # zatáčky a pozice
    t = re.sub(r'\b([Vv]) T(\d+)\b', lambda m: '%s zatáčce %s' % (m.group(1), m.group(2)), t)
    t = re.sub(r'\bT(\d+)\b', r'zatáčka \1', t)
    t = re.sub(r'\b([Nn]a) P(\d+)\b', r'\1 pozici \2', t)
    t = re.sub(r'\bP(\d+)\b', r'pozice \1', t)
    t = re.sub(r'\bAI difficulty (\d+)\b', r'obtížnost \1', t)
    t = re.sub(r'\bAI (\d+)\b', r'obtížnost \1', t)
    # jednotky
    t = re.sub(r'(\d) ?%', r'\1 procent', t)
    t = t.replace('km/h', 'kilometrů za hodinu')
    t = re.sub(r'(\d) m\b', r'\1 metrů', t)
    t = re.sub(r'\bMJ\b', 'megajoulů', t)
    t = t.replace('°C', ' stupňů').replace('°', ' stupňů')
    for en, cs in CS_TERMS:
        def rep(m, cs=cs):
            w = m.group(0)
            return cs[0].upper() + cs[1:] if w[0].isupper() else cs[0].lower() + cs[1:]
        t = re.sub(r'(?<![\w])' + re.escape(en) + r'(?![\w])', rep, t, flags=re.I)
    # skloňování „N kol“
    def kol(m):
        n = m.group(1)
        if ',' in n:
            return n + ' kola'
        k = int(n)
        return n + (' kolo' if k == 1 else ' kola' if 2 <= k <= 4 else ' kol')
    t = re.sub(r'(\d+(?:,\d+)?) kol\b', kol, t)
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip()
