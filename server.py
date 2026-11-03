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
    ap.add_argument('--voice', action='store_true',
                    help='hlas na Macu: mikrofon + Whisper + český neural hlas (setup_mac.sh)')
    ap.add_argument('--mic', default=None, help='mikrofon (číslo nebo část názvu), viz --list-mics')
    ap.add_argument('--list-mics', action='store_true', help='vypíše mikrofony a skončí')
    args = ap.parse_args()
    if args.list_mics:
        from engineer.voice_mac import list_mics
        list_mics()
        return
    storage = Storage(args.data)
    engine = Engine(storage)
    if args.voice:
        from engineer.voice_mac import MacVoice
        missing = MacVoice.check()
        if missing:
            print('⚠️  Hlas na Macu nejde spustit, chybí: %s' % ', '.join(missing))
            print('    Spusť jednou:  bash setup_mac.sh   (a pak bash start_mac.sh)')
        else:
            mic = int(args.mic) if args.mic and args.mic.isdigit() else args.mic
            MacVoice(engine, mic=mic).start()
    udp = args.udp or engine.settings.get('udp_port', 20777)
    http = args.http or engine.settings.get('http_port', 8080)
    try:
        web.run(engine, os.path.join(HERE, 'web'), http, udp)
    except KeyboardInterrupt:
        print('\nUkončeno.')


if __name__ == '__main__':
    main()
