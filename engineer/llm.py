"""Odpovědi na otázky jezdce: Gemini (volitelně) nebo offline pravidla."""
import json
import ssl
import urllib.request
import urllib.error

from . import radio as R

SYSTEM_PROMPT = {
    'cs': """Jsi závodní inženýr F1 týmu a mluvíš se svým jezdcem přes týmové rádio během hry F1 25.
PRAVIDLA:
- Odpovídej česky, maximálně 2–3 krátké věty, jako v rádiu. Žádné odrážky, žádný markdown.
- Technické F1 pojmy VŽDY anglicky, zbytek věty česky. Např.: lap, lap time, sector, delta, gap ahead,
  gap behind, pace, apex, braking point, exit, minimum speed, full throttle, gear, tyre wear, tyre temps,
  Soft/Medium/Hard/Intermediate/Wet, fuel, fuel delta, lift and coast, box, pit stop, undercut, overcut,
  DRS, ERS, straight mode, overtake mode, personal best, session best, target, AI difficulty.
  Příklad: "V T4 ztrácíš dvě desetiny, braking point máš o 12 metrů dřív."
- Zatáčky označuj T1, T2, T3 … (Turn), nikdy česky.
- Používej VÝHRADNĚ čísla z JSON dat níže. Nic si nevymýšlej. Když údaj chybí, řekni to.
- Časy říkej v sekundách s jedním až dvěma desetinnými místy (např. "ztrácíš dvě desetiny").
- loss / avg_loss_ms jsou milisekundy ztráty v úseku zatáčky oproti referenci (kladné = ztráta).
- brake_diff_m záporné = braking point dřív než reference; throttle_diff_m kladné = full throttle později.
- ahead_trend záporné = jezdec stahuje auto před sebou; behind_trend záporné = auto za ním ho dojíždí.
- fuel game_delta_laps (z MFD ve hře) / own_delta_laps: kladné = rezerva v lapech, záporné = nutný lift and coast.
- tyre wear jsou procenta (RL, RR, FL, FR = rear left, rear right, front left, front right).
- target.lap_ms je target lap time pro danou AI difficulty (odhad), match_ai = AI difficulty odpovídající pace jezdce.
- Dávej konkrétní, akční rady (braking point, minimum speed v apexu, exit), ne obecné fráze.
- Turns jsou číslované automaticky (T1, T2 …) podle pořadí na trati, ne podle oficiálního číslování.""",
    'en': """You are an F1 race engineer talking to your driver over team radio during the game F1 25.
RULES:
- Answer in English, max 2-3 short radio-style sentences. No bullet points, no markdown.
- Use ONLY numbers from the JSON data below. Never invent data. If something is missing, say so.
- loss / avg_loss_ms = milliseconds lost in that corner section vs reference (positive = loss).
- brake_diff_m negative = braking earlier than reference; throttle_diff_m positive = later to full throttle.
- ahead_trend negative = driver closing on car ahead; behind_trend negative = car behind is closing.
- fuel own_delta_laps / game_delta_laps: positive = fuel margin in laps, negative = must save fuel.
- tyre wear is percent (RL, RR, FL, FR).
- target.lap_ms is the estimated target lap for the AI difficulty; match_ai = difficulty matching driver pace.
- Give concrete, actionable advice.
- Corners are auto-numbered T1, T2 ... in track order, not official turn numbers.""",
}


def ask_gemini(api_key, model, lang, question, context, timeout=20):
    url = ('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model)
    body = {
        'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT.get(lang, SYSTEM_PROMPT['cs'])}]},
        'contents': [{
            'role': 'user',
            'parts': [{'text': 'DATA (JSON):\n' + json.dumps(context, ensure_ascii=False) +
                       '\n\nOTÁZKA JEZDCE: ' + question}],
        }],
        'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 300,
                             'thinkingConfig': {'thinkingBudget': 0}},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json',
                                          'x-goog-api-key': api_key})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    parts = data.get('candidates', [{}])[0].get('content', {}).get('parts', [])
    text = ''.join(p.get('text', '') for p in parts).strip()
    return text or None


# ---------------------------------------------------------------- offline pravidla
KEYWORDS = [
    ('tyres', ['gum', 'pneu', 'tyre', 'tire', 'opotřeb', 'opotreb', 'wear', 'soft', 'medium', 'hard']),
    ('fuel', ['paliv', 'benz', 'fuel', 'nádrž', 'nadrz']),
    ('gap', ['mezer', 'gap', 'před', 'pred', 'za mnou', 'dojíž', 'dojiz', 'stahu', 'behind', 'ahead']),
    ('corners', ['zatáč', 'zatac', 'ztrác', 'ztrac', 'corner', 'turn', 'apex', 'losing', 'kde']),
    ('target', ['obtížn', 'obtizn', 'ai ', 'cíl', 'cil', 'target', 'difficulty']),
    ('pace', ['tempo', 'pace', 'čas', 'cas', 'kolo', 'lap']),
]


def classify(question):
    q = question.lower() + ' '
    for intent, words in KEYWORDS:
        if any(w in q for w in words):
            return intent
    return 'pace'


def answer_offline(engine, question):
    lang = engine.lang
    snap = engine.snapshot()
    intent = classify(question)
    race = snap.get('race') or {}
    cs = lang == 'cs'
    if intent == 'tyres':
        t = race.get('tyres')
        if not t or 'wear' not in t:
            return R.say(lang, 'no_data')
        w = t['wear']
        wheel = max(w, key=w.get)
        msg = R.say(lang, 'tyre_wear', w=round(t['max_wear']), wheel=R.WHEEL_NAMES[lang][wheel])
        msg += (' %s, tyre age %d laps.' if cs else ' %s, %d laps old.') % (t['compound'], t['age'])
        if t.get('wear_per_lap'):
            wpl, l70 = '%.1f' % t['wear_per_lap'], '%s' % t['laps_to_70']
            if cs:
                msg += ' Wear %s %% za lap, 70 %% za %s laps.' % (
                    wpl.replace('.', ','), l70.replace('.', ','))
            else:
                msg += ' %s%% per lap, 70%% in %s laps.' % (wpl, l70)
        return msg
    if intent == 'fuel':
        f = race.get('fuel')
        if not f:
            return R.say(lang, 'no_data')
        d = f['game_delta_laps']
        ds = ('%+.1f' % d).replace('.', ',') if cs else '%+.1f' % d
        if d < 0:
            return R.say(lang, 'fuel_low', d=ds)
        return R.say(lang, 'fuel_ok', d=ds)
    if intent == 'gap':
        g = race.get('gaps')
        if not g:
            return R.say(lang, 'no_data')
        parts = []
        if g.get('ahead') is not None:
            parts.append(('Gap ahead %s' if cs else 'Gap ahead %s') %
                         R.fmt_delta(g['ahead'], lang))
            if g.get('ahead_trend') is not None:
                tr = g['ahead_trend']
                parts.append((('stahuješ %s/lap' if tr < 0 else 'ujíždí %s/lap') if cs else
                              ('closing %s/lap' if tr < 0 else 'losing %s/lap')) %
                             R.fmt_delta(tr, lang))
        if g.get('behind') is not None:
            parts.append(('gap behind %s' if cs else 'gap behind %s') % R.fmt_delta(g['behind'], lang))
            if g.get('behind_trend') is not None:
                tr = g['behind_trend']
                parts.append((('dojíždí tě %s/lap' if tr < 0 else 'ztrácí %s/lap') if cs else
                              ('closing %s/lap' if tr < 0 else 'dropping %s/lap')) %
                             R.fmt_delta(tr, lang))
        return (', '.join(parts) + '.') if parts else R.say(lang, 'no_data')
    if intent == 'corners':
        cs_list = [c for c in snap['corners'] if c.get('avg_loss') is not None and c['avg_loss'] >= 20]
        if not cs_list:
            if any(c.get('avg_loss') is not None for c in snap['corners']):
                return ('Ve všech turns jsi do 0,02 s od reference. Dobrá práce.' if cs else
                        'Within two hundredths of the reference in every corner. Good job.')
            return R.say(lang, 'no_data')
        cs_list.sort(key=lambda c: -c['avg_loss'])
        out = []
        for c in cs_list[:2]:
            if c.get('last'):
                out.append(R.corner_message(lang, c['last'], engine.level))
            else:
                out.append(R.say(lang, 'corner_loss', name=c['name'],
                                 d=R.fmt_delta(c['avg_loss'], lang)))
        return ' '.join(out)
    if intent == 'target':
        t = snap.get('target')
        if not t:
            return R.say(lang, 'no_data')
        msg = (('Target pro AI %d: %s (%s).' if cs else 'Target for AI %d: %s (%s).') %
               (t['ai'], R.fmt_lap(t['lap_ms']), t['src']))
        if t.get('match_ai') is not None:
            msg += ' ' + R.say(lang, 'match', ai=t['match_ai'])
        return msg
    # pace
    laps = [l for l in snap['laps'] if l['valid']]
    if not laps:
        return R.say(lang, 'no_data')
    last = laps[-1]
    msg = R.say(lang, 'lap', time=R.fmt_lap(last['time']))
    if snap.get('best'):
        msg += ' Session best %s.' % R.fmt_lap(snap['best']['time'])
    if snap.get('theoretical_best'):
        msg += ' Theoretical best %s.' % R.fmt_lap(snap['theoretical_best'])
    return msg


def answer(engine, question):
    key = engine.settings.get('gemini_key')
    if key:
        try:
            text = ask_gemini(key, engine.settings.get('gemini_model', 'gemini-2.5-flash'),
                              engine.lang, question, engine.context_for_llm())
            if text:
                return text, 'gemini'
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
            fallback = answer_offline(engine, question)
            return fallback + (' (Gemini nedostupné: %s)' % str(e)[:80]), 'offline'
    return answer_offline(engine, question), 'offline'
