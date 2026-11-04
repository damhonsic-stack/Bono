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
        'session_start': '{name} tady, radio check. {track}, {session}. AI difficulty {ai}.',
        'regs_ot_available': 'Overtake mode available, gap ahead {g}. Use it.',
        'regs_ot_missed': 'Overtake mode byl k dispozici a nepoužil jsi ho.',
        'regs_ot_behind': 'Auto za tebou má overtake mode, gap {g}. Defend.',
        'regs_ot_enabled': 'Race control: overtake mode enabled.',
        'regs_ot_disabled': 'Race control: overtake mode disabled.',
        'regs_partial_on': 'Race control: partial mode, active aero omezené.',
        'regs_partial_off': 'Race control: full active aero zpět.',
        'regs_straight_low': 'Straight mode využíváš jen na {p} % aero zón.',
        'regs_battery_low': 'Battery jen {p} %. Nabíjej, šetři deploy.',
        'cmd_muted': 'Copy, budu potichu.',
        'cmd_unmuted': 'Copy, jsem zpátky.',
        'cmd_radio_check': 'Loud and clear.',
        'cmd_nothing_to_repeat': 'Nemám co zopakovat.',
        'status_pos': 'P{pos}.',
        'ers_status': 'Battery {p} %, deploy mode {mode}.',
        'ers_harvest': 'Harvest limit zbývá {h} MJ.',
        'ot_ready': 'Overtake mode ready.',
        'ot_in': 'Overtake mode za {m} m.',
        'aero_last': 'Minulý lap straight mode {p} % zón.',
    },
    'en': {
        'lap': 'Lap {time}.',
        'lap_delta_slow': 'Plus {d} to reference.',
        'lap_delta_fast': 'Minus {d} to reference, good lap!',
        'pb': 'Personal best! {time}.',
        'invalid': 'Lap invalidated.',
        'target_gap_slow': '{d} off the target for AI {ai}.',
        'target_gap_fast': 'You are {d} under the AI {ai} target. Consider raising the difficulty.',
        'match': 'Your pace matches roughly AI {ai}.',
        'corner_loss': 'Losing {d} in {name}.',
        'tip_brake_early': 'braking point {0} metres early',
        'tip_overdrive': 'braking {0} metres later and overshooting the apex, {1} km/h down on minimum speed',
        'tip_min_speed': 'minimum speed {0} km/h down at the apex',
        'tip_throttle_late': 'full throttle {0} metres later',
        'tip_exit': 'exit speed {0} km/h down',
        'tip_gear': 'gear {0} at the apex, reference uses {1}',
        'sector': 'Sector {n}: {d}.',
        'fuel_low': 'Fuel delta {d} laps. We need lift and coast.',
        'fuel_ok': 'Fuel is fine, delta {d} laps.',
        'tyre_wear': 'Tyre wear {w} percent, worst is {wheel}.',
        'gap_closing': 'Gap ahead {g}, you are closing {r} a lap.',
        'gap_losing': 'Gap ahead {g}, he is pulling away {r} a lap.',
        'gap_behind_closing': 'Gap behind {g}, he is closing {r} a lap.',
        'gap_behind_dropping': 'Gap behind {g}, he is dropping back {r} a lap.',
        'catch_in': 'You will catch him in about {n} laps.',
        'no_data': 'Not enough data yet.',
        'session_start': '{name} here, radio check. {track}, {session}. AI difficulty {ai}.',
        'regs_ot_available': 'Overtake mode available, gap ahead {g}. Use it.',
        'regs_ot_missed': 'Overtake mode was available and you did not use it.',
        'regs_ot_behind': 'Car behind has overtake mode, gap {g}. Defend.',
        'regs_ot_enabled': 'Race control: overtake mode enabled.',
        'regs_ot_disabled': 'Race control: overtake mode disabled.',
        'regs_partial_on': 'Race control: partial mode, active aero restricted.',
        'regs_partial_off': 'Race control: full active aero is back.',
        'regs_straight_low': 'You only used straight mode in {p} percent of the aero zones.',
        'regs_battery_low': 'Battery down to {p} percent. Harvest, go easy on deploy.',
        'cmd_muted': 'Copy, going quiet.',
        'cmd_unmuted': 'Copy, I am back.',
        'cmd_radio_check': 'Loud and clear.',
        'cmd_nothing_to_repeat': 'Nothing to repeat.',
        'status_pos': 'P{pos}.',
        'ers_status': 'Battery {p} percent, deploy mode {mode}.',
        'ers_harvest': '{h} megajoules of harvest left this lap.',
        'ot_ready': 'Overtake mode ready.',
        'ot_in': 'Overtake mode in {m} metres.',
        'aero_last': 'Last lap straight mode in {p} percent of the zones.',
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
    ph = corner_phase(item)
    if ph:
        msg = say(lang, 'corner_phase', name=item['name'], d=fmt_delta(item['loss'], lang),
                  phase=say(lang, 'phase_' + ph))
    else:
        msg = say(lang, 'corner_loss', name=item['name'], d=fmt_delta(item['loss'], lang))
    if tips:
        msg += ' ' + (', '.join(tips)).capitalize() + '.'
    return msg


# ---------------------------------------------------------------- strategie, soupeři, incidenty,
# kvalifikace, setup, debrief (rozšíření slovníků T)
_EXT = {
    'en': {
        # strategie
        'box_this_lap': 'Box this lap, box box. {tyre} tyres.',
        'box_next_lap': 'Box next lap for {tyre}s. Prepare.',
        'rejoin': 'You will rejoin P{pos}{who}.',
        'rejoin_behind': ', {g} behind {name}',
        'rejoin_ahead': ', {g} ahead of {name}',
        'pit_window': 'Pit window opens lap {ideal}, latest lap {latest}.',
        'plan': 'Plan is {stops}-stop: {plan}.',
        'plan_none': 'No stop needed, tyres take you to the end.',
        'plan_stop': 'lap {lap} onto {tyre}s',
        'deg': 'Tyre deg {d} per lap on the {tyre}s.',
        'sc_box': 'Safety car! Cheap stop, box box for {tyre}s.',
        'vsc_box': 'Virtual safety car. Box box, cheap stop for {tyre}s.',
        'undercut_on': 'Undercut on {name} is on, gap {g}. Fresh tyres are worth {x}.',
        'opp_pitted_ahead': '{name} ahead has boxed, on {tyre}s. Push now for the overcut.',
        'opp_pitted_behind': '{name} behind boxed for {tyre}s. Expect the undercut.',
        'rain_coming': 'Rain expected in about {m} minutes, {p} percent.',
        'rain_now_slicks': 'Track is getting wet. Consider {tyre}s.',
        'drying': 'Track is drying. Slicks soon.',
        # soupeři
        'opp_behind_fresh': '{name} behind on fresh {tyre}s, {x} a lap faster. He catches you in {n} laps.',
        'opp_ahead_old': '{name} ahead on {age}-lap old {tyre}s, you are {x} a lap faster.',
        # incidenty
        'warning': 'Warning number {n}.',
        'track_limits': 'Track limits warning, {n} so far.',
        'track_limits_many': 'That is {n} track limits warnings. Careful, the next one could be a penalty.',
        'penalty_time': '{s} second penalty. {why}.',
        'penalty_dt': 'Drive through penalty. {why}. Serve it within three laps.',
        'penalty_sg': 'Stop and go penalty. {why}.',
        'penalty_other': 'Penalty: {what}. {why}.',
        'blue_flag': 'Blue flag, let him by.',
        'yellow_ahead': 'Yellow flag ahead. Careful.',
        'sc_deployed': 'Safety car, safety car. Keep the delta positive.',
        'vsc_deployed': 'Virtual safety car deployed. Keep the delta positive.',
        'sc_in': 'Safety car in this lap. Get ready.',
        'green': 'Green flag, green flag. Race resumes.',
        'red_flag': 'Red flag, red flag. Slow down and come back to the pits.',
        'contact': 'Contact. Checking damage.',
        'damage': '{part} damage {p} percent.',
        'damage_box_wing': 'Front wing damage is significant. Box for a new nose.',
        'puncture': 'Puncture {wheel}! Box box.',
        'fault': '{part} fault.',
        # kvalifikace
        'out_lap': 'Out lap. Warm the tyres{battery}.',
        'out_lap_battery': ' and charge the battery',
        'tyre_temps': 'Tyre temps: fronts {f}, rears {r} degrees. {hint}',
        'temps_ok': 'Good, in the window.',
        'temps_cold': 'Still cold, keep working them.',
        'temps_hot': 'Too hot, ease off.',
        'traffic_close': 'Car ahead {g} on track. Back off, make space.',
        'clear_air': 'Clear track ahead, {g}.',
        'push_now': 'Push now, push push.',
        'car_behind_push': 'Car behind on a push lap, {g}. Do not impede.',
        'traffic_push': 'Watch it, car ahead {g}.',
        'provisional': 'Provisional P{pos}.',
        'time_left': '{m} minutes left in the session.',
        'battery_quali': 'Battery {p} percent.',
        # setup / debrief
        'setup_header': 'Setup suggestion: {txt}',
        'debrief_ready': 'Debrief is ready on the screen.',
        'no_setup': 'Not enough data for setup advice yet. Do a few clean laps.',
    },
    'cs': {
        'box_this_lap': 'Box this lap, box box. {tyre} tyres.',
        'box_next_lap': 'Příští lap box na {tyre}. Připrav se.',
        'rejoin': 'Vyjedeš na P{pos}{who}.',
        'rejoin_behind': ', {g} za {name}',
        'rejoin_ahead': ', {g} před {name}',
        'pit_window': 'Pit window se otevírá v lapu {ideal}, nejpozději lap {latest}.',
        'plan': 'Plán je {stops}-stop: {plan}.',
        'plan_none': 'Bez zastávky, gumy vydrží do konce.',
        'plan_stop': 'lap {lap} na {tyre}',
        'deg': 'Tyre deg {d} za lap na {tyre}.',
        'sc_box': 'Safety car! Levná zastávka, box box na {tyre}.',
        'vsc_box': 'Virtual safety car. Box box, levná zastávka na {tyre}.',
        'undercut_on': 'Undercut na {name} je možný, gap {g}. Nové gumy dají {x}.',
        'opp_pitted_ahead': '{name} před tebou byl v boxu, je na {tyre}. Teď push na overcut.',
        'opp_pitted_behind': '{name} za tebou byl v boxu na {tyre}. Čekej undercut.',
        'rain_coming': 'Déšť zhruba za {m} minut, {p} procent.',
        'rain_now_slicks': 'Trať vlhne. Zvaž {tyre}.',
        'drying': 'Trať osychá. Brzy slicks.',
        'opp_behind_fresh': '{name} za tebou na nových {tyre}, o {x} za lap rychlejší. Dojede tě za {n} lapů.',
        'opp_ahead_old': '{name} před tebou na {age} lapů starých {tyre}, jsi o {x} za lap rychlejší.',
        'warning': 'Warning číslo {n}.',
        'track_limits': 'Track limits warning, celkem {n}.',
        'track_limits_many': 'Už {n} track limits warningy. Opatrně, další může být penalty.',
        'penalty_time': '{s} sekund penalty. {why}.',
        'penalty_dt': 'Drive through penalty. {why}. Odjeď ho do tří lapů.',
        'penalty_sg': 'Stop and go penalty. {why}.',
        'penalty_other': 'Penalty: {what}. {why}.',
        'blue_flag': 'Blue flag, pusť ho.',
        'yellow_ahead': 'Yellow flag před tebou. Opatrně.',
        'sc_deployed': 'Safety car, safety car. Drž delta kladnou.',
        'vsc_deployed': 'Virtual safety car. Drž delta kladnou.',
        'sc_in': 'Safety car jde tento lap do boxu. Připrav se.',
        'green': 'Green flag, green flag. Závod pokračuje.',
        'red_flag': 'Red flag, red flag. Zpomal a jeď do boxu.',
        'contact': 'Kontakt. Kontroluju damage.',
        'damage': '{part} damage {p} procent.',
        'damage_box_wing': 'Front wing je hodně poškozený. Box na nový nos.',
        'puncture': 'Defekt {wheel}! Box box.',
        'fault': '{part} fault.',
        'out_lap': 'Out lap. Zahřej gumy{battery}.',
        'out_lap_battery': ' a nabij battery',
        'tyre_temps': 'Tyre temps: přední {f}, zadní {r} stupňů. {hint}',
        'temps_ok': 'Dobré, v okně.',
        'temps_cold': 'Pořád studené, zahřívej.',
        'temps_hot': 'Moc horké, uber.',
        'traffic_close': 'Auto před tebou {g} na trati. Uber, udělej si místo.',
        'clear_air': 'Volná trať před tebou, {g}.',
        'push_now': 'Push now, push push.',
        'car_behind_push': 'Auto za tebou jede rychlé kolo, {g}. Nepřekážej.',
        'traffic_push': 'Pozor, auto před tebou {g}.',
        'provisional': 'Zatím P{pos}.',
        'time_left': 'Do konce session {m} minut.',
        'battery_quali': 'Battery {p} procent.',
        'setup_header': 'Setup návrh: {txt}',
        'debrief_ready': 'Debrief je připravený na obrazovce.',
        'no_setup': 'Na setup radu zatím nemám dost dat. Odjeď pár čistých lapů.',
    },
}
for _lang, _d in _EXT.items():
    T[_lang].update(_d)

PENALTY_TYPES = {0: 'Drive through', 1: 'Stop go', 2: 'Grid penalty', 4: 'Time penalty',
                 6: 'Disqualified', 9: 'Tyre regulations', 17: 'Black flag timer'}
INFRINGEMENTS = {
    0: 'Blocking by slow driving', 1: 'Wrong way driving', 3: 'Big collision', 4: 'Small collision',
    5: 'Collision, position not handed back', 6: 'Collision, positions not handed back',
    7: 'Corner cutting gained time', 8: 'Corner cutting overtake', 9: 'Corner cutting overtakes',
    10: 'Crossed pit exit line', 11: 'Ignoring blue flags', 12: 'Ignoring yellow flags',
    17: 'Pit lane speeding', 20: 'Too many penalties', 21: 'Multiple warnings',
    27: 'Running wide, gained time', 28: 'Running wide, gained time', 29: 'Running wide, gained time',
    34: 'Jump start', 36: 'Illegal overtake under safety car', 37: 'Exceeding safety car pace',
    38: 'Exceeding VSC pace', 52: 'Illegal time gain',
}
INFRINGEMENTS_CS = {
    'Blocking by slow driving': 'blokování pomalou jízdou', 'Wrong way driving': 'jízda v protisměru',
    'Big collision': 'velká kolize', 'Small collision': 'malá kolize',
    'Collision, position not handed back': 'kolize a nevrácená pozice',
    'Collision, positions not handed back': 'kolize a nevrácené pozice',
    'Corner cutting gained time': 'zkracování zatáčky se ziskem času',
    'Corner cutting overtake': 'předjetí mimo trať', 'Corner cutting overtakes': 'předjetí mimo trať',
    'Crossed pit exit line': 'přejetí čáry na výjezdu z boxů', 'Ignoring blue flags': 'ignorování modrých vlajek',
    'Ignoring yellow flags': 'ignorování žlutých vlajek', 'Pit lane speeding': 'rychlost v pit lane',
    'Too many penalties': 'příliš mnoho trestů', 'Multiple warnings': 'opakovaná varování',
    'Running wide, gained time': 'vyjetí z trati se ziskem času', 'Jump start': 'předčasný start',
    'Illegal overtake under safety car': 'předjetí za safety carem', 'Exceeding safety car pace': 'moc rychle za safety carem',
    'Exceeding VSC pace': 'moc rychle pod VSC', 'Illegal time gain': 'nedovolený zisk času',
}

DAMAGE_PARTS = {'fl_wing': 'Front left wing', 'fr_wing': 'Front right wing', 'rear_wing': 'Rear wing',
                'floor': 'Floor', 'diffuser': 'Diffuser', 'sidepod': 'Sidepod',
                'gearbox': 'Gearbox', 'engine': 'Engine'}


# ---------------------------------------------------------------- styl „AI race engineer“: start, pozice,
# povzbuzení, kvalifikační run debrief, poškození podle ztráty, nápověda, setup nabídka
_EXT2 = {
    'en': {
        'lights_out': 'Lights out, go go go! Stay calm into turn one.',
        'start_gain': 'Good start, P{pos}. You gained {n}.',
        'start_loss': 'P{pos} after lap one, lost {n}. Plenty of time, stay calm.',
        'start_same': 'P{pos} after lap one. Clean start.',
        'overtake_done': 'Nice move, P{pos} now.',
        'overtaken': 'Lost a place, P{pos}. Stay calm, we have the pace.',
        'last_lap': 'Last lap. Bring it home.',
        'finish': 'Chequered flag! P{pos}. {praise}',
        'praise_top': 'Fantastic drive!', 'praise_ok': 'Good job.',
        'encourage': 'Great pace, keep it up.',
        'push_again': 'Another push lap. Go.',
        'run_debrief': '{time}{pos}. {sectors}{corner}',
        'run_sector': 'S{n} {d}',
        'run_corner': ' Most time lost in {name}, {phase}.',
        'phase_braking': 'on braking', 'phase_apex': 'at the apex', 'phase_exit': 'on exit',
        'corner_phase': 'Losing {d} in {name}, mostly {phase}.',
        'damage_box_measured': 'Front wing costs {x} a lap, {laps} laps left. Box for a new nose.',
        'damage_stay_out': 'Front wing costs about {x} a lap. Not worth a stop, stay out.',
        'setup_offer': 'Five clean laps done. If you want to work on the setup, say Bono, setup.',
        'help': 'You can ask me: {q}.',
        'help_race': 'when do I box, gap behind, tyres, who is ahead',
        'help_quali': 'where am I losing time, sector times, tyre temps, battery',
        'help_other': 'where am I losing time, setup advice, target time, tyres',
    },
    'cs': {
        'lights_out': 'Zhasla světla, jedeš! V klidu do první zatáčky.',
        'start_gain': 'Dobrý start, P{pos}. Získal jsi {n}.',
        'start_loss': 'Po prvním kole P{pos}, ztratil jsi {n}. Času je dost, v klidu.',
        'start_same': 'Po prvním kole P{pos}. Čistý start.',
        'overtake_done': 'Pěkný manévr, jsi P{pos}.',
        'overtaken': 'Ztratil jsi pozici, jsi P{pos}. V klidu, tempo máme.',
        'last_lap': 'Poslední kolo. Dovez to domů.',
        'finish': 'Cíl! P{pos}. {praise}',
        'praise_top': 'Fantastická jízda!', 'praise_ok': 'Dobrá práce.',
        'encourage': 'Skvělé tempo, takhle dál.',
        'push_again': 'Další rychlé kolo. Jeď.',
        'run_debrief': '{time}{pos}. {sectors}{corner}',
        'run_sector': 'S{n} {d}',
        'run_corner': ' Nejvíc ztrácíš v {name}, {phase}.',
        'phase_braking': 'na brzdění', 'phase_apex': 've vrcholu zatáčky', 'phase_exit': 'na výjezdu',
        'corner_phase': 'V {name} ztrácíš {d}, hlavně {phase}.',
        'damage_box_measured': 'Křídlo tě stojí {x} na kolo a zbývá {laps} kol. Box na nový nos.',
        'damage_stay_out': 'Křídlo tě stojí asi {x} na kolo. Zastávka se nevyplatí, zůstaň venku.',
        'setup_offer': 'Máš pět čistých kol. Jestli chceš doladit setup, řekni Bono, setup.',
        'help': 'Můžeš se zeptat: {q}.',
        'help_race': 'kdy jedu do boxu, jaký je odstup za mnou, jak jsou na tom gumy, kdo je přede mnou',
        'help_quali': 'kde ztrácím čas, jaké mám sektory, teploty gum, baterie',
        'help_other': 'kde ztrácím čas, poraď se setupem, jaký je cílový čas, gumy',
    },
}
for _lang, _d in _EXT2.items():
    T[_lang].update(_d)

PHASE_OF_TIP = {'brake_early': 'braking', 'overdrive': 'braking', 'min_speed': 'apex',
                'gear': 'apex', 'throttle_late': 'exit', 'exit': 'exit'}


def corner_phase(item):
    tips = item.get('tips') or []
    return PHASE_OF_TIP.get(tips[0][0]) if tips else None
