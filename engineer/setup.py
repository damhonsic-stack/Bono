"""Analýza vyvážení auta a návrhy setupu.

Z paketu Motion Ex (jen hráč) bereme úhly skluzu kol. Poměr průměrného skluzu
předních a zadních kol říká, jestli auto v zatáčce nedotáčí (přední kola kloužou víc
→ understeer) nebo přetáčí (zadní víc → oversteer). Dělíme podle fáze zatáčky
(entry = brzdění, mid, exit = plyn) a rychlosti (slow / medium / fast).

Je to odhad z telemetrie, ne přesná věda – rady jsou formulované jako "zkus".
"""
import math

PHASES = ('entry', 'mid', 'exit')
SPEEDS = ('slow', 'medium', 'fast')
UNDER, OVER = 1.25, 0.80       # hranice poměru front/rear skluzu
MIN_SAMPLES = 40


def _speed_class(kmh):
    return 'slow' if kmh < 130 else ('medium' if kmh < 210 else 'fast')


class SetupAnalyzer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.buckets = {(p, s): [0.0, 0.0, 0] for p in PHASES for s in SPEEDS}  # front, rear, n
        self.lockups = {'front': 0, 'rear': 0}
        self.wheelspin = 0
        self.temp_sum = [0.0] * 4
        self.temp_n = 0
        self.setup = None
        self._lock_state = {'front': False, 'rear': False}
        self._spin_state = False

    def on_setup(self, setup):
        self.setup = setup

    def on_sample(self, mex, tel, lap):
        """mex: Motion Ex, tel: telemetrie hráče, lap: Lap Data hráče."""
        if not mex or not tel or not lap or lap['pit_status'] or lap['driver_status'] == 0:
            return
        kmh = tel['speed']
        if kmh < 50:
            return
        sa = [abs(math.degrees(a)) for a in mex['slip_angle']]  # RL, RR, FL, FR
        sr = mex['slip_ratio']
        front, rear = (sa[2] + sa[3]) / 2, (sa[0] + sa[1]) / 2
        # zamykání kol při brzdění, protáčení při plynu (s hysterezí = počítáme události)
        if tel['brake'] > 0.3:
            for axle, idx in (('front', (2, 3)), ('rear', (0, 1))):
                locked = min(sr[idx[0]], sr[idx[1]]) < -0.2
                if locked and not self._lock_state[axle]:
                    self.lockups[axle] += 1
                self._lock_state[axle] = locked
        else:
            self._lock_state = {'front': False, 'rear': False}
        spin = tel['throttle'] > 0.5 and max(sr[0], sr[1]) > 0.15 and kmh < 200
        if spin and not self._spin_state:
            self.wheelspin += 1
        self._spin_state = spin
        if abs(tel['steer']) < 0.06 or front + rear < 1.0:
            return  # rovinka nebo minimální zatížení v zatáčce
        if tel['brake'] > 0.2:
            phase = 'entry'
        elif tel['throttle'] > 0.5:
            phase = 'exit'
        else:
            phase = 'mid'
        b = self.buckets[(phase, _speed_class(kmh))]
        b[0] += front
        b[1] += rear
        b[2] += 1
        s = tel['tyre_surface']
        for i in range(4):
            self.temp_sum[i] += s[i]
        self.temp_n += 1

    def balance(self):
        out = {}
        for (p, s), (f, r, n) in self.buckets.items():
            if n < MIN_SAMPLES or r <= 0:
                continue
            ratio = f / r
            state = 'under' if ratio > UNDER else ('over' if ratio < OVER else 'neutral')
            out['%s_%s' % (p, s)] = {'ratio': round(ratio, 2), 'state': state, 'n': n}
        return out

    def advice(self):
        """Seznam doporučení [{'issue', 'change', 'why'}]."""
        bal = self.balance()
        st = self.setup or {}
        tips = []

        def cur(key, delta, unit=''):
            if key in st:
                return '%s %s → %s%s' % (key.replace('_', ' '), st[key], st[key] + delta, unit)
            return None

        def add(issue, change, current=None):
            if not any(t['issue'] == issue for t in tips):
                tips.append({'issue': issue, 'change': change, 'current': current})

        def has(phase, speeds, state):
            return [s for s in speeds if bal.get('%s_%s' % (phase, s), {}).get('state') == state]

        if has('mid', ('fast',), 'under'):
            add('High-speed understeer', 'Front wing +1', cur('front_wing', 1))
        if has('mid', ('fast',), 'over'):
            add('High-speed oversteer', 'Rear wing +1 (or front wing -1)', cur('rear_wing', 1))
        if has('mid', ('slow', 'medium'), 'under'):
            add('Low/medium-speed understeer', 'Front anti-roll bar -1 (softer front)', cur('front_arb', -1))
        if has('mid', ('slow', 'medium'), 'over'):
            add('Low/medium-speed oversteer', 'Rear anti-roll bar -1 (softer rear)', cur('rear_arb', -1))
        if has('entry', SPEEDS, 'under'):
            add('Understeer on corner entry', 'Brake bias -1 % and off-throttle diff -5 %',
                cur('brake_bias', -1, ' %'))
        if has('entry', SPEEDS, 'over'):
            add('Oversteer on corner entry', 'Brake bias +1 % and off-throttle diff +5 %',
                cur('brake_bias', 1, ' %'))
        if has('exit', ('slow', 'medium'), 'over') or self.wheelspin >= 8:
            add('Oversteer / wheelspin on exit', 'On-throttle diff -5 % (more open), smoother throttle',
                cur('on_throttle', -5, ' %'))
        if has('exit', SPEEDS, 'under'):
            add('Understeer on exit', 'On-throttle diff +5 %', cur('on_throttle', 5, ' %'))
        if self.lockups['front'] >= 5 and self.lockups['front'] > self.lockups['rear']:
            add('Front lock-ups (%d)' % self.lockups['front'], 'Brake bias -1 % or brake pressure -2 %',
                cur('brake_bias', -1, ' %'))
        if self.lockups['rear'] >= 5 and self.lockups['rear'] > self.lockups['front']:
            add('Rear lock-ups (%d)' % self.lockups['rear'], 'Brake bias +1 %', cur('brake_bias', 1, ' %'))
        if self.temp_n > 200:
            t = [x / self.temp_n for x in self.temp_sum]
            front, rear = (t[2] + t[3]) / 2, (t[0] + t[1]) / 2
            if rear - front > 8:
                add('Rears running %d° hotter than fronts' % (rear - front),
                    'Lower rear tyre pressures slightly or be gentler on traction')
            elif front - rear > 8:
                add('Fronts running %d° hotter than rears' % (front - rear),
                    'Lower front tyre pressures slightly, reduce front wing if understeering')
        return tips

    def summary(self):
        t = [round(x / self.temp_n) for x in self.temp_sum] if self.temp_n else None
        return {'balance': self.balance(), 'lockups': self.lockups, 'wheelspin': self.wheelspin,
                'avg_surface_temps': dict(zip(['RL', 'RR', 'FL', 'FR'], t)) if t else None,
                'setup': self.setup, 'advice': self.advice()}
