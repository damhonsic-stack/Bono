"""Automatická detekce zatáček z referenčního kola a srovnání kol po zatáčkách."""
from .laps import GRID_M


def _smooth(vals, w=3):
    n = len(vals)
    out = []
    for i in range(n):
        a, b = max(0, i - w), min(n, i + w + 1)
        out.append(sum(vals[a:b]) / (b - a))
    return out


def detect_corners(trace, min_drop_kmh=12.0, merge_m=120.0):
    """Najde zatáčky jako lokální minima rychlosti s dostatečným poklesem.

    Vrátí seznam segmentů, které dohromady pokrývají celé kolo:
    [{'id', 'name', 'start', 'apex', 'end', 'x', 'z'}]. Každý segment = brzdění,
    vrchol, výjezd a rovinka až k dalšímu brzdění.
    """
    sp = _smooth(trace.cols['speed'])
    n = len(sp)
    if n < 40:
        return []
    win = int(100 / GRID_M)
    look = int(300 / GRID_M)
    minima = []
    for i in range(1, n - 1):
        a, b = max(0, i - win), min(n, i + win + 1)
        if sp[i] > min(sp[a:b]):
            continue
        before = max(sp[max(0, i - look):i + 1])
        if before - sp[i] < min_drop_kmh:
            continue
        if minima and (i - minima[-1]) * GRID_M < merge_m:
            if sp[i] < sp[minima[-1]]:
                minima[-1] = i
            continue
        minima.append(i)
    if not minima:
        return []
    bounds = []
    for k in range(len(minima) - 1):
        a, b = minima[k], minima[k + 1]
        seg = sp[a:b + 1]
        bounds.append(a + seg.index(max(seg)))
    # Hranice před první zatáčkou: maximum rychlosti mezi startem a 1. zatáčkou
    first = sp[:minima[0] + 1]
    start0 = first.index(max(first))
    corners = []
    dist = trace.dist
    for k, apex in enumerate(minima):
        s = start0 if k == 0 else bounds[k - 1]
        e = bounds[k] if k < len(bounds) else n - 1
        corners.append({
            'id': k + 1, 'name': 'Z%d' % (k + 1),
            'start': dist[s], 'apex': dist[apex], 'end': dist[e],
            'x': trace.cols['x'][apex], 'z': trace.cols['z'][apex],
            'min_speed': round(sp[apex]),
        })
    # Úsek startovní rovinky (od posledního segmentu přes cíl k první zatáčce)
    # přičteme k první zatáčce jako "start" = 0 a k poslední jako konec = délka.
    corners[0]['start'] = 0.0
    corners[-1]['end'] = dist[-1]
    return corners


def _first_index(col, lo, hi, pred):
    for i in range(lo, hi):
        if pred(col[i]):
            return i
    return None


def corner_metrics(trace, corner):
    """Metriky jednoho kola v jedné zatáčce."""
    dist = trace.dist
    c = trace.cols
    i0 = trace.index_at(corner['start'])
    i1 = trace.index_at(corner['end'])
    ia = trace.index_at(corner['apex'])
    r = int(80 / GRID_M)
    lo, hi = max(i0, ia - r), min(i1, ia + r)
    if hi <= lo:
        return None
    seg = c['speed'][lo:hi + 1]
    imin = lo + seg.index(min(seg))
    # bod brzdění: první brzda > 15 % v okně 400 m před vrcholem
    bwin = max(i0 - int(60 / GRID_M), ia - int(400 / GRID_M), 0)
    ib = _first_index(c['brake'], bwin, imin + 1, lambda v: v > 0.15)
    # plný plyn: první throttle >= 95 % po minimu rychlosti
    ithr = _first_index(c['throttle'], imin, i1 + 1, lambda v: v >= 0.95)
    iexit = min(i1, imin + int(150 / GRID_M))
    t0 = trace.time_at(corner['start'])
    t1 = trace.time_at(corner['end'])
    return {
        'time': t1 - t0,
        'min_speed': c['speed'][imin],
        'min_at': dist[imin],
        'brake_at': dist[ib] if ib is not None else None,
        'entry_speed': c['speed'][ib] if ib is not None else c['speed'][max(lo, i0)],
        'throttle_at': dist[ithr] if ithr is not None else None,
        'exit_speed': c['speed'][iexit],
        'gear': c['gear'][imin],
    }


def compare_lap(lap_trace, ref_trace, corners):
    """Porovná kolo s referencí po zatáčkách. Vrátí list dictů s 'loss' v ms
    (kladné = ztráta) a konkrétními rozdíly."""
    out = []
    for c in corners:
        m = corner_metrics(lap_trace, c)
        r = corner_metrics(ref_trace, c)
        if not m or not r:
            continue
        item = {
            'id': c['id'], 'name': c['name'],
            'loss': round(m['time'] - r['time']),
            'min_speed': round(m['min_speed']), 'ref_min_speed': round(r['min_speed']),
            'exit_speed': round(m['exit_speed']), 'ref_exit_speed': round(r['exit_speed']),
            'gear': m['gear'], 'ref_gear': r['gear'],
            'brake_diff_m': None, 'throttle_diff_m': None,
        }
        if m['brake_at'] is not None and r['brake_at'] is not None:
            # záporné = brzdí dřív než reference
            item['brake_diff_m'] = round(m['brake_at'] - r['brake_at'])
        if m['throttle_at'] is not None and r['throttle_at'] is not None:
            # kladné = na plný plyn později
            item['throttle_diff_m'] = round(m['throttle_at'] - r['throttle_at'])
        item['tips'] = corner_tips(item)
        out.append(item)
    return out


def corner_tips(it):
    """Vrátí seznam klíčů rad (jazykově nezávislé), seřazené podle důležitosti."""
    tips = []
    dmin = it['min_speed'] - it['ref_min_speed']
    dexit = it['exit_speed'] - it['ref_exit_speed']
    bd = it['brake_diff_m']
    td = it['throttle_diff_m']
    if bd is not None and bd <= -8 and dmin <= 2:
        tips.append(('brake_early', -bd))
    if bd is not None and bd >= 8 and dmin < -3:
        tips.append(('overdrive', bd, -dmin))
    elif dmin <= -3:
        tips.append(('min_speed', -dmin))
    if td is not None and td >= 10:
        tips.append(('throttle_late', td))
    if dexit <= -4:
        tips.append(('exit', -dexit))
    if it['gear'] != it['ref_gear'] and it['gear'] and it['ref_gear']:
        tips.append(('gear', it['gear'], it['ref_gear']))
    return tips


def theoretical_best(laps, corners):
    """Součet nejlepších časů v jednotlivých zatáčkových úsecích z daných kol."""
    if not laps or not corners:
        return None
    total = 0.0
    for c in corners:
        best = None
        for tr in laps:
            t = tr.time_at(c['end']) - tr.time_at(c['start'])
            if best is None or t < best:
                best = t
        total += best
    return round(total)
