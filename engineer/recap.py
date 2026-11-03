"""Post-race recap: mapa, sektory a zatáčky – kde ztrácím nejvíc / nejméně,
kde jsem nahnal v best lapu a kde nejvíc ztratil ve worst lapu.

Srovnání po úsecích zatáček (T1, T2 …; úseky dohromady pokrývají celé kolo):
  - ideal  = nejlepší průjezd daného úseku v session
  - avg    = průměr přes čistá kola
  - avg_loss    = avg − ideal          (kde ztrácím pravidelně)
  - best_vs_avg = best lap − avg       (záporné = tady jsem v best lapu nahnal)
  - worst_vs_avg = worst lap − avg     (kladné = tady jsem ve worst lapu ztratil)
"""
import statistics

from .constants import RACE
from .corners import compare_lap
from . import radio as R


def segment_times(trace, corners):
    return [trace.time_at(c['end']) - trace.time_at(c['start']) for c in corners]


def usable_laps(engine, need_trace=True):
    """Čistá kola pro srovnání: platná, bez boxů, bez out/in lapů, bez 1. kola závodu."""
    race = engine.session.get('session_type') in RACE
    out = []
    for l in engine.player_laps:
        if not l.valid or not l.lap_ms or l.meta.get('pitted'):
            continue
        if need_trace and not (l.clean and l.trace):
            continue
        if l.meta.get('kind') in ('in', 'out'):
            continue
        if race and l.lap_num <= 1:
            continue
        out.append(l)
    return out


def _outline(engine, max_points=320):
    o = engine.track_data.get('outline')
    if not o or not o.get('x'):
        return None
    step = max(1, len(o['x']) // max_points)
    return {'x': o['x'][::step], 'z': o['z'][::step], 'dist': o['dist'][::step]}


def _top(rows, key, n=3, reverse=True, filt=None):
    rs = [r for r in rows if r.get(key) is not None and (filt is None or filt(r[key]))]
    rs.sort(key=lambda r: r[key], reverse=reverse)
    return [{'turn': r['name'], 'ms': round(r[key])} for r in rs[:n]]


def build_recap(engine):
    """Volat pod zámkem enginu. Vrací dict pro UI i pro debrief."""
    corners = engine.corners
    laps = usable_laps(engine)
    lang = engine.lang
    out = {'ok': False, 'laps_used': len(laps), 'track_id': engine.track_id,
           'outline': _outline(engine), 'length': engine.session.get('track_length')}
    s2, s3 = engine.session.get('sector2_start'), engine.session.get('sector3_start')
    out['sector_starts'] = [0, s2, s3] if s2 and s3 else None
    # ---- sektory (ze všech platných kol, i bez trace)
    valid = [l for l in usable_laps(engine, need_trace=False) if all(l.sectors)]
    if valid:
        best_l = min(valid, key=lambda l: l.lap_ms)
        worst_l = max(valid, key=lambda l: l.lap_ms)
        avg = [round(statistics.mean(l.sectors[i] for l in valid)) for i in range(3)]
        ideal = [min(l.sectors[i] for l in valid) for i in range(3)]
        out['sectors'] = {
            'best': {'lap': best_l.lap_num, 's': best_l.sectors, 'time': best_l.lap_ms},
            'worst': {'lap': worst_l.lap_num, 's': worst_l.sectors, 'time': worst_l.lap_ms},
            'avg': {'s': avg, 'time': sum(avg)},
            'ideal': {'s': ideal, 'time': sum(ideal)},
        }
    if len(laps) < 2 or not corners:
        out['reason'] = 'Potřebuju aspoň 2 čistá kola s analýzou zatáček.' if lang == 'cs' else \
            'Need at least 2 clean analysed laps.'
        return out
    seg = {l.lap_num: segment_times(l.trace, corners) for l in laps}
    best = min(laps, key=lambda l: l.lap_ms)
    worst = max(laps, key=lambda l: l.lap_ms)
    tips = {}
    if worst is not best:
        for c in compare_lap(worst.trace, best.trace, corners):
            tips[c['id']] = [R.tip_text(lang, t) for t in c['tips'][:2]]
    rows = []
    for k, c in enumerate(corners):
        times = [seg[l.lap_num][k] for l in laps]
        avg = statistics.mean(times)
        ideal = min(times)
        rows.append({
            'id': c['id'], 'name': c['name'], 'start': c['start'], 'end': c['end'],
            'apex': c['apex'], 'x': c['x'], 'z': c['z'],
            'avg_ms': round(avg), 'ideal_ms': round(ideal),
            'avg_loss': round(avg - ideal),
            'best_vs_avg': round(seg[best.lap_num][k] - avg),
            'worst_vs_avg': round(seg[worst.lap_num][k] - avg),
            'stdev': round(statistics.pstdev(times)),
            'worst_tips': tips.get(c['id'], []),
        })
    out.update({
        'ok': True, 'corners': rows,
        'best_lap': {'lap': best.lap_num, 'time': best.lap_ms},
        'worst_lap': {'lap': worst.lap_num, 'time': worst.lap_ms},
        'ideal_time': round(sum(r['ideal_ms'] for r in rows)),
        'highlights': {
            'most_loss': _top(rows, 'avg_loss', 3, True, lambda v: v > 0),
            'least_loss': _top(rows, 'avg_loss', 3, False),
            'best_gains': _top(rows, 'best_vs_avg', 3, False, lambda v: v < 0),
            'worst_losses': _top(rows, 'worst_vs_avg', 3, True, lambda v: v > 0),
        },
    })
    out['text'] = highlights_text(out, lang)
    return out


def highlights_text(rc, lang='cs'):
    if not rc.get('ok'):
        return []
    h = rc['highlights']
    cs = lang == 'cs'

    def fmt(items, sign=False):
        return ', '.join('%s (%s)' % (i['turn'], R.fmt_delta(i['ms'], lang, signed=sign)) for i in items)
    lines = []
    if h['most_loss']:
        lines.append(('Nejvíc pravidelně ztrácíš: ' if cs else 'Losing most consistently: ') +
                     fmt(h['most_loss']))
    if h['least_loss']:
        lines.append(('Nejstabilnější: ' if cs else 'Most consistent: ') + fmt(h['least_loss']))
    if h['best_gains']:
        lines.append(('V best lapu (lap %d) jsi nahnal hlavně: ' if cs else
                      'In your best lap (lap %d) you gained most in: ') % rc['best_lap']['lap'] +
                     fmt(h['best_gains'], True))
    if h['worst_losses']:
        lines.append(('Ve worst lapu (lap %d) jsi nejvíc ztratil: ' if cs else
                      'In your worst lap (lap %d) you lost most in: ') % rc['worst_lap']['lap'] +
                     fmt(h['worst_losses'], True))
    return lines


def for_llm(rc):
    """Kompaktní verze pro Gemini (bez mapy)."""
    if not rc:
        return None
    keep = {k: rc.get(k) for k in ('ok', 'laps_used', 'best_lap', 'worst_lap', 'ideal_time',
                                   'highlights', 'sectors')}
    if rc.get('corners'):
        keep['turns'] = [{'turn': r['name'], 'avg_loss_ms': r['avg_loss'],
                          'best_vs_avg_ms': r['best_vs_avg'], 'worst_vs_avg_ms': r['worst_vs_avg'],
                          'worst_lap_tips': r['worst_tips']} for r in rc['corners']]
    return keep
