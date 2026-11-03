"""Záznam kol: sběr vzorků podle vzdálenosti na kole, převzorkování, delta."""
import bisect

GRID_M = 5.0
FIELDS = ('t', 'speed', 'throttle', 'brake', 'steer', 'gear', 'x', 'z')


class LapTrace:
    """Kolo převzorkované na pevnou mřížku po GRID_M metrech."""

    def __init__(self, dist, cols):
        self.dist = dist
        self.cols = cols  # dict field -> list

    @property
    def lap_time(self):
        return self.cols['t'][-1] if self.dist else 0

    def value_at(self, field, d):
        dist = self.dist
        if not dist:
            return None
        col = self.cols[field]
        if d <= dist[0]:
            return col[0]
        if d >= dist[-1]:
            return col[-1]
        i = bisect.bisect_right(dist, d)
        d0, d1 = dist[i - 1], dist[i]
        f = (d - d0) / (d1 - d0) if d1 > d0 else 0
        return col[i - 1] + (col[i] - col[i - 1]) * f

    def time_at(self, d):
        return self.value_at('t', d)

    def index_at(self, d):
        return max(0, min(len(self.dist) - 1, int(round(d / GRID_M))))

    def to_dict(self):
        out = {'dist': [round(d, 1) for d in self.dist]}
        for k, v in self.cols.items():
            out[k] = [round(x, 2) for x in v]
        return out

    @classmethod
    def from_dict(cls, d):
        return cls(d['dist'], {k: d[k] for k in FIELDS if k in d})

    def downsample(self, step=4, fields=('speed', 'throttle', 'brake')):
        out = {'dist': self.dist[::step]}
        for f in fields:
            out[f] = [round(v, 2) for v in self.cols[f][::step]]
        return out


def resample(samples, track_length, lap_time_ms):
    """samples: seznam tuple (dist, t, speed, throttle, brake, steer, gear, x, z)
    seřazený podle dist. Vrátí LapTrace na mřížce 0..track_length."""
    if len(samples) < 10:
        return None
    end = track_length if track_length else samples[-1][0]
    # Přidej koncový bod: v cíli je čas = čas kola
    last = samples[-1]
    if lap_time_ms and end > last[0]:
        samples = samples + [(end, float(lap_time_ms)) + tuple(last[2:])]
    src_d = [s[0] for s in samples]
    n = int(end // GRID_M) + 1
    grid = [i * GRID_M for i in range(n)]
    if grid[-1] < end:
        grid.append(end)
    cols = {f: [] for f in FIELDS}
    j = 0
    for d in grid:
        while j < len(src_d) - 2 and src_d[j + 1] < d:
            j += 1
        a, b = samples[j], samples[j + 1]
        span = b[0] - a[0]
        f = (d - a[0]) / span if span > 0 else 0
        f = max(-1.0, min(f, 2.0))
        for k, name in enumerate(FIELDS, start=1):
            if name == 'gear':
                cols[name].append(a[k] if f < 0.5 else b[k])
            else:
                cols[name].append(a[k] + (b[k] - a[k]) * f)
    # čas na startu nesmí být záporný a musí být monotónní
    t = cols['t']
    for i in range(len(t)):
        if t[i] < 0:
            t[i] = 0.0
        if i and t[i] < t[i - 1]:
            t[i] = t[i - 1]
    if lap_time_ms:
        t[-1] = float(lap_time_ms)
    return LapTrace(grid, cols)


class CompletedLap:
    def __init__(self, car, lap_num, lap_ms, sectors, valid, clean, trace, meta=None):
        self.car = car
        self.lap_num = lap_num
        self.lap_ms = lap_ms
        self.sectors = sectors  # [s1, s2, s3] ms
        self.valid = valid
        self.clean = clean  # bez boxů, kompletní záznam
        self.trace = trace
        self.meta = meta or {}

    def summary(self):
        return {'lap': self.lap_num, 'time': self.lap_ms, 'sectors': self.sectors,
                'valid': self.valid, 'clean': self.clean, **self.meta}


class CarLapRecorder:
    """Sbírá vzorky jednoho auta a při přejetí cílové čáry vrátí CompletedLap."""

    def __init__(self, car):
        self.car = car
        self.reset()

    def reset(self):
        self.lap_num = None
        self.samples = []
        self.invalid = False
        self.pitted = False
        self.s1 = 0
        self.s2 = 0
        self.started_at_line = False

    def update(self, lap, tel, mot, track_length):
        """lap: dict z LapData; tel/mot: poslední telemetrie/pohyb (nebo None)."""
        done = None
        lap_num = lap['lap_num']
        d = lap['lap_distance']
        if self.lap_num is None:
            self.lap_num = lap_num
        if lap_num != self.lap_num:
            if lap_num == self.lap_num + 1:
                done = self._finish(lap['last_lap_ms'], track_length)
            self.lap_num = lap_num
            self.samples = []
            self.invalid = False
            self.pitted = False
            self.s1 = self.s2 = 0
            self.started_at_line = False
        if lap['invalid']:
            self.invalid = True
        if lap['pit_status']:
            self.pitted = True
        if lap['s1_ms']:
            self.s1 = lap['s1_ms']
        if lap['s2_ms']:
            self.s2 = lap['s2_ms']
        if d < 0:
            return done
        if not self.samples:
            self.started_at_line = d < 60
        elif d < self.samples[-1][0] - 20:
            # flashback / restart: zahoď vzorky za aktuální pozicí
            while self.samples and self.samples[-1][0] >= d:
                self.samples.pop()
            if not self.samples:
                self.started_at_line = d < 60
        if self.samples and d <= self.samples[-1][0] + 0.5:
            return done
        t = float(lap['current_lap_ms'])
        if tel:
            row = (d, t, float(tel['speed']), tel['throttle'], tel['brake'],
                   tel['steer'], tel['gear'])
        else:
            row = (d, t, 0.0, 0.0, 0.0, 0.0, 0)
        if mot:
            row += (mot['x'], mot['z'])
        else:
            row += (0.0, 0.0)
        self.samples.append(row)
        return done

    def _finish(self, lap_ms, track_length):
        samples = self.samples
        if not lap_ms:
            return None
        complete = (self.started_at_line and samples and
                    (not track_length or samples[-1][0] > track_length - 150) and
                    len(samples) > 50)
        trace = resample(samples, track_length, lap_ms) if complete else None
        s1, s2 = self.s1, self.s2
        s3 = lap_ms - s1 - s2 if s1 and s2 else 0
        return CompletedLap(self.car, self.lap_num, lap_ms, [s1, s2, s3],
                            valid=not self.invalid,
                            clean=bool(trace) and not self.pitted,
                            trace=trace, meta={'pitted': self.pitted})

    def live_progress(self):
        if not self.samples:
            return None
        return self.samples[-1]
