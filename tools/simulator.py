#!/usr/bin/env python3
"""Simulátor UDP telemetrie F1 25 – na testování bez Xboxu.

Vytváří syntetickou trať s 8 zatáčkami, hráče a několik AI aut a posílá pakety
ve formátu F1 25 (2025) nebo 2026 Season Pack (2026, active aero, overtake mode,
ERS). Hráč dělá náhodné chyby (pozdní plyn, brzká brzda, nevyužitý straight mode…),
takže inženýr má co analyzovat.

    python3 tools/simulator.py                  # posílá na 127.0.0.1:20777
    python3 tools/simulator.py --speed 4        # 4× rychleji než reálný čas
    python3 tools/simulator.py --mode race      # závod (mezery, palivo, gumy)
    python3 tools/simulator.py --format 2026    # regulace 2026
    python3 tools/simulator.py --button 2       # jen stiskne UDP Action 2 (test tlačítek)
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
ERS_CAP = 4.0e6
HARVEST_LIMIT = 8.5e6


def aero_zones():
    """Active aero zóny = delší rovinky mezi zatáčkami (vzdálenosti v m)."""
    zones = []
    apexes = [c[0] for c in CORNERS]
    for k, a in enumerate(apexes):
        b = apexes[(k + 1) % len(apexes)] + (TRACK_LEN if k == len(apexes) - 1 else 0)
        start, end = a + 150, b - 250
        if end - start > 300:
            zones.append((start, end))
    return zones


AERO_ZONES = aero_zones()


def in_zone(d):
    for a, b in AERO_ZONES:
        if a <= d <= b or a <= d + TRACK_LEN <= b:
            return True
    return False


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
        self.ers = ERS_CAP * 0.8
        self.harvested = 0.0
        self.deployed = 0.0
        self.aero_mode = 0
        self.ot_available = 0
        self.ot_active = 0
        self.ot_timer = 0.0
        self.gap_front = 0
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
        # hráč občas pozdě zapne straight mode (využije jen část zóny)
        self.straight_use = 1.0 if self.ai else random.choice([1.0, 1.0, 0.9, 0.6])
        self.harvested = 0.0
        self.deployed = 0.0

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
        # 2026: active aero, ERS, overtake
        self.aero_mode = 0
        dd = max(0.0, d)
        for a, b in AERO_ZONES:
            for off in (0, TRACK_LEN):
                if a <= dd + off <= b and (dd + off - a) >= (1 - self.straight_use) * (b - a):
                    self.aero_mode = 1
        if self.throttle == 0 and self.harvested < HARVEST_LIMIT:
            h = 400000 * dt
            self.harvested += h
            self.ers = min(ERS_CAP, self.ers + h)
        elif self.throttle >= 1.0 and self.ers > 0:
            u = (25000 if not self.ot_active else 120000) * dt
            u = min(u, self.ers)
            self.ers -= u
            self.deployed += u
        self.ot_available = 1 if (0 < self.gap_front < 1000 and self.total > 0) else 0
        if self.ot_available and not self.ot_active and in_zone(dd) and random.random() < 0.02:
            self.ot_active, self.ot_timer = 1, 6.0
        if self.ot_active:
            self.ot_timer -= dt
            if self.ot_timer <= 0:
                self.ot_active = 0
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


class Packer:
    def __init__(self, fmt, uid):
        self.L = P.LAYOUTS[fmt]
        self.fmt = fmt
        self.uid = uid

    def header(self, pid, t, frame, player=0):
        return P.HEADER.pack(self.fmt, 25, 1, 0, 1, pid, self.uid, t, frame, frame, player, 255)

    def lap(self, cars, t, frame, positions):
        out = bytearray(self.header(P.LAP_DATA, t, frame))
        for i in range(self.L.cars):
            c = cars.get(i)
            if not c:
                out += bytes(P.LAP.size)
                continue
            pos = positions[i]
            ahead = [x for x in cars.values() if positions[x.idx] == pos - 1]
            gap = 0
            if ahead:
                gap = int(max(0.0, (ahead[0].total - c.total)) / max(c.speed / 3.6, 1) * 1000)
            c.gap_front = gap
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

    def telemetry(self, cars, t, frame):
        T = self.L.telemetry
        out = bytearray(self.header(P.CAR_TELEMETRY, t, frame))
        for i in range(self.L.cars):
            c = cars.get(i)
            if not c:
                out += bytes(T.size)
                continue
            out += T.pack(int(c.speed), c.throttle, 0.0, c.brake, 0, c.gear(),
                          int(6000 + c.speed * 30), 0, 50, 0,
                          *([500] * 4), *([95] * 4), *([100] * 4), 105,
                          *([22.5] * 4), *([0] * 4))
        out += struct.pack('<BBb', 255, 255, 0)
        return bytes(out)

    def telemetry2(self, cars, t, frame):
        out = bytearray(self.header(P.CAR_TELEMETRY_2, t, frame))
        for i in range(24):
            c = cars.get(i)
            if not c:
                out += bytes(P.TELEMETRY2.size)
                continue
            dd = max(0.0, c.dist())
            avail = 1 if in_zone(dd) else 0
            out += P.TELEMETRY2.pack(c.aero_mode, avail, 0 if avail else 120,
                                     c.ot_available, c.ot_active,
                                     0 if c.ot_available else 300, 1, 0)
        return bytes(out)

    def motion(self, cars, t, frame):
        M = self.L.motion
        out = bytearray(self.header(P.MOTION, t, frame))
        for i in range(self.L.cars):
            c = cars.get(i)
            if not c:
                out += bytes(M.size)
                continue
            x, z = xz(max(0.0, c.dist()))
            out += M.pack(x, 0.0, z, *([0] * (len(M.format) - 4)))
        return bytes(out)

    def status(self, cars, t, frame):
        S = self.L.status
        out = bytearray(self.header(P.CAR_STATUS, t, frame))
        for i in range(self.L.cars):
            c = cars.get(i)
            if not c:
                out += bytes(S.size)
                continue
            left = max(0.0, c.laps_total - (c.total / TRACK_LEN))
            head = [0, 0, 1, 56, 0, c.fuel, 110.0, c.fuel / 1.6 - left, 13000, 4000,
                    8, 0, 0, 17, 17, c.tyre_age, 0, 0.0, 0.0, c.ers, 3 if c.ot_active else 1,
                    c.harvested, 0.0]
            if self.fmt == 2026:
                head += [HARVEST_LIMIT]
            out += S.pack(*(head + [c.deployed, 0]))
        return bytes(out)

    def damage(self, cars, t, frame):
        out = bytearray(self.header(P.CAR_DAMAGE, t, frame))
        for i in range(self.L.cars):
            c = cars.get(i)
            block = bytearray(P.DAMAGE_STRIDE)
            if c:
                struct.pack_into('<4f', block, 0, *c.wear)
            out += block
        return bytes(out)

    def session(self, t, frame, session_type, total_laps, ai):
        buf = bytearray(self.L.sizes[P.SESSION])
        buf[0:29] = self.header(P.SESSION, t, frame)
        struct.pack_into('<BbbBHBbBHHB', buf, 29, 0, 32, 24, total_laps, int(TRACK_LEN),
                         session_type, 17, 0, 1800, 3600, 80)
        buf[669] = ai
        struct.pack_into('<ff', buf, 745, TRACK_LEN / 3, 2 * TRACK_LEN / 3)
        if self.fmt == 2026:
            buf[753] = 0
            buf[754] = len(AERO_ZONES)
            for k, (a, b) in enumerate(AERO_ZONES[:8]):
                struct.pack_into('<ff', buf, 755 + k * 8, (a / TRACK_LEN) % 1.0,
                                 (b / TRACK_LEN) % 1.0)
        return bytes(buf)

    def participants(self, cars, t, frame):
        PT = self.L.participant
        out = bytearray(self.header(P.PARTICIPANTS, t, frame))
        out += bytes([len(cars)])
        for i in range(self.L.cars):
            c = cars.get(i)
            if not c:
                out += bytes(PT.size)
                continue
            out += PT.pack(1 if c.ai else 0, i, 0, i % 10, 0, i + 1, 0,
                           c.name.encode('utf-8')[:31], 1, 1, 0, 0, 0, bytes(12))
        return bytes(out)

    def event(self, code, t, frame, payload=b''):
        buf = bytearray(45)
        buf[0:29] = self.header(P.EVENT, t, frame)
        buf[29:33] = code.encode('ascii')
        buf[33:33 + len(payload)] = payload
        return bytes(buf)

    def buttons(self, status, t, frame):
        return self.event('BUTN', t, frame, struct.pack('<I', status))


# zpětně kompatibilní funkce (formát 2025)
def pack_session(uid, t, frame, session_type, total_laps, ai, fmt=2025):
    return Packer(fmt, uid).session(t, frame, session_type, total_laps, ai)


def make_cars(mode, laps=10):
    cars = {0: SimCar(0, 'Ty', 0.93, False, start_offset=0 if mode != 'race' else 30, laps=laps)}
    names = ['Verstappen', 'Norris', 'Leclerc', 'Piastri', 'Hamilton']
    for k, n in enumerate(names, start=1):
        off = 0 if mode != 'race' else 30 - k * 12
        cars[k] = SimCar(k, n, 0.9 + 0.025 * (len(names) - k), True, start_offset=off, laps=laps)
    return cars


def generate(mode='quali', laps=6, hz=20, ai=95, seed=1, fmt=2025):
    """Generátor paketů (pro testy i odesílání). Yielduje (sim_time, bytes)."""
    random.seed(seed)
    cars = make_cars(mode, laps)
    pk = Packer(fmt, random.getrandbits(63))
    st = 15 if mode == 'race' else (18 if mode == 'tt' else 7)
    dt = 1.0 / hz
    t = 0.0
    frame = 0
    yield t, pk.session(t, frame, st, laps, ai)
    yield t, pk.participants(cars, t, frame)
    while cars[0].lap <= laps:
        for c in cars.values():
            c.step(dt)
        t += dt
        frame += 1
        order = sorted(cars.values(), key=lambda c: -c.total)
        positions = {c.idx: k + 1 for k, c in enumerate(order)}
        yield t, pk.motion(cars, t, frame)
        yield t, pk.telemetry(cars, t, frame)
        if fmt == 2026:
            yield t, pk.telemetry2(cars, t, frame)
        yield t, pk.lap(cars, t, frame, positions)
        if frame % 5 == 0:
            yield t, pk.status(cars, t, frame)
        if frame % hz == 0:
            yield t, pk.damage(cars, t, frame)
            yield t, pk.session(t, frame, st, laps, ai)
        if frame % (hz * 5) == 0:
            yield t, pk.participants(cars, t, frame)
        if fmt == 2026 and mode == 'race' and frame == hz * 3:
            yield t, pk.event('OVEN', t, frame)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=20777)
    ap.add_argument('--speed', type=float, default=1.0, help='zrychlení času')
    ap.add_argument('--mode', choices=['quali', 'race', 'tt'], default='quali')
    ap.add_argument('--laps', type=int, default=10)
    ap.add_argument('--ai', type=int, default=95)
    ap.add_argument('--format', type=int, choices=[2025, 2026], default=2026)
    ap.add_argument('--button', type=int, default=None,
                    help='pošle jen stisk UDP Action N (1-12) a skončí')
    args = ap.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.button:
        pk = Packer(args.format, 1)
        sock.sendto(pk.buttons(P.UDP_ACTION_BITS[args.button], 0.0, 0), (args.host, args.port))
        sock.sendto(pk.buttons(0, 0.0, 1), (args.host, args.port))
        print('Stisknuto UDP Action %d' % args.button)
        return
    start = time.time()
    print('Simuluji %s, %d kol, AI %d, formát %d → %s:%d' % (
        args.mode, args.laps, args.ai, args.format, args.host, args.port))
    for t, pkt in generate(args.mode, args.laps, ai=args.ai, seed=int(start), fmt=args.format):
        wait = start + t / args.speed - time.time()
        if wait > 0:
            time.sleep(wait)
        sock.sendto(pkt, (args.host, args.port))
    print('Hotovo.')


if __name__ == '__main__':
    main()
