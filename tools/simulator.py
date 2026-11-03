#!/usr/bin/env python3
"""Simulátor UDP telemetrie F1 25 – na testování bez Xboxu.

Vytváří syntetickou trať s 8 zatáčkami, hráče a několik AI aut a posílá pakety
ve formátu F1 25 (2025). Hráč dělá náhodné chyby (pozdní plyn, brzká brzda…),
takže inženýr má co analyzovat.

    python3 tools/simulator.py                  # posílá na 127.0.0.1:20777
    python3 tools/simulator.py --speed 4        # 4× rychleji než reálný čas
    python3 tools/simulator.py --mode race      # závod (mezery, palivo, gumy)
"""
import argparse
import math
import os
import random
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engineer import packets as P  # noqa: E402

TRACK_LEN = 4600.0
# (vzdálenost vrcholu, minimální rychlost km/h)
CORNERS = [(450, 95), (1050, 160), (1500, 210), (2050, 75), (2600, 140),
           (3150, 230), (3600, 110), (4150, 185)]
VMAX = 325.0
BRAKE = 38.0   # km/h na každých ~ m (zjednodušená decelerace v (km/h)^2 / m)
ACCEL = 5.5


def speed_profile(skill=1.0, errors=None):
    """Vrátí funkci v(d) pro jedno kolo. errors: {corner_idx: (typ, velikost)}."""
    errors = errors or {}
    prof = []
    step = 2.0
    n = int(TRACK_LEN / step) + 1
    for i in range(n):
        d = i * step
        v = VMAX * (0.985 + 0.015 * skill)
        for k, (apex, vmin) in enumerate(CORNERS):
            vmin_k = vmin * (0.97 + 0.03 * skill)
            brake = BRAKE * (0.95 + 0.05 * skill)
            acc = ACCEL
            e = errors.get(k)
            if e:
                kind, mag = e
                if kind == 'early':
                    brake *= (1 - mag)
                elif kind == 'slow':
                    vmin_k *= (1 - mag)
                elif kind == 'late_throttle':
                    acc *= (1 - mag)
            for off in (-TRACK_LEN, 0, TRACK_LEN):
                a = apex + off
                if d <= a:
                    lim = math.sqrt(vmin_k ** 2 + 2 * brake * 40 * (a - d))
                else:
                    lim = math.sqrt(vmin_k ** 2 + 2 * acc * 40 * (d - a))
                v = min(v, lim)
        prof.append(v)
    return prof, step


def xz(d):
    th = 2 * math.pi * d / TRACK_LEN
    r = 700 + 120 * math.sin(3 * th) + 60 * math.cos(5 * th)
    return r * math.cos(th), r * math.sin(th) * 0.7


class SimCar:
    def __init__(self, idx, name, skill, ai, start_offset=0.0, laps=10):
        self.idx, self.name, self.skill, self.ai = idx, name, skill, ai
        self.total = -start_offset
        self.lap = 1
        self.lap_time = 0.0
        self.last_lap = 0
        self.s1 = self.s2 = 0
        self.invalid = 0
        self.laps_total = laps
        self.fuel = 1.6 * laps + 1.2
        self.wear = [2.0, 2.0, 1.5, 1.5]
        self.tyre_age = 0
        self.new_lap_profile()
        self.prev_v = self.v_at(max(0.0, self.dist()))

    def dist(self):
        return self.total - (self.lap - 1) * TRACK_LEN

    def new_lap_profile(self):
        errors = {}
        if not self.ai:
            for k in random.sample(range(len(CORNERS)), 2):
                errors[k] = (random.choice(['early', 'slow', 'late_throttle']),
                             random.uniform(0.04, 0.12))
        self.errors = errors
        self.profile, self.pstep = speed_profile(self.skill, errors)
        self.invalid = 1 if (not self.ai and random.random() < 0.1) else 0

    def v_at(self, d):
        i = int(max(0.0, min(d, TRACK_LEN - 1)) / self.pstep)
        return self.profile[i]

    def step(self, dt):
        d = self.dist()
        v = self.v_at(max(0.0, d))
        self.throttle = 1.0 if v >= self.prev_v - 0.01 else 0.0
        self.brake = min(1.0, max(0.0, (self.prev_v - v) / (dt * 60))) if v < self.prev_v - 0.01 else 0.0
        if 0 < self.throttle and v < 200 and v - self.prev_v < 0.05:
            self.throttle = 0.6
        self.prev_v = v
        self.speed = v
        self.total += v / 3.6 * dt
        if self.total >= 0:
            self.lap_time += dt
        d = self.dist()
        if d >= TRACK_LEN / 3 and not self.s1:
            self.s1 = int(self.lap_time * 1000)
        if d >= 2 * TRACK_LEN / 3 and not self.s2:
            self.s2 = int(self.lap_time * 1000) - self.s1
        if d >= TRACK_LEN:
            over = (d - TRACK_LEN) / (v / 3.6)
            self.last_lap = int((self.lap_time - over) * 1000)
            self.lap_time = over
            self.lap += 1
            self.s1 = self.s2 = 0
            self.fuel -= 1.6
            self.wear = [w + random.uniform(1.0, 1.6) for w in self.wear]
            self.tyre_age += 1
            self.new_lap_profile()

    def gear(self):
        return max(1, min(8, int(self.speed / 40) + 1))


def header(pid, uid, t, frame, player=0):
    return P.HEADER.pack(2025, 25, 1, 0, 1, pid, uid, t, frame, frame, player, 255)


def pack_lap(cars, uid, t, frame, positions):
    out = bytearray(header(P.LAP_DATA, uid, t, frame))
    for i in range(P.NUM_CARS):
        c = cars.get(i)
        if not c:
            out += bytes(P.LAP.size)
            continue
        pos = positions[i]
        ahead = [x for x in cars.values() if positions[x.idx] == pos - 1]
        gap = 0
        if ahead:
            gap = int(max(0.0, (ahead[0].total - c.total)) / max(c.speed / 3.6, 1) * 1000)
        fields = [c.last_lap, int(c.lap_time * 1000), c.s1 % 60000, c.s1 // 60000,
                  c.s2 % 60000, c.s2 // 60000, gap % 60000, gap // 60000, 0, 0,
                  c.dist(), c.total, 0.0,
                  pos, c.lap, 0, 0, 0 if c.dist() < TRACK_LEN / 3 else
                  (1 if c.dist() < 2 * TRACK_LEN / 3 else 2),
                  c.invalid, 0, 0, 0, 0, 0, pos, 4, 2, 0,
                  0, 0, 0, 0.0, 0]
        out += P.LAP.pack(*fields)
    out += struct.pack('<BB', 255, 255)
    return bytes(out)


def pack_telemetry(cars, uid, t, frame):
    out = bytearray(header(P.CAR_TELEMETRY, uid, t, frame))
    for i in range(P.NUM_CARS):
        c = cars.get(i)
        if not c:
            out += bytes(P.TELEMETRY.size)
            continue
        out += P.TELEMETRY.pack(int(c.speed), c.throttle, 0.0, c.brake, 0, c.gear(),
                                int(6000 + c.speed * 30), 0, 50, 0,
                                *([500] * 4), *([95] * 4), *([100] * 4), 105,
                                *([22.5] * 4), *([0] * 4))
    out += struct.pack('<BBb', 255, 255, 0)
    return bytes(out)


def pack_motion(cars, uid, t, frame):
    out = bytearray(header(P.MOTION, uid, t, frame))
    for i in range(P.NUM_CARS):
        c = cars.get(i)
        if not c:
            out += bytes(P.MOTION_CAR.size)
            continue
        x, z = xz(max(0.0, c.dist()))
        out += P.MOTION_CAR.pack(x, 0.0, z, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    return bytes(out)


def pack_status(cars, uid, t, frame):
    out = bytearray(header(P.CAR_STATUS, uid, t, frame))
    for i in range(P.NUM_CARS):
        c = cars.get(i)
        if not c:
            out += bytes(P.STATUS.size)
            continue
        left = max(0.0, c.laps_total - (c.total / TRACK_LEN))
        out += P.STATUS.pack(0, 0, 1, 56, 0, c.fuel, 110.0, c.fuel / 1.6 - left, 13000, 4000,
                             8, 0, 0, 17, 17, c.tyre_age, 0, 0.0, 0.0, 3.0e6, 1,
                             0.0, 0.0, 0.0, 0)
    return bytes(out)


def pack_damage(cars, uid, t, frame):
    out = bytearray(header(P.CAR_DAMAGE, uid, t, frame))
    for i in range(P.NUM_CARS):
        c = cars.get(i)
        block = bytearray(P.DAMAGE_STRIDE)
        if c:
            struct.pack_into('<4f', block, 0, *c.wear)
        out += block
    return bytes(out)


def pack_session(uid, t, frame, session_type, total_laps, ai):
    buf = bytearray(P.PACKET_SIZES[P.SESSION])
    buf[0:29] = header(P.SESSION, uid, t, frame)
    struct.pack_into('<BbbBHBbBHHB', buf, 29, 0, 32, 24, total_laps, int(TRACK_LEN),
                     session_type, 17, 0, 1800, 3600, 80)
    buf[669] = ai
    struct.pack_into('<ff', buf, 745, TRACK_LEN / 3, 2 * TRACK_LEN / 3)
    return bytes(buf)


def pack_participants(cars, uid, t, frame):
    out = bytearray(header(P.PARTICIPANTS, uid, t, frame))
    out += bytes([len(cars)])
    for i in range(P.NUM_CARS):
        c = cars.get(i)
        if not c:
            out += bytes(P.PARTICIPANT.size)
            continue
        out += P.PARTICIPANT.pack(1 if c.ai else 0, i, 0, i % 10, 0, i + 1, 0,
                                  c.name.encode('utf-8')[:31], 1, 1, 0, 0, 0, bytes(12))
    return bytes(out)


def make_cars(mode, laps=10):
    cars = {0: SimCar(0, 'Ty', 0.93, False, start_offset=0 if mode != 'race' else 30, laps=laps)}
    names = ['Verstappen', 'Norris', 'Leclerc', 'Piastri', 'Hamilton']
    for k, n in enumerate(names, start=1):
        off = 0 if mode != 'race' else 30 - k * 12
        cars[k] = SimCar(k, n, 0.9 + 0.025 * (len(names) - k), True, start_offset=off, laps=laps)
    return cars


def generate(mode='quali', laps=6, hz=20, ai=95, seed=1):
    """Generátor paketů (pro testy i odesílání). Yielduje (sim_time, bytes)."""
    random.seed(seed)
    cars = make_cars(mode, laps)
    uid = random.getrandbits(63)
    st = 15 if mode == 'race' else (18 if mode == 'tt' else 7)
    dt = 1.0 / hz
    t = 0.0
    frame = 0
    yield t, pack_session(uid, t, frame, st, laps, ai)
    yield t, pack_participants(cars, uid, t, frame)
    while cars[0].lap <= laps:
        for c in cars.values():
            c.step(dt)
        t += dt
        frame += 1
        order = sorted(cars.values(), key=lambda c: -c.total)
        positions = {c.idx: k + 1 for k, c in enumerate(order)}
        yield t, pack_motion(cars, uid, t, frame)
        yield t, pack_telemetry(cars, uid, t, frame)
        yield t, pack_lap(cars, uid, t, frame, positions)
        if frame % 5 == 0:
            yield t, pack_status(cars, uid, t, frame)
        if frame % hz == 0:
            yield t, pack_damage(cars, uid, t, frame)
            yield t, pack_session(uid, t, frame, st, laps, ai)
        if frame % (hz * 5) == 0:
            yield t, pack_participants(cars, uid, t, frame)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=20777)
    ap.add_argument('--speed', type=float, default=1.0, help='zrychlení času')
    ap.add_argument('--mode', choices=['quali', 'race', 'tt'], default='quali')
    ap.add_argument('--laps', type=int, default=10)
    ap.add_argument('--ai', type=int, default=95)
    args = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start = time.time()
    print('Simuluji %s, %d kol, AI %d → %s:%d' % (args.mode, args.laps, args.ai,
                                                args.host, args.port))
    for t, pkt in generate(args.mode, args.laps, ai=args.ai, seed=int(start)):
        wait = start + t / args.speed - time.time()
        if wait > 0:
            time.sleep(wait)
        sock.sendto(pkt, (args.host, args.port))
    print('Hotovo.')


if __name__ == '__main__':
    main()
