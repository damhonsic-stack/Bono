"""Soupeři: gumy, zastávky, tempo a jejich vývoj. Sbírá i data pro odhad pit loss."""
from .constants import VISUAL_COMPOUND


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


class CarInfo:
    def __init__(self, idx):
        self.idx = idx
        self.lap_num = None
        self.laps = []            # [(lap_num, ms, pit_flag)]
        self.in_pit_this_lap = False
        self.pit_stops = 0
        self.pending_pit = False  # zastávka zjištěná, čeká se na výjezd a směs
        self.compound = None
        self.age = None

    def clean_laps(self, n=3):
        out = [ms for (_, ms, pit) in self.laps if not pit and ms]
        return out[-n:]

    def pace(self, n=3):
        c = self.clean_laps(n)
        return sum(c) / len(c) if len(c) >= 2 else None


class Opponents:
    def __init__(self):
        self.reset()

    def reset(self):
        self.cars = {}
        self.events = []
        self.pit_losses = []      # naměřené ztráty zastávky (ms)
        self.announced = {}       # (key, car) -> lap

    def car(self, i):
        if i not in self.cars:
            self.cars[i] = CarInfo(i)
        return self.cars[i]

    def pop_events(self):
        ev, self.events = self.events, []
        return ev

    def update(self, laps, statuses, player):
        """Volá se s každým paketem Lap Data."""
        for i, l in enumerate(laps):
            if not l or l['result_status'] not in (2, 3):
                continue
            c = self.car(i)
            st = statuses[i] if i < len(statuses) else None
            if st:
                c.compound = st['visual_compound']
                c.age = st['tyre_age']
            if l['pit_status']:
                c.in_pit_this_lap = True
            if c.lap_num is not None and l['lap_num'] == c.lap_num + 1 and l['last_lap_ms']:
                c.laps.append((c.lap_num, l['last_lap_ms'], c.in_pit_this_lap))
                c.laps = c.laps[-60:]
                self._measure_pit_loss(c)
                c.in_pit_this_lap = bool(l['pit_status'])
            c.lap_num = l['lap_num']
            if l['num_pit_stops'] > c.pit_stops:
                c.pit_stops = l['num_pit_stops']
                if i != player:
                    c.pending_pit = True
            if c.pending_pit and not l['pit_status'] and st:
                c.pending_pit = False
                self.events.append(('pitted', {'car': i, 'compound': st['visual_compound']}))

    def _measure_pit_loss(self, c):
        """Ztráta zastávky = (in lap + out lap) − 2 × medián čistých kol."""
        laps = c.laps
        if len(laps) < 4:
            return
        # poslední dvě kola s pit příznakem, kterým předcházejí čistá kola
        if laps[-1][2] and laps[-2][2]:
            base = _median([ms for (_, ms, pit) in laps[:-2] if not pit][-5:])
            if base:
                loss = laps[-1][1] + laps[-2][1] - 2 * base
                if 8000 < loss < 45000:
                    self.pit_losses.append(loss)

    def pit_loss(self, default=22000):
        m = _median(self.pit_losses[-8:])
        return m if m else default

    def around(self, laps, player, names, n=2):
        """Auta P-n .. P+n kolem hráče."""
        me = laps[player] if player < len(laps) else None
        if not me:
            return []
        pos = me['position']
        mine = self.cars.get(player)
        my_pace = mine.pace() if mine else None
        out = []
        for i, l in enumerate(laps):
            if not l or l['result_status'] != 2 or abs(l['position'] - pos) > n:
                continue
            c = self.car(i)
            gap = l['delta_leader_ms'] - me['delta_leader_ms']
            pace = c.pace()
            out.append({
                'idx': i, 'pos': l['position'], 'name': names.get(i, 'Car %d' % (i + 1)),
                'me': i == player, 'gap': gap if i != player else 0,
                'tyre': VISUAL_COMPOUND.get(c.compound, '?'), 'age': c.age,
                'pits': l['num_pit_stops'], 'last': c.laps[-1][1] if c.laps else None,
                'pace_delta': round(pace - my_pace) if pace and my_pace and i != player else None,
                'in_pit': bool(l['pit_status']),
            })
        out.sort(key=lambda x: x['pos'])
        return out

    def alerts(self, laps, player, names, lap_num):
        """Varování: rychlejší auto za mnou na čerstvých gumách, pomalé auto přede mnou."""
        me = laps[player] if player < len(laps) else None
        mine = self.cars.get(player)
        if not me or not mine or mine.pace() is None:
            return
        my_pace = mine.pace()
        for i, l in enumerate(laps):
            if not l or i == player or l['result_status'] != 2:
                continue
            c = self.cars.get(i)
            if not c or c.pace() is None or c.age is None or mine.age is None:
                continue
            gap = abs(l['delta_leader_ms'] - me['delta_leader_ms'])
            diff = my_pace - c.pace()  # kladné = on je rychlejší
            if l['position'] == me['position'] + 1 and gap < 4000 and diff > 300 and \
                    c.age < mine.age - 4 and self._once('behind_fresh', i, lap_num, 5):
                self.events.append(('behind_fresh', {
                    'car': i, 'x': diff, 'n': max(1, round(gap / diff)), 'compound': c.compound}))
            if l['position'] == me['position'] - 1 and gap < 4000 and -diff > 300 and \
                    c.age > mine.age + 4 and self._once('ahead_old', i, lap_num, 5):
                self.events.append(('ahead_old', {'car': i, 'x': -diff, 'age': c.age,
                                                  'compound': c.compound}))

    def _once(self, key, car, lap_num, every):
        last = self.announced.get((key, car))
        if last is not None and lap_num - last < every:
            return False
        self.announced[(key, car)] = lap_num
        return True
