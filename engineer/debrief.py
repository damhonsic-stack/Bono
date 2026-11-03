"""Debrief po session: souhrn dat + text od Gemini (nebo offline šablona)."""
import json
import statistics
import time

from .constants import TRACKS, SESSION_TYPES, VISUAL_COMPOUND
from . import radio as R

PROMPT = {
    'en': """You are {name}, an F1 race engineer writing a short post-session debrief for your driver
(game F1 25). Use ONLY the JSON data. Plain text, no markdown symbols except a numbered list.
Structure: 2-3 sentences summary (result, best lap, consistency, comparison with previous best on
this track if given). Then "Top 3 focus points:" as a numbered list 1-3, each one concrete and
actionable (corner T-number + what to change, strategy, tyres, setup). Max 120 words.
If a value is null (e.g. previous_best_on_track), do not mention it at all. Never invent facts.
recap: per turn avg_loss_ms (vs own best pass), best_vs_avg_ms (negative = gained in best lap),
worst_vs_avg_ms (positive = lost in worst lap), worst_lap_tips. Use it for the focus points.""",
    'cs': """Jsi {name}, závodní inženýr F1. Napiš krátký debrief po session pro svého jezdce (hra F1 25).
Používej JEN data z JSONu. Čistý text, bez markdownu kromě číslovaného seznamu. F1 pojmy anglicky.
Struktura: 2–3 věty shrnutí (výsledek, best lap, konzistence, srovnání s dřívějším rekordem na trati).
Pak "Top 3 věci na příště:" jako číslovaný seznam 1–3, každá konkrétní (T-číslo zatáčky + co změnit,
strategie, gumy, setup). Max 120 slov.
Když je hodnota null (např. previous_best_on_track), vůbec ji nezmiňuj. Nic si nevymýšlej.
recap: pro každý turn avg_loss_ms (ztráta proti vlastnímu nejlepšímu průjezdu), best_vs_avg_ms (záporné
= v best lapu nahnal), worst_vs_avg_ms (kladné = ve worst lapu ztratil), worst_lap_tips. Použij to.""",
}


def build_summary(engine):
    """Data pro debrief (volat pod zámkem enginu)."""
    s = engine.session
    laps = engine.player_laps
    valid = [l for l in laps if l.valid and l.lap_ms]
    best = min((l.lap_ms for l in valid), default=None)
    good = [l.lap_ms for l in valid if best and l.lap_ms < best * 1.07]
    hist = engine.storage.load_history(engine.track_id, limit=2000)
    prev = [h['lap_ms'] for h in hist if h.get('valid') and h.get('ts', 0) < engine.session_started
            and h.get('lap_ms')]
    corners = []
    for c in engine.corner_summary():
        if c.get('avg_loss') is not None and c['avg_loss'] > 15:
            tip = c['last']['tips_text'][0] if c.get('last') and c['last'].get('tips_text') else None
            corners.append({'turn': c['name'], 'avg_loss_ms': c['avg_loss'], 'tip': tip})
    corners.sort(key=lambda c: -c['avg_loss_ms'])
    me = engine.lap[engine.player] if engine.player < len(engine.lap) else None
    sp = [l.meta.get('straight_pct') for l in laps if l.meta.get('straight_pct') is not None]
    out = {
        'track': TRACKS.get(engine.track_id, str(engine.track_id)),
        'session': SESSION_TYPES.get(s.get('session_type'), '?'),
        'ai_difficulty': engine.difficulty(),
        'laps': len(laps), 'valid_laps': len(valid),
        'best_lap': R.fmt_lap(best) if best else None,
        'theoretical_best': R.fmt_lap(engine.snapshot_theoretical()) if engine.snapshot_theoretical() else None,
        'consistency_stdev_s': round(statistics.pstdev(good) / 1000.0, 3) if len(good) >= 3 else None,
        'previous_best_on_track': R.fmt_lap(min(prev)) if prev else None,
        'improvement_vs_previous_s': round((min(prev) - best) / 1000.0, 3) if prev and best else None,
        'worst_turns': corners[:4],
        'straight_mode_avg_pct': round(sum(sp) / len(sp)) if sp else None,
        'grid': me['grid'] if me else None,
        'finish_position': me['position'] if me else None,
        'incidents': engine.incidents.summary(me, engine.damage[engine.player]
                                              if engine.player < len(engine.damage) else None),
        'stints': [{'tyre': VISUAL_COMPOUND.get(st['compound'], '?'), 'clean_laps': len(st['points']),
                    'deg_ms': round(engine.strategy.deg(st['compound'])[0])}
                   for st in engine.strategy.stints],
        'setup_advice': engine.setup.advice()[:3],
    }
    out['incidents'].pop('log', None)
    from .recap import build_recap
    out['recap'] = build_recap(engine)
    return out


def offline_text(summary, lang='en'):
    cs = lang == 'cs'
    lines = []
    head = '%s, %s: %d laps, best %s.' % (summary['track'], summary['session'], summary['laps'],
                                          summary['best_lap'] or '-')
    if cs:
        head = '%s, %s: %d lapů, best %s.' % (summary['track'], summary['session'], summary['laps'],
                                              summary['best_lap'] or '-')
    lines.append(head)
    if summary.get('improvement_vs_previous_s') is not None:
        d = summary['improvement_vs_previous_s']
        lines.append(('Oproti dřívějšímu rekordu %+.3f s.' if cs else 'Versus your previous best: %+.3f s.')
                     % (-d))
    if summary.get('consistency_stdev_s') is not None:
        c = '%.2f' % summary['consistency_stdev_s']
        lines.append(('Konzistence ±%s s.' % c.replace('.', ',')) if cs else ('Consistency ±%s s.' % c))
    lines.extend((summary.get('recap') or {}).get('text') or [])
    lines.append('Top 3 věci na příště:' if cs else 'Top 3 focus points:')
    n = 1
    for c in summary['worst_turns'][:3]:
        lines.append('%d. %s: %s%s' % (n, c['turn'], R.fmt_delta(c['avg_loss_ms'], lang),
                                       (' – ' + c['tip']) if c.get('tip') else ''))
        n += 1
    for a in summary.get('setup_advice', []):
        if n > 3:
            break
        lines.append('%d. %s: %s' % (n, a['issue'], a['change']))
        n += 1
    if n == 1:
        lines.append('1. ' + ('Víc čistých lapů pro analýzu.' if cs else 'More clean laps for analysis.'))
    return '\n'.join(lines)


def make_debrief(engine, summary, lang='en', key=None, model=None, name='Bono'):
    """Vytvoří a uloží debrief z hotového souhrnu. Gemini se volá bez zámku enginu."""
    from . import llm
    from .recap import for_llm
    text, src = None, 'offline'
    payload = dict(summary, recap=for_llm(summary.get('recap')))
    if key:
        try:
            text, _m = llm.ask_with_fallback(
                key, model or llm.DEFAULT_MODEL, lang, 'Write the debrief now.', payload, name=name,
                system=PROMPT.get(lang, PROMPT['en']).replace('{name}', name), max_tokens=3000,
                timeout=25)
            src = 'gemini'
        except Exception as e:  # noqa: BLE001
            engine.last_llm_error = str(e)[:200]
    if not text:
        text = offline_text(summary, lang)
    entry = {'ts': int(time.time()), 'track': summary['track'], 'session': summary['session'],
             'text': text, 'source': src, 'summary': summary}
    engine.storage.append_debrief(entry)
    return entry


def to_json(entry):
    return json.dumps(entry, ensure_ascii=False)
