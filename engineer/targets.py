"""Cílové časy podle obtížnosti AI a samokalibrace z reálných časů AI."""
from .constants import POLE_BASELINE, AI_PCT_PER_POINT


def factor(difficulty):
    return 1.0 + AI_PCT_PER_POINT * (100 - difficulty)


class Targets:
    """calibration: {track_id(str): {'base100_ms': float, 'samples': int}}"""

    def __init__(self, calibration):
        self.cal = calibration

    def base100(self, track_id):
        c = self.cal.get(str(track_id))
        if c and c.get('base100_ms'):
            return c['base100_ms'], 'calibrated (%d×)' % c.get('samples', 1)
        s = POLE_BASELINE.get(track_id)
        if s:
            return s * 1000.0, 'estimate'
        return None, None

    def target_lap(self, track_id, difficulty):
        base, src = self.base100(track_id)
        if base is None:
            return None, None
        return base * factor(difficulty), src

    def matching_difficulty(self, track_id, lap_ms):
        """Jaké obtížnosti AI odpovídá daný čas kola."""
        base, _ = self.base100(track_id)
        if not base or not lap_ms:
            return None
        d = 100 - (lap_ms / base - 1.0) / AI_PCT_PER_POINT
        return max(0, min(110, round(d)))

    def calibrate(self, track_id, difficulty, ai_best_ms):
        """Zapíše pozorovaný nejlepší čas AI (kvalifikace/trénink, sucho)."""
        if not ai_best_ms or difficulty is None:
            return False
        implied = ai_best_ms / factor(difficulty)
        key = str(track_id)
        c = self.cal.get(key)
        if not c:
            self.cal[key] = {'base100_ms': implied, 'samples': 1}
        else:
            n = min(c.get('samples', 1), 9)
            # klouzavý průměr, novější data mají váhu
            c['base100_ms'] = (c['base100_ms'] * n + implied) / (n + 1)
            c['samples'] = c.get('samples', 1) + 1
        return True


def split_sectors(target_ms, ref_sectors):
    """Rozdělí cílový čas do sektorů podle poměru referenčních sektorů."""
    if not target_ms or not ref_sectors or not all(ref_sectors):
        return None
    tot = float(sum(ref_sectors))
    return [round(target_ms * s / tot) for s in ref_sectors]
