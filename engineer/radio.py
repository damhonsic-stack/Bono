"""Texty týmového rádia v češtině a angličtině.

Úroveň inženýra (verbosity):
  1 = Nováček – málo hlášení, jedna jednoduchá rada
  2 = Pokročilý – standard
  3 = Pro – víc detailů, i drobné ztráty
"""

LEVELS = {
    1: {'corner_min_loss': 120, 'tips': 1, 'corners': 1, 'sector_msgs': False},
    2: {'corner_min_loss': 60, 'tips': 2, 'corners': 2, 'sector_msgs': False},
    3: {'corner_min_loss': 30, 'tips': 2, 'corners': 3, 'sector_msgs': True},
}

T = {
    'cs': {
        'lap': 'Kolo {time}.',
        'lap_delta_slow': 'O {d} pomaleji než reference.',
        'lap_delta_fast': 'O {d} rychleji než reference!',
        'pb': 'Nejrychlejší kolo! {time}.',
        'invalid': 'Kolo neplatné.',
        'target_gap_slow': 'Na cíl pro AI {ai} chybí {d}.',
        'target_gap_fast': 'Jsi {d} pod cílem pro AI {ai}. Zkus přidat obtížnost.',
        'match': 'Tvoje tempo odpovídá zhruba AI {ai}.',
        'corner_loss': 'V {name} ztrácíš {d}.',
        'tip_brake_early': 'brzdíš o {0} m dřív',
        'tip_overdrive': 'brzdíš o {0} m později a přestřelíš, ve vrcholu o {1} km/h pomaleji',
        'tip_min_speed': 'vrcholem neseš o {0} km/h méně',
        'tip_throttle_late': 'na plný plyn o {0} m později',
        'tip_exit': 'výjezd o {0} km/h pomalejší',
        'tip_gear': 've vrcholu máš {0}. rychlost, reference {1}',
        'sector': 'Sektor {n}: {d}.',
        'fuel_low': 'Palivo: {d} kola. Šetři – lift and coast před brzděním.',
        'fuel_ok': 'Palivo v pořádku, rezerva {d} kola.',
        'tyre_wear': 'Opotřebení gum {w} %, nejvíc {wheel}.',
        'gap_closing': 'Stahuješ auto před sebou o {r} za kolo, mezera {g}.',
        'gap_losing': 'Auto před tebou ujíždí o {r} za kolo, mezera {g}.',
        'gap_behind_closing': 'Auto za tebou dojíždí o {r} za kolo, mezera {g}.',
        'gap_behind_dropping': 'Auto za tebou ztrácí {r} za kolo, mezera {g}.',
        'catch_in': 'Dojedeš ho zhruba za {n} kol.',
        'no_data': 'Zatím nemám dost dat.',
        'session_start': 'Rádio zapnuto. {track}, {session}. Obtížnost AI {ai}.',
    },
    'en': {
        'lap': 'Lap {time}.',
        'lap_delta_slow': '{d} slower than reference.',
        'lap_delta_fast': '{d} faster than reference!',
        'pb': 'Fastest lap! {time}.',
        'invalid': 'Lap invalidated.',
        'target_gap_slow': '{d} off the target for AI {ai}.',
        'target_gap_fast': 'You are {d} under the AI {ai} target. Consider raising difficulty.',
        'match': 'Your pace matches roughly AI {ai}.',
        'corner_loss': 'Losing {d} in {name}.',
        'tip_brake_early': 'braking {0} m too early',
        'tip_overdrive': 'braking {0} m later and overshooting, {1} km/h slower at apex',
        'tip_min_speed': 'carrying {0} km/h less through the apex',
        'tip_throttle_late': 'full throttle {0} m later',
        'tip_exit': 'exit {0} km/h slower',
        'tip_gear': 'gear {0} at apex, reference uses {1}',
        'sector': 'Sector {n}: {d}.',
        'fuel_low': 'Fuel is {d} laps. Lift and coast into braking zones.',
        'fuel_ok': 'Fuel is fine, plus {d} laps.',
        'tyre_wear': 'Tyre wear {w} percent, worst {wheel}.',
        'gap_closing': 'Closing on the car ahead by {r} a lap, gap {g}.',
        'gap_losing': 'Car ahead pulling away by {r} a lap, gap {g}.',
        'gap_behind_closing': 'Car behind closing by {r} a lap, gap {g}.',
        'gap_behind_dropping': 'Car behind dropping back {r} a lap, gap {g}.',
        'catch_in': 'You will catch him in about {n} laps.',
        'no_data': 'Not enough data yet.',
        'session_start': 'Radio check. {track}, {session}. AI difficulty {ai}.',
    },
}

WHEEL_NAMES = {
    'cs': {'RL': 'zadní levá', 'RR': 'zadní pravá', 'FL': 'přední levá', 'FR': 'přední pravá'},
    'en': {'RL': 'rear left', 'RR': 'rear right', 'FL': 'front left', 'FR': 'front right'},
}


def fmt_lap(ms):
    if not ms:
        return '-'
    ms = int(round(ms))
    m, rest = divmod(ms, 60000)
    return '%d:%06.3f' % (m, rest / 1000.0)


def fmt_delta(ms, lang='cs', signed=False):
    s = abs(ms) / 1000.0
    if signed:
        txt = ('+' if ms >= 0 else '-') + '%.2f' % s
    else:
        txt = '%.2f' % s
    if lang == 'cs':
        txt = txt.replace('.', ',')
    return txt + (' s' if lang == 'cs' else '')


def say(lang, key, **kw):
    return T.get(lang, T['cs'])[key].format(**kw)


def tip_text(lang, tip):
    key = 'tip_' + tip[0]
    return T.get(lang, T['cs'])[key].format(*tip[1:])


def corner_message(lang, item, level):
    cfg = LEVELS[level]
    tips = [tip_text(lang, t) for t in item.get('tips', [])[:cfg['tips']]]
    msg = say(lang, 'corner_loss', name=item['name'], d=fmt_delta(item['loss'], lang))
    if tips:
        msg += ' ' + (', '.join(tips)).capitalize() + '.'
    return msg
