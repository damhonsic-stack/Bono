"""Parser UDP telemetrie F1 25 – formát 2025 i 2026 (2026 Season Pack).

Pouze standardní knihovna (struct), aby to běželo i v a-Shell na iPadu.
Rozložení struktur odpovídá oficiálním specifikacím EA:
  - "Data Output from F1 25" (formát 2025, 22 aut)
  - "Data Output from F1 25: 2026 Season Pack" v1.2 (formát 2026, 24 aut)
Pořadí kol v polích: RL, RR, FL, FR.
"""
import struct

MAX_CARS = 24
NUM_CARS = MAX_CARS  # zpětná kompatibilita

HEADER = struct.Struct('<HBBBBBQfIIBB')  # 29 B, stejné pro 2025 i 2026
HEADER_SIZE = HEADER.size

# packet ids
MOTION = 0
SESSION = 1
LAP_DATA = 2
EVENT = 3
PARTICIPANTS = 4
CAR_SETUPS = 5
CAR_TELEMETRY = 6
CAR_STATUS = 7
FINAL_CLASSIFICATION = 8
LOBBY_INFO = 9
CAR_DAMAGE = 10
SESSION_HISTORY = 11
TYRE_SETS = 12
MOTION_EX = 13
TIME_TRIAL = 14
LAP_POSITIONS = 15
CAR_TELEMETRY_2 = 16  # jen formát 2026

LAP = struct.Struct('<IIHBHBHBHBfff' + 'B' * 15 + 'HHBfB')  # 57 B (2025 i 2026)
HISTORY_HEAD = struct.Struct('<BBBBBBB')
HISTORY_LAP = struct.Struct('<IHBHBHBB')  # 14 B
FORECAST = struct.Struct('<BBBbbbbB')  # 8 B
TELEMETRY2 = struct.Struct('<BBHBBHBB')  # 10 B (2026)
DAMAGE_STRIDE = 46
DAMAGE = struct.Struct('<4f4B4B4B18B')  # 46 B (2025 i 2026)
SETUP = struct.Struct('<BBBBffffBBBBBBBBBffffBf')  # 50 B (2025 i 2026)
TYRE_SET = struct.Struct('<BBBBBBBhB')  # 10 B
MOTION_EX_S = struct.Struct('<' + 'f' * 61)  # 244 B (jen hráč)


class Layout:
    def __init__(self, fmt, cars, telemetry, status, motion, participant, tt_set, sizes):
        self.format = fmt
        self.cars = cars
        self.telemetry = struct.Struct(telemetry)
        self.status = struct.Struct(status)
        self.motion = struct.Struct(motion)
        self.participant = struct.Struct(participant)
        self.tt_set = struct.Struct(tt_set)
        self.sizes = sizes


LAYOUT_2025 = Layout(
    2025, 22,
    telemetry='<HfffBbHBBH4H4B4BH4f4B',          # 60 B (engine temp uint16)
    status='<BBBBBfffHHBBHBBBbfffBfffB',         # 55 B
    motion='<ffffffhhhhhhffffff',                # 60 B (g-force float)
    participant='<BBBBBBB32sBBHBB12s',           # 57 B
    tt_set='<BBIIIIBBBBBB',                      # 24 B
    sizes={MOTION: 1349, SESSION: 753, LAP_DATA: 1285, EVENT: 45, PARTICIPANTS: 1284,
           CAR_SETUPS: 1133, CAR_TELEMETRY: 1352, CAR_STATUS: 1239, CAR_DAMAGE: 1041,
           SESSION_HISTORY: 1460, TYRE_SETS: 231, MOTION_EX: 273, TIME_TRIAL: 101},
)

LAYOUT_2026 = Layout(
    2026, 24,
    telemetry='<HfffBbHBBH4H4B4BB4f4B',          # 59 B (engine temp uint8)
    status='<BBBBBfffHHBBHBBBbfffBffffB',        # 59 B (+ ERS harvest limit per lap)
    motion='<ffffffhhhhhhhhhfff',                # 54 B (g-force int16)
    participant='<BHHHBBB32sBBHBB12s',           # 60 B (driver/network/team id uint16)
    tt_set='<BHIIIIBBBBBB',                      # 25 B (team id uint16)
    sizes={MOTION: 1325, SESSION: 926, LAP_DATA: 1399, EVENT: 45, PARTICIPANTS: 1470,
           CAR_SETUPS: 1233, CAR_TELEMETRY: 1448, CAR_STATUS: 1445, CAR_DAMAGE: 1133,
           SESSION_HISTORY: 1460, TYRE_SETS: 231, MOTION_EX: 273, TIME_TRIAL: 104,
           CAR_TELEMETRY_2: 269},
)

LAYOUTS = {2025: LAYOUT_2025, 2026: LAYOUT_2026}
PACKET_SIZES = LAYOUT_2025.sizes  # zpětná kompatibilita

# Tlačítka (BUTN event) – UDP Action 1..12 lze ve hře namapovat na ovladač
UDP_ACTION_BITS = {i + 1: 0x00100000 << i for i in range(12)}

for _l in LAYOUTS.values():
    assert HEADER_SIZE + _l.cars * LAP.size + 2 == _l.sizes[LAP_DATA]
    assert HEADER_SIZE + _l.cars * _l.telemetry.size + 3 == _l.sizes[CAR_TELEMETRY]
    assert HEADER_SIZE + _l.cars * _l.status.size == _l.sizes[CAR_STATUS]
    assert HEADER_SIZE + _l.cars * _l.motion.size == _l.sizes[MOTION]
    assert HEADER_SIZE + 1 + _l.cars * _l.participant.size == _l.sizes[PARTICIPANTS]
    assert HEADER_SIZE + _l.cars * DAMAGE_STRIDE == _l.sizes[CAR_DAMAGE]
    assert HEADER_SIZE + 3 * _l.tt_set.size == _l.sizes[TIME_TRIAL]
    assert HEADER_SIZE + _l.cars * SETUP.size + 4 == _l.sizes[CAR_SETUPS]
    assert HEADER_SIZE + 1 + 20 * TYRE_SET.size + 1 == _l.sizes[TYRE_SETS]
    assert HEADER_SIZE + MOTION_EX_S.size == _l.sizes[MOTION_EX]
assert DAMAGE.size == DAMAGE_STRIDE
assert HEADER_SIZE + 24 * TELEMETRY2.size == LAYOUT_2026.sizes[CAR_TELEMETRY_2]


def _ms(ms_part, min_part):
    return min_part * 60000 + ms_part


def parse_header(data):
    if len(data) < HEADER_SIZE:
        return None
    (fmt, year, major, minor, pver, pid, uid, stime, frame, oframe,
     player, player2) = HEADER.unpack_from(data, 0)
    return {
        'format': fmt, 'year': year, 'packet_id': pid, 'session_uid': uid,
        'session_time': stime, 'frame': frame, 'player': player,
    }


def parse_lap_data(data, L):
    cars = []
    off = HEADER_SIZE
    for _ in range(L.cars):
        v = LAP.unpack_from(data, off)
        off += LAP.size
        cars.append({
            'last_lap_ms': v[0],
            'current_lap_ms': v[1],
            's1_ms': _ms(v[2], v[3]),
            's2_ms': _ms(v[4], v[5]),
            'delta_front_ms': _ms(v[6], v[7]),
            'delta_leader_ms': _ms(v[8], v[9]),
            'lap_distance': v[10],
            'total_distance': v[11],
            'position': v[13],
            'lap_num': v[14],
            'pit_status': v[15],
            'num_pit_stops': v[16],
            'sector': v[17],
            'invalid': v[18],
            'penalties': v[19],
            'warnings': v[20],
            'cc_warnings': v[21],
            'unserved_dt': v[22],
            'unserved_sg': v[23],
            'grid': v[24],
            'driver_status': v[25],   # 0 garage, 1 flying lap, 2 in lap, 3 out lap, 4 on track
            'result_status': v[26],
            'pit_lane_active': v[27],
            'pit_lane_ms': v[28],
            'pit_stop_ms': v[29],
            'sc_delta': v[12],
        })
    pb_idx, rival_idx = struct.unpack_from('<BB', data, off)
    return {'cars': cars, 'tt_pb_idx': pb_idx, 'tt_rival_idx': rival_idx}


def parse_telemetry(data, L):
    cars = []
    off = HEADER_SIZE
    for _ in range(L.cars):
        v = L.telemetry.unpack_from(data, off)
        off += L.telemetry.size
        cars.append({
            'speed': v[0], 'throttle': v[1], 'steer': v[2], 'brake': v[3],
            'gear': v[5], 'rpm': v[6], 'drs': v[7],
            'brake_temp': list(v[10:14]),
            'tyre_surface': list(v[14:18]),
            'tyre_inner': list(v[18:22]),
            'engine_temp': v[22],
            'tyre_pressure': [round(p, 1) for p in v[23:27]],
        })
    return {'cars': cars}


def parse_telemetry2(data, L):
    cars = []
    for i in range(24):
        v = TELEMETRY2.unpack_from(data, HEADER_SIZE + i * TELEMETRY2.size)
        cars.append({
            'aero_mode': v[0],             # 0 = Corner mode, 1 = Straight mode
            'aero_available': v[1],
            'aero_distance': v[2],         # m do zpřístupnění active aero
            'overtake_available': v[3],
            'overtake_active': v[4],
            'overtake_distance': v[5],     # m do zpřístupnění overtake mode
            'regs_2026': v[6],
            'wrong_way': v[7],
        })
    return {'cars': cars}


def parse_status(data, L):
    cars = []
    off = HEADER_SIZE
    is26 = L.format == 2026
    for _ in range(L.cars):
        v = L.status.unpack_from(data, off)
        off += L.status.size
        cars.append({
            'fuel_mix': v[2], 'brake_bias': v[3],
            'fuel_in_tank': v[5], 'fuel_capacity': v[6],
            'fuel_remaining_laps': v[7],
            'drs_allowed': v[11], 'drs_distance': v[12],
            'actual_compound': v[13], 'visual_compound': v[14],
            'tyre_age': v[15], 'fia_flag': v[16],
            'ice_power': v[17], 'mguk_power': v[18],
            'ers_store': v[19], 'ers_mode': v[20],
            'ers_harvested_k': v[21], 'ers_harvested_h': v[22],
            'ers_harvest_limit': v[23] if is26 else None,
            'ers_deployed_lap': v[24] if is26 else v[23],
        })
    return {'cars': cars}


def parse_damage(data, L):
    cars = []
    for i in range(L.cars):
        v = DAMAGE.unpack_from(data, HEADER_SIZE + i * DAMAGE_STRIDE)
        cars.append({
            'tyre_wear': [round(w, 1) for w in v[0:4]],
            'tyre_damage': list(v[4:8]),
            'brake_damage': list(v[8:12]),
            'blisters': list(v[12:16]),
            'fl_wing': v[16], 'fr_wing': v[17], 'rear_wing': v[18], 'floor': v[19],
            'diffuser': v[20], 'sidepod': v[21], 'drs_fault': v[22], 'ers_fault': v[23],
            'gearbox': v[24], 'engine': v[25],
            'engine_blown': v[32], 'engine_seized': v[33],
        })
    return {'cars': cars}


def parse_setups(data, L):
    cars = []
    for i in range(L.cars):
        v = SETUP.unpack_from(data, HEADER_SIZE + i * SETUP.size)
        cars.append({
            'front_wing': v[0], 'rear_wing': v[1], 'on_throttle': v[2], 'off_throttle': v[3],
            'front_camber': round(v[4], 2), 'rear_camber': round(v[5], 2),
            'front_toe': round(v[6], 2), 'rear_toe': round(v[7], 2),
            'front_susp': v[8], 'rear_susp': v[9], 'front_arb': v[10], 'rear_arb': v[11],
            'front_height': v[12], 'rear_height': v[13], 'brake_pressure': v[14],
            'brake_bias': v[15], 'engine_braking': v[16],
            'pressures': [round(x, 1) for x in v[17:21]],  # RL, RR, FL, FR
            'ballast': v[21], 'fuel_load': round(v[22], 1),
        })
    return {'cars': cars}


def parse_tyre_sets(data, L):
    car = data[29]
    sets = []
    for i in range(20):
        v = TYRE_SET.unpack_from(data, 30 + i * TYRE_SET.size)
        sets.append({'actual': v[0], 'visual': v[1], 'wear': v[2], 'available': v[3],
                     'recommended_session': v[4], 'life_left': v[5], 'usable_life': v[6],
                     'lap_delta': v[7], 'fitted': v[8], 'idx': i})
    return {'car': car, 'sets': sets, 'fitted_idx': data[230]}


def parse_motion_ex(data, L):
    v = MOTION_EX_S.unpack_from(data, HEADER_SIZE)
    return {
        'slip_ratio': list(v[16:20]),     # RL, RR, FL, FR
        'slip_angle': list(v[20:24]),
        'local_vel': list(v[33:36]),
        'ang_vel': list(v[36:39]),
        'front_wheels_angle': v[42],
        'chassis_yaw': v[51],
    }


def parse_motion(data, L):
    cars = []
    off = HEADER_SIZE
    for _ in range(L.cars):
        v = L.motion.unpack_from(data, off)
        off += L.motion.size
        cars.append({'x': v[0], 'y': v[1], 'z': v[2]})
    return {'cars': cars}


def _zones(data, off, n, max_n):
    out = []
    for i in range(min(n, max_n)):
        a, b = struct.unpack_from('<ff', data, off + i * 8)
        out.append((a, b))
    return out


def parse_session(data, L):
    (weather, track_temp, air_temp, total_laps, track_length, session_type,
     track_id, formula, time_left, duration, pit_limit) = struct.unpack_from(
        '<BbbBHBbBHHB', data, 29)
    s = {
        'weather': weather, 'track_temp': track_temp, 'air_temp': air_temp,
        'total_laps': total_laps, 'track_length': track_length,
        'session_type': session_type, 'track_id': track_id, 'formula': formula,
        'time_left': time_left, 'duration': duration, 'pit_limit': pit_limit,
        'paused': data[43], 'safety_car': data[153], 'network': data[154],
        'marshal_zones': [struct.unpack_from('<fb', data, 48 + i * 5)
                          for i in range(min(data[47], 21))],
        'ai_difficulty': data[669], 'game_mode': data[694],
        'pit_ideal_lap': data[682], 'pit_latest_lap': data[683],
    }
    n_fc = data[155]
    s['forecast'] = []
    for i in range(min(n_fc, 64)):
        f = FORECAST.unpack_from(data, 156 + i * 8)
        if f[0] == session_type:
            s['forecast'].append({'offset_min': f[1], 'weather': f[2], 'rain_pct': f[7]})
    s['sector2_start'], s['sector3_start'] = struct.unpack_from('<ff', data, 745)
    if L.format == 2026:
        # Active aero a DRS zóny (zlomky délky kola 0..1)
        s['aero_status'] = data[753]          # 0 = Full, 1 = Partial
        s['aero_zones_full'] = _zones(data, 755, data[754], 8)
        s['aero_zones_partial'] = _zones(data, 820, data[819], 8)
        s['drs_zones'] = _zones(data, 885, data[884], 4)
        s['start_reaction'] = struct.unpack_from('<f', data, 917)[0]
    return s


def parse_participants(data, L):
    num = data[29]
    cars = []
    for i in range(L.cars):
        v = L.participant.unpack_from(data, 30 + i * L.participant.size)
        name = v[7].split(b'\x00', 1)[0].decode('utf-8', 'replace')
        cars.append({'ai': v[0], 'driver_id': v[1], 'team_id': v[3],
                     'number': v[5], 'name': name})
    return {'num_active': num, 'cars': cars}


def parse_session_history(data, L):
    car, num_laps, num_stints, best_lap, b1, b2, b3 = HISTORY_HEAD.unpack_from(data, 29)
    laps = []
    for i in range(min(num_laps, 100)):
        v = HISTORY_LAP.unpack_from(data, 36 + i * HISTORY_LAP.size)
        laps.append({'lap_ms': v[0], 's1': _ms(v[1], v[2]), 's2': _ms(v[3], v[4]),
                     's3': _ms(v[5], v[6]), 'valid_flags': v[7]})
    stints = []
    for i in range(min(num_stints, 8)):
        end, actual, visual = struct.unpack_from('<BBB', data, 1436 + i * 3)
        stints.append({'end_lap': end, 'actual': actual, 'visual': visual})
    return {'car': car, 'num_laps': num_laps, 'best_lap': best_lap,
            'best_s': (b1, b2, b3), 'laps': laps, 'stints': stints}


def parse_time_trial(data, L):
    sets = []
    for i in range(3):
        v = L.tt_set.unpack_from(data, 29 + i * L.tt_set.size)
        sets.append({'car': v[0], 'team': v[1], 'lap_ms': v[2],
                     's1': v[3], 's2': v[4], 's3': v[5], 'valid': v[11]})
    return {'session_best': sets[0], 'personal_best': sets[1], 'rival': sets[2]}


def parse_event(data, L):
    code = data[29:33].decode('ascii', 'replace')
    ev = {'code': code}
    if code == 'BUTN':
        ev['buttons'] = struct.unpack_from('<I', data, 33)[0]
    elif code == 'FTLP':
        ev['car'] = data[33]
        ev['lap_time'] = struct.unpack_from('<f', data, 34)[0]
    elif code == 'OVTK':
        ev['overtaker'], ev['overtaken'] = data[33], data[34]
    elif code == 'PMEN':
        ev['reason'] = data[33]
    elif code == 'PENA':
        (ev['penalty_type'], ev['infringement'], ev['car'], ev['other'], ev['time'],
         ev['lap'], ev['places']) = struct.unpack_from('<7B', data, 33)
    elif code in ('RTMT', 'TMPT', 'RCWN', 'DTSV', 'SGSV'):
        ev['car'] = data[33]
    elif code == 'SCAR':
        ev['sc_type'], ev['sc_event'] = data[33], data[34]
    elif code == 'COLL':
        ev['car1'], ev['car2'] = data[33], data[34]
        if L.format == 2026:
            ev['severity'] = data[35]
    return ev


PARSERS = {
    MOTION: parse_motion,
    SESSION: parse_session,
    LAP_DATA: parse_lap_data,
    EVENT: parse_event,
    PARTICIPANTS: parse_participants,
    CAR_TELEMETRY: parse_telemetry,
    CAR_TELEMETRY_2: parse_telemetry2,
    CAR_SETUPS: parse_setups,
    TYRE_SETS: parse_tyre_sets,
    MOTION_EX: parse_motion_ex,
    CAR_STATUS: parse_status,
    CAR_DAMAGE: parse_damage,
    SESSION_HISTORY: parse_session_history,
    TIME_TRIAL: parse_time_trial,
}


def parse_packet(data):
    """Vrátí (header, packet_id, payload) nebo None. payload je None pro
    nepodporované pakety, neznámý formát nebo špatnou velikost."""
    hdr = parse_header(data)
    if hdr is None:
        return None
    pid = hdr['packet_id']
    L = LAYOUTS.get(hdr['format'])
    parser = PARSERS.get(pid)
    if parser is None or L is None:
        return hdr, pid, None
    need = L.sizes.get(pid)
    if need is None or len(data) < need:
        return hdr, pid, None
    return hdr, pid, parser(data, L)
