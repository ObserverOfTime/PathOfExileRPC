#!/usr/bin/env python3

import asyncio
import atexit
import json
import os
import logging
import sys
import time

from poeRPC import PoeRPC

logging.basicConfig(level=logging.DEBUG)

os.chdir(os.path.dirname(__file__) or '.')


class Launcher:
    def __init__(self):
        self.logger = logging.getLogger('PoE RPC')
        try:
            with open('config.json') as f:
                js = json.load(f)
        except Exception:
            js = {'name': '', 'private': False, 'sessid': ''}
        if not js['name']:
            js['name'] = input('Please enter your path of exile account name: ')
            while 1:
                reply = input('Is your path of exile profile private ' +
                              'or is character tab hidden? (y/n): ')
                if reply in ('y', 'n'):
                    break
            if reply == 'y':
                while 1:
                    sessid = input('Input your POESESSID here: ')
                    confirm = input('Confirm? (y/n)')
                    if confirm in ('y', 'n'):
                        if confirm == 'n':
                            continue
                        else:
                            break
                js['sessid'] = sessid
                js['private'] = True
            else:
                js['private'] = False
        self.loop = asyncio.get_event_loop()
        cookies = None
        if js['private']:
            cookies = {'POESESSID': js['sessid']}
        self.cl = PoeRPC(self.loop, js['name'], cookies, self.logger)

    def run(self):
        try:
            self.loop.create_task(self.cl.init())
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.logger.info('Process Interrupted.')
        finally:
            self.quit()

    def quit(self):
        self.cl.do_quit()
        if hasattr(self.loop, 'shutdown_asyncgens'):
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.close()
        self.logger.info('PathOfExileRPC successfully shutdown.')


if __name__ == '__main__':
    Launcher().run()
