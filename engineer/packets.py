"""Parser UDP telemetrie F1 25 (formát 2025).

Pouze standardní knihovna (struct), aby to běželo i v a-Shell na iPadu.
Rozložení struktur odpovídá oficiální specifikaci EA F1 25 UDP.
Pořadí kol v polích: RL, RR, FL, FR.
"""
import struct

NUM_CARS = 22

HEADER = struct.Struct('<HBBBBBQfIIBB')  # 29 B
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

# Očekávané velikosti paketů (F1 25, formát 2025)
PACKET_SIZES = {
    MOTION: 1349,
    SESSION: 753,
    LAP_DATA: 1285,
    EVENT: 45,
    PARTICIPANTS: 1284,
    CAR_TELEMETRY: 1352,
    CAR_STATUS: 1239,
    CAR_DAMAGE: 1041,
    SESSION_HISTORY: 1460,
    TIME_TRIAL: 101,
}

LAP = struct.Struct('<IIHBHBHBHBfff' + 'B' * 15 + 'HHBfB')  # 57 B
TELEMETRY = struct.Struct('<HfffBbHBBH4H4B4BH4f4B')  # 60 B
STATUS = struct.Struct('<BBBBBfffHHBBHBBBbfffBfffB')  # 55 B
DAMAGE_STRIDE = 46
DAMAGE_HEAD = struct.Struct('<4f4B4B')
MOTION_CAR = struct.Struct('<ffffffhhhhhhffffff')  # 60 B
PARTICIPANT = struct.Struct('<BBBBBBB32sBBHBB12s')  # 57 B
HISTORY_HEAD = struct.Struct('<BBBBBBB')
HISTORY_LAP = struct.Struct('<IHBHBHBB')  # 14 B
TT_SET = struct.Struct('<BBIIIIBBBBBB')  # 24 B
FORECAST = struct.Struct('<BBBbbbbB')  # 8 B

assert HEADER.size == 29 and LAP.size == 57 and TELEMETRY.size == 60
assert STATUS.size == 55 and MOTION_CAR.size == 60 and PARTICIPANT.size == 57
assert HISTORY_LAP.size == 14 and TT_SET.size == 24


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


def parse_lap_data(data):
    cars = []
    off = HEADER_SIZE
    for _ in range(NUM_CARS):
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
            'driver_status': v[25],
            'result_status': v[26],
        })
    pb_idx, rival_idx = struct.unpack_from('<BB', data, off)
    return {'cars': cars, 'tt_pb_idx': pb_idx, 'tt_rival_idx': rival_idx}


def parse_telemetry(data):
    cars = []
    off = HEADER_SIZE
    for _ in range(NUM_CARS):
        v = TELEMETRY.unpack_from(data, off)
        off += TELEMETRY.size
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


def parse_status(data):
    cars = []
    off = HEADER_SIZE
    for _ in range(NUM_CARS):
        v = STATUS.unpack_from(data, off)
        off += STATUS.size
        cars.append({
            'fuel_mix': v[2], 'brake_bias': v[3],
            'fuel_in_tank': v[5], 'fuel_capacity': v[6],
            'fuel_remaining_laps': v[7],
            'drs_allowed': v[11],
            'actual_compound': v[13], 'visual_compound': v[14],
            'tyre_age': v[15], 'fia_flag': v[16],
            'ers_store': v[19], 'ers_mode': v[20],
            'ers_deployed_lap': v[23],
        })
    return {'cars': cars}


def parse_damage(data):
    cars = []
    for i in range(NUM_CARS):
        v = DAMAGE_HEAD.unpack_from(data, HEADER_SIZE + i * DAMAGE_STRIDE)
        cars.append({
            'tyre_wear': [round(w, 1) for w in v[0:4]],
            'tyre_damage': list(v[4:8]),
            'brake_damage': list(v[8:12]),
        })
    return {'cars': cars}


def parse_motion(data):
    cars = []
    off = HEADER_SIZE
    for _ in range(NUM_CARS):
        v = MOTION_CAR.unpack_from(data, off)
        off += MOTION_CAR.size
        cars.append({'x': v[0], 'y': v[1], 'z': v[2],
                     'g_lat': v[12], 'g_long': v[13]})
    return {'cars': cars}


def parse_session(data):
    (weather, track_temp, air_temp, total_laps, track_length, session_type,
     track_id, formula, time_left, duration, pit_limit) = struct.unpack_from(
        '<BbbBHBbBHHB', data, 29)
    game_paused = data[43]
    safety_car = data[153]
    n_fc = data[155]
    forecast = []
    for i in range(min(n_fc, 64)):
        f = FORECAST.unpack_from(data, 156 + i * 8)
        if f[0] == session_type:
            forecast.append({'offset_min': f[1], 'weather': f[2], 'rain_pct': f[7]})
    ai_difficulty = data[669]
    game_mode = data[694]
    s2_start, s3_start = struct.unpack_from('<ff', data, 745)
    return {
        'weather': weather, 'track_temp': track_temp, 'air_temp': air_temp,
        'total_laps': total_laps, 'track_length': track_length,
        'session_type': session_type, 'track_id': track_id, 'formula': formula,
        'time_left': time_left, 'duration': duration, 'pit_limit': pit_limit,
        'paused': game_paused, 'safety_car': safety_car, 'forecast': forecast,
        'ai_difficulty': ai_difficulty, 'game_mode': game_mode,
        'sector2_start': s2_start, 'sector3_start': s3_start,
    }


def parse_participants(data):
    num = data[29]
    cars = []
    for i in range(NUM_CARS):
        v = PARTICIPANT.unpack_from(data, 30 + i * PARTICIPANT.size)
        name = v[7].split(b'\x00', 1)[0].decode('utf-8', 'replace')
        cars.append({'ai': v[0], 'driver_id': v[1], 'team_id': v[3],
                     'number': v[5], 'name': name})
    return {'num_active': num, 'cars': cars}


def parse_session_history(data):
    car, num_laps, num_stints, best_lap, b1, b2, b3 = HISTORY_HEAD.unpack_from(data, 29)
    laps = []
    for i in range(min(num_laps, 100)):
        v = HISTORY_LAP.unpack_from(data, 36 + i * HISTORY_LAP.size)
        laps.append({'lap_ms': v[0], 's1': _ms(v[1], v[2]), 's2': _ms(v[3], v[4]),
                     's3': _ms(v[5], v[6]), 'valid_flags': v[7]})
    return {'car': car, 'num_laps': num_laps, 'best_lap': best_lap,
            'best_s': (b1, b2, b3), 'laps': laps}


def parse_time_trial(data):
    sets = []
    for i in range(3):
        v = TT_SET.unpack_from(data, 29 + i * TT_SET.size)
        sets.append({'car': v[0], 'team': v[1], 'lap_ms': v[2],
                     's1': v[3], 's2': v[4], 's3': v[5], 'valid': v[11]})
    return {'session_best': sets[0], 'personal_best': sets[1], 'rival': sets[2]}


def parse_event(data):
    code = data[29:33].decode('ascii', 'replace')
    ev = {'code': code}
    if code == 'BUTN' and len(data) >= 37:
        ev['buttons'] = struct.unpack_from('<I', data, 33)[0]
    elif code == 'FTLP' and len(data) >= 34:
        ev['car'] = data[33]
        ev['lap_time'] = struct.unpack_from('<f', data, 34)[0]
    return ev


PARSERS = {
    MOTION: parse_motion,
    SESSION: parse_session,
    LAP_DATA: parse_lap_data,
    EVENT: parse_event,
    PARTICIPANTS: parse_participants,
    CAR_TELEMETRY: parse_telemetry,
    CAR_STATUS: parse_status,
    CAR_DAMAGE: parse_damage,
    SESSION_HISTORY: parse_session_history,
    TIME_TRIAL: parse_time_trial,
}


def parse_packet(data):
    """Vrátí (header, packet_id, payload) nebo None pro nepodporované pakety."""
    hdr = parse_header(data)
    if hdr is None:
        return None
    pid = hdr['packet_id']
    parser = PARSERS.get(pid)
    if parser is None:
        return hdr, pid, None
    need = PACKET_SIZES.get(pid, 0)
    if pid == EVENT:
        need = 33
    if len(data) < need:
        return hdr, pid, None
    return hdr, pid, parser(data)
