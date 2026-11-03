#!/usr/bin/env python3
"""F1 25 AI inženýr – spuštění: python3 server.py"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engineer.storage import Storage  # noqa: E402
from engineer.state import Engine  # noqa: E402
from engineer import web  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description='F1 25 AI závodní inženýr')
    ap.add_argument('--udp', type=int, default=None, help='UDP port (výchozí 20777)')
    ap.add_argument('--http', type=int, default=None, help='HTTP port (výchozí 8080)')
    ap.add_argument('--data', default=os.path.join(HERE, 'data'), help='složka s daty')
    args = ap.parse_args()
    storage = Storage(args.data)
    engine = Engine(storage)
    udp = args.udp or engine.settings.get('udp_port', 20777)
    http = args.http or engine.settings.get('http_port', 8080)
    try:
        web.run(engine, os.path.join(HERE, 'web'), http, udp)
    except KeyboardInterrupt:
        print('\nUkončeno.')


if __name__ == '__main__':
    main()
