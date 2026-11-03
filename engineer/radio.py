"""Texty týmového rádia. Česky = české věty s anglickou F1 terminologií.

Úroveň inženýra (verbosity):
  1 = Rookie – málo hlášení, jedna jednoduchá rada
  2 = Advanced – standard
  3 = Pro – víc detailů, i drobné ztráty
"""

LEVELS = {
    1: {'corner_min_loss': 120, 'tips': 1, 'corners': 1, 'sector_msgs': False},
    2: {'corner_min_loss': 60, 'tips': 2, 'corners': 2, 'sector_msgs': False},
    3: {'corner_min_loss': 30, 'tips': 2, 'corners': 3, 'sector_msgs': True},
}

T = {
    'cs': {
        'lap': 'Lap {time}.',
        'lap_delta_slow': 'Delta +{d} na referenci.',
        'lap_delta_fast': 'Delta -{d}, rychlejší než reference!',
        'pb': 'Personal best! {time}.',
        'invalid': 'Lap invalid.',
        'target_gap_slow': 'Na target pro AI {ai} chybí {d}.',
        'target_gap_fast': 'Jsi {d} pod targetem pro AI {ai}. Zkus zvýšit AI difficulty.',
        'match': 'Tvoje pace odpovídá zhruba AI {ai}.',
        'corner_loss': 'V {name} ztrácíš {d}.',
        'tip_brake_early': 'braking point o {0} m dřív',
        'tip_overdrive': 'braking point o {0} m později a přestřelíš apex, minimum speed o {1} km/h nižší',
        'tip_min_speed': 'minimum speed v apexu o {0} km/h nižší',
        'tip_throttle_late': 'full throttle o {0} m později',
        'tip_exit': 'exit speed o {0} km/h nižší',
        'tip_gear': 'gear {0}, reference gear {1}',
        'sector': 'Sector {n}: {d}.',
        'fuel_low': 'Fuel delta {d} laps. Potřebuješ lift and coast.',
        'fuel_ok': 'Fuel v pořádku, fuel delta {d} laps.',
        'tyre_wear': 'Tyre wear {w} %, nejvíc {wheel}.',
        'gap_closing': 'Gap ahead {g}, stahuješ {r} za lap.',
        'gap_losing': 'Gap ahead {g}, ztrácíš {r} za lap.',
        'gap_behind_closing': 'Gap behind {g}, dojíždí tě {r} za lap.',
        'gap_behind_dropping': 'Gap behind {g}, ztrácí {r} za lap.',
        'catch_in': 'Dojedeš ho zhruba za {n} laps.',
        'no_data': 'Zatím nemám dost dat.',
        'session_start': 'Radio check. {track}, {session}. AI difficulty {ai}.',
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
    'cs': {'RL': 'rear left', 'RR': 'rear right', 'FL': 'front left', 'FR': 'front right'},
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
