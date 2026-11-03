"""Závodní přehled: palivo, gumy, mezery a jejich trend."""
from .constants import WHEELS, VISUAL_COMPOUND, ACTUAL_COMPOUND


def _trend(history, n=3):
    """Průměrná změna hodnoty za kolo z posledních n+1 bodů."""
    if len(history) < 2:
        return None
    h = history[-(n + 1):]
    return (h[-1] - h[0]) / (len(h) - 1)


class RaceTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.fuel_at_lap_start = {}   # lap_num -> kg
        self.fuel_burn = []           # kg/kolo
        self.wear_at_lap = {}         # lap_num -> max wear
        self.gap_ahead = []           # ms na konci každého kola
        self.gap_behind = []
        self.lap_times = []
        self.last_lap_num = None

    def on_new_lap(self, lap_num, status, damage, gap_ahead_ms, gap_behind_ms, last_lap_ms):
        """Zavolá se při přejetí cílové čáry hráčem."""
        if status:
            fuel = status['fuel_in_tank']
            prev = self.fuel_at_lap_start.get(lap_num - 1)
            if prev is not None and prev - fuel > 0.05:
                self.fuel_burn.append(prev - fuel)
            self.fuel_at_lap_start[lap_num] = fuel
        if damage:
            self.wear_at_lap[lap_num] = max(damage['tyre_wear'])
        if gap_ahead_ms is not None:
            self.gap_ahead.append(gap_ahead_ms)
        if gap_behind_ms is not None:
            self.gap_behind.append(gap_behind_ms)
        if last_lap_ms:
            self.lap_times.append(last_lap_ms)
        self.last_lap_num = lap_num

    def fuel(self, status, current_lap, total_laps, lap_distance, track_length):
        if not status:
            return None
        out = {
            'kg': round(status['fuel_in_tank'], 2),
            'game_delta_laps': round(status['fuel_remaining_laps'], 2),
            'mix': status['fuel_mix'],
        }
        if self.fuel_burn:
            recent = self.fuel_burn[-3:]
            burn = sum(recent) / len(recent)
            out['burn_per_lap'] = round(burn, 3)
            if total_laps and track_length:
                frac = max(0.0, min(1.0, lap_distance / track_length))
                laps_left = max(0.0, total_laps - current_lap + 1 - frac)
                need = burn * laps_left
                out['laps_left'] = round(laps_left, 1)
                out['own_delta_laps'] = round((status['fuel_in_tank'] - need) / burn, 2)
        return out

    def tyres(self, status, damage, telemetry):
        if not status:
            return None
        out = {
            'compound': VISUAL_COMPOUND.get(status['visual_compound'], '?'),
            'actual': ACTUAL_COMPOUND.get(status['actual_compound'], '?'),
            'age': status['tyre_age'],
        }
        if damage:
            out['wear'] = dict(zip(WHEELS, damage['tyre_wear']))
            out['max_wear'] = max(damage['tyre_wear'])
            laps = sorted(self.wear_at_lap)
            if len(laps) >= 2:
                a, b = laps[max(0, len(laps) - 4)], laps[-1]
                if b > a:
                    rate = (self.wear_at_lap[b] - self.wear_at_lap[a]) / (b - a)
                    if rate > 0.01:
                        out['wear_per_lap'] = round(rate, 2)
                        out['laps_to_70'] = max(0, round((70 - out['max_wear']) / rate, 1))
        if telemetry:
            out['surface'] = dict(zip(WHEELS, telemetry['tyre_surface']))
            out['inner'] = dict(zip(WHEELS, telemetry['tyre_inner']))
            out['pressure'] = dict(zip(WHEELS, telemetry['tyre_pressure']))
        return out

    def gaps(self, gap_ahead_now, gap_behind_now):
        out = {'ahead': gap_ahead_now, 'behind': gap_behind_now}
        ta = _trend(self.gap_ahead)
        tb = _trend(self.gap_behind)
        if ta is not None:
            out['ahead_trend'] = round(ta)  # záporné = stahuji
            if ta < -50 and gap_ahead_now:
                out['catch_in_laps'] = round(gap_ahead_now / -ta, 1)
        if tb is not None:
            out['behind_trend'] = round(tb)  # záporné = dojíždí mě
        return out

    def pace(self):
        lt = [t for t in self.lap_times if t]
        if len(lt) < 2:
            return None
        last3 = lt[-3:]
        return {'last': lt[-1], 'avg3': round(sum(last3) / len(last3)),
                'trend': round(lt[-1] - lt[-2])}
