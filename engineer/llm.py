"""Odpovědi na otázky jezdce: Gemini (volitelně) nebo offline pravidla."""
import json
import re
import ssl
import time
import urllib.request
import urllib.error

from . import radio as R

SYSTEM_PROMPT = {
    'cs': """Jmenuješ se {name} a jsi závodní inženýr F1 týmu. Mluvíš se svým jezdcem přes týmové rádio během hry F1 25.
PRAVIDLA:
- Jsi klidný, přátelský a profesionální, jako skutečný inženýr na pit wallu. Mluvíš přirozeně česky.
- Odpovídej maximálně 2–3 krátké věty, jako v rádiu. Žádné odrážky, žádný markdown, žádné emoji.
- Na otázky mimo data (F1 obecně, hra, pozdrav, pochvala, vtip, „jak se máš“) odpověz normálně a krátce.
- Navazuj na předchozí konverzaci (zájmena jako „on“, „tam“, „a co teď“ se týkají toho, o čem byla řeč).
- Čísla piš slovy nebo jednoduše, budou se číst nahlas (např. „jedna celá dvě sekundy“).
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
- Turns jsou číslované automaticky (T1, T2 …) podle pořadí na trati, ne podle oficiálního číslování.
- regs_2026 (regulace 2026): aero.mode Straight/Corner = active aero; overtake = Overtake mode
  (available/active/distance = metry do zpřístupnění); ers.pct = battery %, harvest_left_mj = zbývající
  harvest v tomto lapu; last_lap.straight_pct = kolik % dostupných aero zón jezdec jel ve Straight mode.
- strategy.plan: doporučené zastávky (laps = box na KONCI lapu, tyres), alt = alternativa a o kolik ms je
  pomalejší; rejoin = pozice po zastávce teď; stints deg_ms = degradace za lap. cars_around: auta kolem
  (gap ms, záporné = před jezdcem; pace_delta ms/lap, záporné = rychlejší). incidents: warnings, track
  limits, penalizace, damage %. weather.forecast: minuty dopředu + rain %. quali: stav a gap na trati.
  setup_advice + car_balance (ratio >1,25 understeer, <0,8 oversteer).
- bono_memory: co si pamatuješ o jezdci (driver_notes = co ti řekl, this_track = dřívější session,
  nejlepší čas, opakovaně slabé zatáčky). Používej to přirozeně („minule jsi tady ztrácel v T8“).""",
    'en': """Your name is {name}. You are an F1 race engineer talking to your driver over team radio during the game F1 25.
RULES:
- Answer in English, max 2-3 short radio-style sentences. No bullet points, no markdown, no emoji.
- Be calm, friendly and professional like a real pit wall engineer. Answer general F1 / game / small
  talk questions naturally and briefly. Follow up on the previous conversation.
- Use ONLY numbers from the JSON data below. Never invent data. If something is missing, say so.
- loss / avg_loss_ms = milliseconds lost in that corner section vs reference (positive = loss).
- brake_diff_m negative = braking earlier than reference; throttle_diff_m positive = later to full throttle.
- ahead_trend negative = driver closing on car ahead; behind_trend negative = car behind is closing.
- fuel own_delta_laps / game_delta_laps: positive = fuel margin in laps, negative = must save fuel.
- tyre wear is percent (RL, RR, FL, FR).
- target.lap_ms is the estimated target lap for the AI difficulty; match_ai = difficulty matching driver pace.
- Give concrete, actionable advice.
- Corners are auto-numbered T1, T2 ... in track order, not official turn numbers.
- regs_2026 (2026 regulations): aero.mode Straight/Corner = active aero; overtake = Overtake mode
  (available/active/distance in metres until available); ers.pct = battery %, harvest_left_mj = harvest
  left this lap; last_lap.straight_pct = % of available aero zone distance actually used in Straight mode.
- strategy.plan: recommended pit plan (laps = pit at END of that lap, tyres), alt = alternative and how
  much slower (ms); rejoin = predicted position if pitting now; pit_loss_ms; stints deg_ms = tyre
  degradation per lap. cars_around: nearby cars with gap (ms, negative = ahead), tyre, age, pace_delta
  (ms/lap, negative = faster than driver). incidents: warnings, track_limits, penalties, damage %.
  weather.forecast: minutes ahead + rain %. quali: driver status, gap on track (s). setup_advice +
  car_balance (ratio >1.25 understeer, <0.8 oversteer; entry/mid/exit and slow/medium/fast).
- bono_memory: what you remember about the driver (driver_notes, this_track: sessions before,
  best ever, recurring_weak_turns, last_session). Use it naturally ("last time here you lost in T8").
- Speak like a real F1 race engineer: calm, short, precise.""",
}


# Pořadí modelů: rychlý "lite" alias jako první, při přetížení/nedostupnosti další.
# Aliasy *-latest Google sám posouvá na nejnovější verzi, takže nezastarají.
DEFAULT_MODEL = 'gemini-flash-lite-latest'
FALLBACK_MODELS = ['gemini-flash-lite-latest', 'gemini-3.5-flash', 'gemini-flash-latest']


class GeminiError(Exception):
    pass


def _post(url, body, api_key, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json',
                                          'x-goog-api-key': api_key})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode('utf-8'))['error']['message']
        except (ValueError, KeyError, OSError):
            msg = str(e)
        raise GeminiError('%d: %s' % (e.code, msg))


PERSONAS = {
    'cs': {'bono': 'Povaha: klidný, přátelský a věcný.',
           'vlasta': 'Povaha: energická a povzbuzující, mluví s nadšením a chválí dobré věci.',
           'kouc': 'Povaha: přísný kouč – stručný, náročný, chce víc a nic nepřikrášluje.'},
    'en': {'bono': 'Personality: calm, friendly and factual.',
           'vlasta': 'Personality: energetic and encouraging, enthusiastic, praises good work.',
           'kouc': 'Personality: strict coach – short, demanding, always asks for more.'},
}
PERSONA = {'name': 'bono'}


def persona_line(lang):
    return PERSONAS.get(lang, PERSONAS['en']).get(PERSONA['name'], '')


def ask_gemini(api_key, model, lang, question, context, timeout=8, name='Bono', system=None,
               max_tokens=2048, history=None):
    url = ('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model)
    body = {
        'systemInstruction': {'parts': [{'text': system or (SYSTEM_PROMPT.get(lang, SYSTEM_PROMPT['en'])
                                          .replace('{name}', name) + '\n- ' + persona_line(lang))}]},
        'contents': [c for q, a in (history or [])[-6:] for c in (
            {'role': 'user', 'parts': [{'text': 'DRIVER: ' + q}]},
            {'role': 'model', 'parts': [{'text': a}]})] + [{
            'role': 'user',
            'parts': [{'text': 'DATA (JSON):\n' + json.dumps(context, ensure_ascii=False) +
                       '\n\nDRIVER: ' + question}],
        }],
        # Gemini 3.x: thinkingLevel "low" = rychlá odpověď (v rádiu záleží na latenci)
        # limit zahrnuje i "thinking" tokeny, proto rezerva
        'generationConfig': {'temperature': 0.3, 'maxOutputTokens': max_tokens,
                             'thinkingConfig': {'thinkingLevel': 'low'}},
    }
    try:
        data = _post(url, body, api_key, timeout)
    except GeminiError as e:
        if 'thinking' not in str(e).lower() and 'invalid argument' not in str(e).lower():
            raise
        body['generationConfig'].pop('thinkingConfig')  # starší model bez thinkingLevel
        data = _post(url, body, api_key, timeout)
    cand = data.get('candidates', [{}])[0]
    parts = cand.get('content', {}).get('parts', [])
    text = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
    if text and cand.get('finishReason') == 'MAX_TOKENS':
        cut = max(text.rfind('. '), text.rfind('! '), text.rfind('? '))
        text = text[:cut + 1] if cut > 0 else ''  # uříznutá odpověď → jen celé věty
    return text or None


def ask_with_fallback(api_key, preferred, lang, question, context, name='Bono', system=None,
                      max_tokens=2048, timeout=8, history=None):
    """Zkusí preferovaný model a pak zálohy. Vrátí (text, model) nebo vyhodí poslední chybu."""
    models = [preferred] + [m for m in FALLBACK_MODELS if m != preferred]
    last = None
    for m in models:
        if not m:
            continue
        try:
            text = ask_gemini(api_key, m, lang, question, context, name=name, system=system,
                              max_tokens=max_tokens, timeout=timeout, history=history)
            if text:
                return text, m
        except (GeminiError, urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
            last = e
            if isinstance(e, GeminiError) and str(e).startswith(('401', '403')):
                break  # špatný klíč – další modely nepomůžou
    raise last or GeminiError('empty response')


# ---------------------------------------------------------------- offline pravidla
KEYWORDS = [
    ('help', ['co se můžu zeptat', 'co se muzu zeptat', 'na co se můžu', 'what can i ask', 'nápověda',
              'napoveda', 'co umíš', 'co umis', 'what can you do']),
    ('around', ['kdo je', 'kdo jede', 'who is', "who's", 'přede mnou', 'prede mnou', 'za mnou',
                'ahead of me', 'behind me']),
    ('debrief', ['debrief', 'shrň session', 'session summary']),
    ('setup', ['setup', 'understeer', 'oversteer', 'balance', 'nedotáč', 'nedotac', 'přetáč',
               'pretac', 'handling', 'wing angle']),
    ('damage', ['damage', 'poškoz', 'poskoz', 'wing', 'křídl', 'kridl', 'puncture', 'defekt']),
    ('weather', ['rain', 'weather', 'déšť', 'dest', 'prší', 'prsi', 'počasí', 'pocasi', 'inters',
                 'intermediate']),
    ('strategy', ['strategy', 'strategie', 'box', 'pit', 'stop', 'undercut', 'overcut', 'plan',
                  'zastáv', 'zastav']),
    ('tyres', ['gum', 'pneu', 'tyre', 'tire', 'opotřeb', 'opotreb', 'wear', 'soft', 'medium', 'hard']),
    ('fuel', ['paliv', 'benz', 'fuel', 'nádrž', 'nadrz']),
    ('ers', ['battery', 'baterie', 'ers', 'energy', 'energie', 'overtake mode', 'straight mode',
             'aero', 'harvest', 'deploy', 'boost']),
    ('gap', ['mezer', 'gap', 'před', 'pred', 'za mnou', 'dojíž', 'dojiz', 'stahu', 'behind', 'ahead',
             'catching', 'closing', 'dojet', 'dojedu', 'dojedeme', 'catch', 'předjet', 'predjet']),
    ('corners', ['zatáč', 'zatac', 'ztrác', 'ztrac', 'corner', 'turn', 'apex', 'losing', 'kde',
                 'where', 'braking']),
    ('target', ['obtížn', 'obtizn', 'ai ', 'cíl', 'cil', 'target', 'difficulty']),
    ('status', ['status', 'report', 'update', 'how am i', 'how are we', 'situation', 'jak to vypadá',
                'jak jsem na tom', 'shrnutí']),
    ('pace', ['tempo', 'pace', 'čas', 'cas', 'kolo', 'lap']),
]


SMALLTALK = [
    ('thanks', ['díky', 'diky', 'děkuju', 'dekuju', 'děkuji', 'thanks', 'thank you', 'cheers',
                'dobrej', 'dobrý', 'good job', 'nice one', 'super', 'skvělý', 'skvely']),
    ('hello', ['ahoj', 'čau', 'cau', 'nazdar', 'hello', 'hi bono', 'hey bono', 'zdravím']),
    ('how', ['jak se máš', 'jak se mas', 'how are you', 'jak to jde']),
]
SMALLTALK_REPLY = {
    'cs': {'thanks': 'Rádo se stalo. Drž tempo.', 'hello': 'Ahoj, Bono na příjmu. Jsem tady pro tebe.',
           'how': 'Všechno v pohodě, sleduju data. Soustřeď se na jízdu.'},
    'en': {'thanks': 'No worries. Keep it up.', 'hello': 'Hey, Bono here. I am with you.',
           'how': 'All good here, watching the data. Focus on driving.'},
}


def smalltalk(question):
    q = question.lower()
    if len(q.split()) > 6:
        return None
    for kind, words in SMALLTALK:
        if any(w in q for w in words):
            return kind
    return None


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
    st = smalltalk(question)
    if st and intent == 'pace' or st == 'thanks':
        return SMALLTALK_REPLY.get(lang, SMALLTALK_REPLY['en'])[st]
    if intent == 'help':
        st = (snap.get('session') or {}).get('type_id')
        kind = 'help_race' if st in (15, 16, 17) else 'help_quali' if st in range(5, 15) else 'help_other'
        return R.say(lang, 'help', q=R.say(lang, kind))
    if intent == 'around':
        return around_report(engine, snap)
    if intent == 'status':
        return status_report(engine, snap)
    if intent == 'strategy':
        return strategy_report(engine, snap)
    if intent == 'damage':
        return damage_report(engine, snap)
    if intent == 'weather':
        return weather_report(engine, snap)
    if intent == 'setup':
        return setup_report(engine, snap)
    if intent == 'debrief':
        ok = engine.start_debrief(announce=True)
        if cs:
            return 'Připravuju debrief, bude na obrazovce.' if ok else R.say(lang, 'no_data')
        return 'Preparing the debrief, it will be on the screen.' if ok else R.say(lang, 'no_data')
    if intent == 'ers':
        return ers_report(engine, snap)
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


def ers_report(engine, snap):
    lang = engine.lang
    r = snap.get('regs') or {}
    parts = []
    if r.get('ers'):
        e = r['ers']
        parts.append(R.say(lang, 'ers_status', p=e['pct'], mode=e['mode']))
        if e.get('harvest_left_mj') is not None:
            h = '%.1f' % e['harvest_left_mj']
            parts.append(R.say(lang, 'ers_harvest', h=h.replace('.', ',') if lang == 'cs' else h))
    ot = r.get('overtake')
    if ot:
        if ot['available'] or ot['active']:
            parts.append(R.say(lang, 'ot_ready'))
        elif ot['distance']:
            parts.append(R.say(lang, 'ot_in', m=ot['distance']))
    last = r.get('last_lap') or {}
    if last.get('straight_pct') is not None:
        parts.append(R.say(lang, 'aero_last', p=last['straight_pct']))
    return ' '.join(parts) if parts else R.say(lang, 'no_data')


def around_report(engine, snap):
    lang = engine.lang
    cs = lang == 'cs'
    cars = snap.get('around') or []
    me = next((c for c in cars if c['me']), None)
    if not me:
        return R.say(lang, 'no_data')
    parts = []
    for c in cars:
        if c['me'] or abs(c['pos'] - me['pos']) != 1:
            continue
        where = ('před tebou' if c['pos'] < me['pos'] else 'za tebou') if cs else \
            ('ahead' if c['pos'] < me['pos'] else 'behind')
        txt = ('%s %s, %s, %s %s' if cs else '%s %s, %s, %s %s') % (
            c['name'], where, R.fmt_delta(abs(c['gap']), lang), c['tyre'],
            ('%d lapů' % c['age']) if cs and c['age'] is not None else
            ('%d laps old' % c['age'] if c['age'] is not None else ''))
        if c.get('pace_delta') is not None and abs(c['pace_delta']) >= 100:
            faster = c['pace_delta'] < 0
            txt += (', o %s za lap %s' % (R.fmt_delta(abs(c['pace_delta']), lang),
                                          'rychlejší' if faster else 'pomalejší')) if cs else \
                (', %s a lap %s' % (R.fmt_delta(abs(c['pace_delta']), lang),
                                    'faster' if faster else 'slower'))
        parts.append(txt + '.')
    return ' '.join(parts) if parts else R.say(lang, 'no_data')


def strategy_report(engine, snap):
    lang = engine.lang
    cs = lang == 'cs'
    st = snap.get('strategy') or {}
    parts = []
    with engine.lock:
        plan_text = engine._plan_text()
        rejoin = engine._rejoin_text() if st.get('rejoin') else ''
    if plan_text:
        parts.append(plan_text)
    p = st.get('plan')
    if p and p.get('alt'):
        parts.append(('Alternativa %d-stop je o %s pomalejší.' if cs else
                      'The %d-stop is %s slower.') % (p['alt']['stops'],
                                                      R.fmt_delta(p['alt']['delta_ms'], lang)))
    if st.get('stints'):
        s = st['stints'][-1]
        parts.append(R.say(lang, 'deg', d=R.fmt_delta(s['deg_ms'], lang), tyre=s['tyre']))
    w = st.get('game_window') or [None, None]
    if w[0]:
        parts.append(R.say(lang, 'pit_window', ideal=w[0], latest=w[1]))
    if rejoin and p and p.get('stops'):
        parts.append(('Kdybys jel do boxu teď: ' if cs else 'If you box now: ') + rejoin)
    return ' '.join(parts) if parts else R.say(lang, 'no_data')


def damage_report(engine, snap):
    lang = engine.lang
    inc = snap.get('incidents') or {}
    dmg = inc.get('damage') or {}
    if not dmg:
        return 'Žádné poškození.' if lang == 'cs' else 'No damage, car is fine.'
    parts = [R.say(lang, 'damage', part=R.DAMAGE_PARTS.get(k, k), p=v)
             for k, v in sorted(dmg.items(), key=lambda kv: -kv[1])[:3]]
    return ' '.join(parts)


def weather_report(engine, snap):
    lang = engine.lang
    cs = lang == 'cs'
    w = snap.get('weather') or {}
    msg = ('Teď %s, trať %s °C.' if cs else 'Currently %s, track %s degrees.') % (
        w.get('now') or '?', w.get('track_temp'))
    rain = [f for f in w.get('forecast', []) if f['rain'] >= 40 or f['weather'] in
            ('Light Rain', 'Heavy Rain', 'Storm')]
    if rain:
        f = rain[0]
        msg += ' ' + R.say(lang, 'rain_coming', m=f['min'], p=f['rain'])
    else:
        msg += ' Déšť se nečeká.' if cs else ' No rain expected.'
    return msg


def setup_report(engine, snap):
    lang = engine.lang
    adv = (snap.get('setup') or {}).get('advice') or []
    if not adv:
        return R.say(lang, 'no_setup')
    txt = '; '.join('%s: %s' % (a['issue'], a['change']) for a in adv[:2])
    return R.say(lang, 'setup_header', txt=txt)


def status_report(engine, snap):
    """Krátký souhrn jako od inženýra: pozice, mezery, gumy, palivo, baterie."""
    lang = engine.lang
    race = snap.get('race') or {}
    parts = []
    if race.get('position'):
        parts.append(R.say(lang, 'status_pos', pos=race['position']))
    for intent in ('gap', 'tyres', 'fuel'):
        txt = answer_intent(engine, intent, snap)
        if txt and txt != R.say(lang, 'no_data'):
            parts.append(txt.split('. ')[0].rstrip('.') + '.')
    r = snap.get('regs') or {}
    if r.get('ers'):
        parts.append(R.say(lang, 'ers_status', p=r['ers']['pct'], mode=r['ers']['mode']))
    with engine.lock:
        plan_text = engine._plan_text()
    if plan_text:
        parts.append(plan_text)
    if not race:
        txt = answer_intent(engine, 'pace', snap)
        parts.append(txt)
    return ' '.join(parts) if parts else R.say(lang, 'no_data')


def answer_intent(engine, intent, snap=None):
    """Offline odpověď pro konkrétní záměr (pro tlačítka na ovladači)."""
    q = {'gap': 'gap', 'tyres': 'tyres', 'fuel': 'fuel', 'corners': 'corner',
         'pace': 'pace', 'target': 'target', 'ers': 'ers', 'status': 'status',
         'strategy': 'strategy', 'damage': 'damage', 'setup': 'setup', 'weather': 'weather',
         'debrief': 'debrief'}.get(intent, intent)
    return answer_offline(engine, q)


# ---------------------------------------------------------------- příkazy
COMMANDS = [
    ('unmute', ['unmute', 'talk to me', 'speak again', 'mluv', 'zapni rádio']),
    ('mute', ['mute', 'quiet', 'be quiet', 'shut up', 'silence', 'ticho', 'mlč', 'buď potichu']),
    ('repeat', ['repeat', 'say again', 'say that again', 'come again', 'zopakuj', 'znovu']),
    ('radio_check', ['radio check', 'can you hear', 'slyšíš']),
]


def strip_wake_word(text, wake):
    import re
    t = text.strip()
    if wake:
        t = re.sub(r'^\W*(hey\s+|hi\s+|ok\s+)?' + re.escape(wake.lower()) + r'\W*', '',
                   t, flags=re.IGNORECASE)
    return t.strip(' ,.!?')


def match_command(text):
    q = ' ' + text.lower().strip(' .!?') + ' '
    for cmd, words in COMMANDS:
        for w in words:
            if (' ' + w + ' ') in q or q.strip() == w:
                return cmd
    return None


def run_command(engine, action):
    """Provede příkaz / akci tlačítka. Vrátí text odpovědi (nebo None)."""
    lang = engine.lang
    if action == 'mute':
        engine.settings['voice'] = False
        return R.say(lang, 'cmd_muted')
    if action == 'unmute':
        engine.settings['voice'] = True
        return R.say(lang, 'cmd_unmuted')
    if action == 'radio_check':
        return R.say(lang, 'cmd_radio_check')
    if action == 'repeat':
        for m in reversed(engine.messages):
            if m.get('prio', 1) >= 1:
                return m['text']
        return R.say(lang, 'cmd_nothing_to_repeat')
    return answer_intent(engine, action)


CHAT_MODELS = ['gemini-flash-lite-latest', 'gemini-3.6-flash', 'gemini-flash-latest']
GROQ_MODELS = ['llama-3.3-70b-versatile', 'openai/gpt-oss-120b']
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'


def ask_groq(api_key, model, lang, question, context, timeout=6, name='Bono', history=None):
    """Groq (zdarma, velmi rychlé): OpenAI-kompatibilní chat API."""
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT.get(lang, SYSTEM_PROMPT['en'])
             .replace('{name}', name) + '\n- ' + persona_line(lang)}]
    for q, a in (history or [])[-6:]:
        msgs += [{'role': 'user', 'content': 'DRIVER: ' + q}, {'role': 'assistant', 'content': a}]
    msgs.append({'role': 'user', 'content': 'DATA (JSON):\n' + json.dumps(context, ensure_ascii=False) +
                 '\n\nDRIVER: ' + question})
    body = {'model': model, 'messages': msgs, 'temperature': 0.3, 'max_tokens': 400}
    if model.startswith('openai/gpt-oss'):
        body['reasoning_effort'] = 'low'
    req = urllib.request.Request(GROQ_URL, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + api_key,
                                          'User-Agent': 'bono-f1-engineer'})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            data = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode('utf-8'))['error']['message']
        except (ValueError, KeyError, OSError):
            msg = str(e)
        raise GeminiError('groq %d: %s' % (e.code, msg))
    text = (data['choices'][0]['message'].get('content') or '').strip()
    return text or None
_model_down = {}          # model -> čas, do kdy ho přeskakovat (přetížení / timeout)


def ask_fast(api_key, models, lang, question, context, name='Bono', history=None,
             deadline=6.0, hedge_after=2.5, groq_key=None):
    """Konverzace v závodě: první model hned, druhý souběžně po hedge_after s, celkem max
    deadline s. Vrátí (text, model) nebo vyhodí chybu (pak odpoví offline)."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    now = time.time()
    order = [m for m in models if _model_down.get(m, 0) < now] or list(models)
    pool = ThreadPoolExecutor(max_workers=2)
    futs = {}
    t0 = time.time()

    def submit(m):
        if m.startswith('groq:'):
            futs[pool.submit(ask_groq, groq_key, m[5:], lang, question, context, deadline, name,
                             history)] = m
        else:
            futs[pool.submit(ask_gemini, api_key, m, lang, question, context, deadline, name,
                             None, 2048, history)] = m
    submit(order[0])
    nxt = 1
    last = None
    try:
        while futs:
            left = deadline - (time.time() - t0)
            if left <= 0:
                break
            step = min(left, hedge_after) if nxt < len(order) and len(futs) < 2 else left
            done, _ = wait(list(futs), timeout=step, return_when=FIRST_COMPLETED)
            for f in done:
                m = futs.pop(f)
                try:
                    text = f.result()
                    if text:
                        return text, m
                except Exception as e:  # noqa: BLE001
                    last = e
                    _model_down[m] = time.time() + 60
            if (not done or not futs) and nxt < len(order) and len(futs) < 2:
                submit(order[nxt])
                nxt += 1
        for m in futs.values():
            _model_down[m] = time.time() + 60
        raise last or GeminiError('timeout %.0fs' % deadline)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def answer(engine, question):
    PERSONA['name'] = engine.settings.get('persona', 'bono')
    question = strip_wake_word(question, engine.settings.get('wake_word', 'bono'))
    question = re.sub(r'^\W*r[aá]di[oa]\W*', '', question, flags=re.I).strip() or question
    if not question:
        return R.say(engine.lang, 'cmd_radio_check'), 'command'
    from .memory import REMEMBER_RE, FORGET_RE
    m = REMEMBER_RE.match(question)
    if m:
        with engine.lock:
            engine.memory.add_note(m.group(1))
        return ('Zapamatováno: %s.' if engine.lang == 'cs' else 'Noted: %s.') % m.group(1).rstrip('.'), \
            'command'
    if FORGET_RE.match(question):
        with engine.lock:
            gone = engine.memory.forget_last()
        if engine.lang == 'cs':
            return ('Zapomněl jsem: %s.' % gone) if gone else 'Nemám nic k zapomenutí.', 'command'
        return ('Forgot: %s.' % gone) if gone else 'Nothing to forget.', 'command'
    cmd = match_command(question)
    if cmd:
        with engine.lock:
            text = run_command(engine, cmd)
        return text, 'command'
    key = engine.settings.get('gemini_key')
    groq = engine.settings.get('groq_key')
    if key or groq:
        try:
            with engine.lock:
                history = list(engine.chat_history)
            models = []
            if groq:   # Groq první (rychlý), Gemini jako souběžná záloha
                gm = engine.settings.get('groq_model') or GROQ_MODELS[0]
                models += ['groq:' + m for m in [gm] + [x for x in GROQ_MODELS if x != gm]][:1]
            if key:
                first = engine.settings.get('chat_model') or CHAT_MODELS[0]
                models += [first] + [m for m in CHAT_MODELS if m != first]
            if groq:
                models += ['groq:' + m for m in GROQ_MODELS if 'groq:' + m not in models]
            text, model = ask_fast(key, models, engine.lang, question, engine.context_for_llm(),
                                   name=engine.settings.get('engineer_name', 'Bono'),
                                   history=history, groq_key=groq)
            engine.last_llm_model = model
            with engine.lock:
                engine.chat_history = (engine.chat_history + [(question, text)])[-10:]
            return text, 'gemini'
        except Exception as e:  # noqa: BLE001 – v závodě vždy odpověz aspoň offline
            engine.last_llm_error = str(e)[:200]
            return answer_offline(engine, question), 'offline'
    return answer_offline(engine, question), 'offline'
