"""Strategie: tyre degradation, pit loss, plán zastávek, undercut, safety car a počasí.

Model času (relativně k aktuálnímu tempu na nasazených gumách):
  - pokračování na aktuální sadě:  deg_cur × i za i-tý lap (+ cliff za koncem životnosti)
  - nová sada směsi c:             offset_c + deg_c × j   (offset_c = lap delta nové sady vůči
                                    nasazené, ideálně přímo ze hry z paketu Tyre Sets)
  - zastávka:                      + pit loss (naměřený z reálných zastávek aut v session)
"""
from .constants import VISUAL_COMPOUND, RACE

SLICKS = (16, 17, 18)
DEFAULT_DEG = {16: 110.0, 17: 70.0, 18: 45.0, 7: 60.0, 8: 60.0}        # ms za lap stáří
DEFAULT_LIFE = {16: 16, 17: 26, 18: 36, 7: 30, 8: 30}                  # lapů
COMPOUND_PACE = {16: -450.0, 17: 0.0, 18: 450.0, 7: 0.0, 8: 0.0}       # ms vůči Medium
FUEL_MS_PER_KG = 30.0
CLIFF_MS = 1500.0
OUTLAP_WARMUP_MS = 700.0


def tyre_name(c):
    return VISUAL_COMPOUND.get(c, 'new')


def _stint_cost(n, start_age, deg, life_left):
    """Součet ztrát za n lapů na sadě se stářím start_age (ms)."""
    if n <= 0:
        return 0.0
    cost = deg * (n * start_age + n * (n - 1) / 2.0)
    if life_left is not None and n > life_left:
        cost += (n - max(0, life_left)) * CLIFF_MS
    return cost


def _slope(points):
    """Lineární regrese (x=stáří, y=čas) → ms za lap. None při málo datech."""
    if len(points) < 3:
        return None
    n = float(len(points))
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    den = n * sxx - sx * sx
    if den == 0:
        return None
    return (n * sxy - sx * sy) / den


class Strategy:
    def __init__(self):
        self.reset()

    def reset(self):
        self.stints = []            # [{'compound', 'start_lap', 'points': [(age, ms)]}]
        self.used_compounds = set()
        self.last_plan = None
        self.called_box_lap = None
        self.called_next_lap = None
        self.window_called = False
        self.plan_announced_lap = None
        self.undercut_called = {}
        self.rain_called_at = None
        self.wet_called = False
        self.dry_called = False
        self.sc_called = False
        self.committed = None       # (laps, compounds) ukotvený plán blízké zastávky

    # ------------------------------------------------------------ data z kol
    def on_player_lap(self, lap_num, lap_ms, valid, pitted, fuel_kg, compound, age, neutralized):
        if compound is None:
            return
        self.used_compounds.add(compound)
        last = self.stints[-1] if self.stints else None
        if not last or last['compound'] != compound or \
                (age is not None and last.get('age') is not None and age < last['age']):
            if last:   # nový stint po zastávce → nová volání a nový plán
                self.called_box_lap = self.called_next_lap = None
                self.committed = None
                self.sc_called = False
            self.stints.append({'compound': compound, 'start_lap': lap_num, 'points': []})
        self.stints[-1]['age'] = age
        if valid and not pitted and not neutralized and lap_ms and age is not None and lap_num > 1:
            corrected = lap_ms - FUEL_MS_PER_KG * (fuel_kg or 0.0)
            pts = self.stints[-1]['points']
            # odfiltruj výrazné odchylky (chyba, provoz) – víc než 2 s od mediánu
            if pts:
                med = sorted(p[1] for p in pts)[len(pts) // 2]
                if abs(corrected - med) > 2000:
                    return
            pts.append((age, corrected))

    def deg(self, compound):
        """Degradace v ms/lap: z aktuálního stintu, jinak z dřívějšího stintu, jinak výchozí."""
        for st in reversed(self.stints):
            if st['compound'] == compound:
                s = _slope(st['points'])
                if s is not None:
                    return max(5.0, min(400.0, s)), 'measured'
        cur = self.stints[-1] if self.stints else None
        if cur:
            s = _slope(cur['points'])
            if s is not None and cur['compound'] in DEFAULT_DEG and compound in DEFAULT_DEG:
                scale = DEFAULT_DEG[compound] / DEFAULT_DEG[cur['compound']]
                return max(5.0, min(400.0, s * scale)), 'scaled'
        return DEFAULT_DEG.get(compound, 70.0), 'default'

    # ------------------------------------------------------------ plán
    def options(self, tyre_sets, current, wet):
        """Dostupné sady pro další stinty: {compound: {'offset', 'life'}}."""
        allowed = (7, 8) if wet else SLICKS
        out = {}
        if tyre_sets:
            for s in tyre_sets:
                if not s['available'] or s['fitted'] or s['visual'] not in allowed:
                    continue
                best = out.get(s['visual'])
                if best is None or s['wear'] < best['wear']:
                    out[s['visual']] = {'offset': float(s['lap_delta']), 'life': s['life_left'],
                                        'wear': s['wear']}
        if not out:
            cur_deg = self.deg(current['compound'])[0] if current else 70.0
            age = current['age'] if current else 0
            base = COMPOUND_PACE.get(current['compound'], 0.0) if current else 0.0
            for c in allowed:
                out[c] = {'offset': COMPOUND_PACE[c] - base - cur_deg * age,
                          'life': DEFAULT_LIFE[c], 'wear': 0}
        return out

    def plan(self, current_lap, total_laps, current, tyre_sets, pit_loss, wet, must_two):
        """current: {'compound', 'age', 'life_left'}. Vrací nejlepší plán nebo None."""
        if not total_laps or not current or current_lap > total_laps:
            return None
        R = total_laps - current_lap + 1           # lapy, které ještě pojedu (včetně aktuálního)
        if R < 1:
            return None
        d_cur = self.deg(current['compound'])[0]
        life_cur = current.get('life_left')
        opts = self.options(tyre_sets, current, wet)
        used = set(c for c in self.used_compounds if c in SLICKS)

        def rule_ok(seq):
            if not must_two or wet:
                return True
            return len(used | set(c for c in seq if c in SLICKS)) >= 2

        plans = []
        # 0 zastávek
        if rule_ok([]):
            plans.append((_stint_cost(R, 0, d_cur, life_cur), [], []))
        # 1 zastávka: pit na konci lapu k (k = current_lap .. total_laps-1)
        for c, o in opts.items():
            d_c = self.deg(c)[0]
            if not rule_ok([c]):
                continue
            for k in range(current_lap, total_laps):
                n1 = k - current_lap + 1
                n2 = total_laps - k
                cost = (_stint_cost(n1, 0, d_cur, life_cur) + pit_loss +
                        n2 * o['offset'] + _stint_cost(n2, 0, d_c, o['life']))
                plans.append((cost, [k], [c]))
        # 2 zastávky
        if R >= 6:
            for c1, o1 in opts.items():
                for c2, o2 in opts.items():
                    if not rule_ok([c1, c2]):
                        continue
                    d1, d2 = self.deg(c1)[0], self.deg(c2)[0]
                    # druhá sada stejné směsi: offset bez rozdílu směsi (už stejná)
                    off2 = o2['offset']
                    for k1 in range(current_lap, total_laps - 1):
                        n1 = k1 - current_lap + 1
                        base = _stint_cost(n1, 0, d_cur, life_cur) + 2 * pit_loss
                        for k2 in range(k1 + 1, total_laps):
                            n2, n3 = k2 - k1, total_laps - k2
                            cost = (base + n2 * o1['offset'] + _stint_cost(n2, 0, d1, o1['life']) +
                                    n3 * off2 + _stint_cost(n3, 0, d2, o2['life']))
                            plans.append((cost, [k1, k2], [c1, c2]))
        if not plans:
            return None
        plans.sort(key=lambda p: p[0])
        best = plans[0]
        # ukotvení: blízkou naplánovanou zastávku neměň, pokud nový plán není o >1,5 s lepší
        c = self.committed
        if c and c[0] and c[0][0] >= current_lap:
            for p in plans:
                if tuple(p[1]) == c[0] and tuple(p[2]) == c[1]:
                    if p[0] <= best[0] + 1500:
                        best = p
                    break
        if best[1] and best[1][0] - current_lap <= 2:
            self.committed = (tuple(best[1]), tuple(best[2]))
        elif not best[1]:
            self.committed = None
        stops = len(best[1])
        alt = next((p for p in plans if len(p[1]) != stops), None)
        # okno pro první zastávku: lapy, kde je stejný počet zastávek do +1 s od optima
        window = None
        if stops:
            ks = [p[1][0] for p in plans if len(p[1]) == stops and p[2][0] == best[2][0] and
                  p[0] <= best[0] + 1000]
            if ks:
                window = [min(ks), max(ks)]
        res = {
            'stops': stops, 'laps': best[1], 'compounds': best[2],
            'tyres': [tyre_name(c) for c in best[2]],
            'cost_ms': round(best[0]), 'window': window,
            'deg_ms': round(d_cur), 'deg_src': self.deg(current['compound'])[1],
            'pit_loss_ms': round(pit_loss), 'remaining': R,
        }
        if alt:
            res['alt'] = {'stops': len(alt[1]), 'laps': alt[1], 'tyres': [tyre_name(c) for c in alt[2]],
                          'delta_ms': round(alt[0] - best[0])}
        self.last_plan = res
        return res

    # ------------------------------------------------------------ rejoin
    @staticmethod
    def rejoin(laps, player, pit_loss, names):
        me = laps[player] if player < len(laps) else None
        if not me:
            return None
        t = me['delta_leader_ms'] + pit_loss
        ahead = behind = None
        pos = 1
        for i, l in enumerate(laps):
            if not l or i == player or l['result_status'] != 2:
                continue
            g = l['delta_leader_ms']
            if g < t:
                pos += 1
                if ahead is None or g > ahead[1]:
                    ahead = (i, g)
            elif behind is None or g < behind[1]:
                behind = (i, g)
        out = {'pos': pos}
        if ahead:
            out['ahead'] = {'name': names.get(ahead[0], '?'), 'gap': round(t - ahead[1])}
        if behind:
            out['behind'] = {'name': names.get(behind[0], '?'), 'gap': round(behind[1] - t)}
        return out

    # ------------------------------------------------------------ hlášení
    def lap_calls(self, current_lap, plan, session):
        """Volá se na začátku každého lapu hráče. Vrací [(key, kwargs, urgent)]."""
        out = []
        if not plan:
            return out
        recently = self.called_box_lap is not None and current_lap - self.called_box_lap < 3
        if plan['stops'] and plan['laps'][0] <= current_lap and not recently:
            self.called_box_lap = current_lap
            out.append(('box_this_lap', {'tyre': plan['tyres'][0]}, True))
        elif plan['stops'] and plan['laps'][0] == current_lap + 1 and \
                self.called_next_lap is None and not recently:
            self.called_next_lap = current_lap
            out.append(('box_next_lap', {'tyre': plan['tyres'][0]}, False))
        ideal = session.get('pit_ideal_lap')
        if ideal and not self.window_called and current_lap == max(1, ideal - 2):
            self.window_called = True
            out.append(('pit_window', {'ideal': ideal, 'latest': session.get('pit_latest_lap')}, False))
        if self.plan_announced_lap is None or current_lap - self.plan_announced_lap >= 8:
            self.plan_announced_lap = current_lap
            out.append(('plan', {}, False))
        return out

    def safety_car_call(self, kind, plan, current_lap, max_wear):
        if not plan or not plan['stops'] or self.sc_called:
            return None
        if plan['remaining'] <= 3:
            return None
        if plan['laps'][0] - current_lap <= 12 or (max_wear or 0) >= 35:
            self.sc_called = True
            return ('sc_box' if kind == 'sc' else 'vsc_box', {'tyre': plan['tyres'][0]}, True)
        return None

    def undercut_call(self, plan, gap_ahead, ahead_idx, ahead_age, my_age, current_lap, opts):
        if not plan or not plan['stops'] or gap_ahead is None or ahead_idx is None:
            return None
        if ahead_age is None or my_age is None or ahead_age < my_age:
            return None
        w = plan.get('window') or plan['laps']
        if current_lap < w[0] - 2:
            return None
        o = opts.get(plan['compounds'][0])
        if not o:
            return None
        gain = -o['offset'] - OUTLAP_WARMUP_MS
        if gain <= 300 or gap_ahead > gain * 1.5:
            return None
        last = self.undercut_called.get(ahead_idx)
        if last is not None and current_lap - last < 5:
            return None
        self.undercut_called[ahead_idx] = current_lap
        return ('undercut_on', {'car': ahead_idx, 'x': gain, 'g': gap_ahead}, False)

    def weather_calls(self, session, compound):
        out = []
        w = session.get('weather', 0)
        now = session.get('time_left')
        fc = sorted(session.get('forecast') or [], key=lambda f: f['offset_min'])
        if w < 3:
            for f in fc:
                if 0 < f['offset_min'] <= 15 and (f['weather'] >= 3 or f['rain_pct'] >= 50):
                    if self.rain_called_at is None or (now is not None and
                                                       self.rain_called_at - now > 600):
                        self.rain_called_at = now if now is not None else 0
                        out.append(('rain_coming', {'m': f['offset_min'], 'p': f['rain_pct']}, False))
                    break
            self.wet_called = False
        if w >= 3 and compound in SLICKS and not self.wet_called:
            self.wet_called = True
            out.append(('rain_now_slicks', {'tyre': 'Wet' if w >= 4 else 'Intermediate'}, True))
        if w <= 1 and compound in (7, 8):
            soon_rain = any(0 < f['offset_min'] <= 10 and f['weather'] >= 3 for f in fc)
            if not soon_rain and not self.dry_called:
                self.dry_called = True
                out.append(('drying', {}, False))
        else:
            self.dry_called = self.dry_called and compound in (7, 8)
        return out


def is_race(session):
    return session.get('session_type') in RACE
