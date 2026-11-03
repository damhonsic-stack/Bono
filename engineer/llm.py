"""Odpovědi na otázky jezdce: Gemini (volitelně) nebo offline pravidla."""
import json
import ssl
import urllib.request
import urllib.error

from . import radio as R

SYSTEM_PROMPT = {
    'cs': """Jmenuješ se {name} a jsi závodní inženýr F1 týmu. Mluvíš se svým jezdcem přes týmové rádio během hry F1 25.
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
- Turns jsou číslované automaticky (T1, T2 …) podle pořadí na trati, ne podle oficiálního číslování.
- regs_2026 (regulace 2026): aero.mode Straight/Corner = active aero; overtake = Overtake mode
  (available/active/distance = metry do zpřístupnění); ers.pct = battery %, harvest_left_mj = zbývající
  harvest v tomto lapu; last_lap.straight_pct = kolik % dostupných aero zón jezdec jel ve Straight mode.""",
    'en': """Your name is {name}. You are an F1 race engineer talking to your driver over team radio during the game F1 25.
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
- Corners are auto-numbered T1, T2 ... in track order, not official turn numbers.
- regs_2026 (2026 regulations): aero.mode Straight/Corner = active aero; overtake = Overtake mode
  (available/active/distance in metres until available); ers.pct = battery %, harvest_left_mj = harvest
  left this lap; last_lap.straight_pct = % of available aero zone distance actually used in Straight mode.
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


def ask_gemini(api_key, model, lang, question, context, timeout=8, name='Bono'):
    url = ('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model)
    body = {
        'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT.get(lang, SYSTEM_PROMPT['en'])
                                          .replace('{name}', name)}]},
        'contents': [{
            'role': 'user',
            'parts': [{'text': 'DATA (JSON):\n' + json.dumps(context, ensure_ascii=False) +
                       '\n\nDRIVER: ' + question}],
        }],
        # Gemini 3.x: thinkingLevel "low" = rychlá odpověď (v rádiu záleží na latenci)
        # limit zahrnuje i "thinking" tokeny, proto rezerva
        'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 2048,
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


def ask_with_fallback(api_key, preferred, lang, question, context, name='Bono'):
    """Zkusí preferovaný model a pak zálohy. Vrátí (text, model) nebo vyhodí poslední chybu."""
    models = [preferred] + [m for m in FALLBACK_MODELS if m != preferred]
    last = None
    for m in models:
        if not m:
            continue
        try:
            text = ask_gemini(api_key, m, lang, question, context, name=name)
            if text:
                return text, m
        except (GeminiError, urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
            last = e
            if isinstance(e, GeminiError) and str(e).startswith(('401', '403')):
                break  # špatný klíč – další modely nepomůžou
    raise last or GeminiError('empty response')


# ---------------------------------------------------------------- offline pravidla
KEYWORDS = [
    ('tyres', ['gum', 'pneu', 'tyre', 'tire', 'opotřeb', 'opotreb', 'wear', 'soft', 'medium', 'hard']),
    ('fuel', ['paliv', 'benz', 'fuel', 'nádrž', 'nadrz']),
    ('ers', ['battery', 'baterie', 'ers', 'energy', 'energie', 'overtake mode', 'straight mode',
             'aero', 'harvest', 'deploy', 'boost']),
    ('gap', ['mezer', 'gap', 'před', 'pred', 'za mnou', 'dojíž', 'dojiz', 'stahu', 'behind', 'ahead',
             'catching', 'closing']),
    ('corners', ['zatáč', 'zatac', 'ztrác', 'ztrac', 'corner', 'turn', 'apex', 'losing', 'kde',
                 'where', 'braking']),
    ('target', ['obtížn', 'obtizn', 'ai ', 'cíl', 'cil', 'target', 'difficulty']),
    ('status', ['status', 'report', 'update', 'how am i', 'how are we', 'situation', 'jak to vypadá',
                'jak jsem na tom', 'shrnutí']),
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
    if intent == 'status':
        return status_report(engine, snap)
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
    if not race:
        txt = answer_intent(engine, 'pace', snap)
        parts.append(txt)
    return ' '.join(parts) if parts else R.say(lang, 'no_data')


def answer_intent(engine, intent, snap=None):
    """Offline odpověď pro konkrétní záměr (pro tlačítka na ovladači)."""
    q = {'gap': 'gap', 'tyres': 'tyres', 'fuel': 'fuel', 'corners': 'corner',
         'pace': 'pace', 'target': 'target', 'ers': 'ers', 'status': 'status'}.get(intent, intent)
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


def answer(engine, question):
    question = strip_wake_word(question, engine.settings.get('wake_word', 'bono'))
    if not question:
        return R.say(engine.lang, 'cmd_radio_check'), 'command'
    cmd = match_command(question)
    if cmd:
        with engine.lock:
            text = run_command(engine, cmd)
        return text, 'command'
    key = engine.settings.get('gemini_key')
    if key:
        try:
            text, model = ask_with_fallback(
                key, engine.settings.get('gemini_model') or DEFAULT_MODEL, engine.lang, question,
                engine.context_for_llm(), name=engine.settings.get('engineer_name', 'Bono'))
            engine.last_llm_model = model
            return text, 'gemini'
        except Exception as e:  # noqa: BLE001 – v závodě vždy odpověz aspoň offline
            engine.last_llm_error = str(e)[:200]
            return answer_offline(engine, question), 'offline'
    return answer_offline(engine, question), 'offline'
