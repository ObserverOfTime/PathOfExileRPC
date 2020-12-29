import aiohttp
import asyncio
import json
import sys
import time
import aiohttp

from enum import Enum
from psutil import process_iter
from pypresence import Presence
from pypresence.exceptions import InvalidPipe

CLIENT_ID = '466251900157820929'


class LogEvents(Enum):
    LOGIN = 0
    LOGOUT = 1
    AREA = 2


class PoeRPC:
    def __init__(self, loop, account_name, cookies, logger):
        self.rpc = Presence(CLIENT_ID, pipe=0, loop=loop)
        self.cookies = cookies
        self.log_path = None
        self.on = True
        self.loop = loop
        self.logger = logger
        self.last_location = None
        self.last_latest_message = ''
        self.last_event = LogEvents.LOGOUT
        self.afk = False
        self.dnd = False
        self.afk_message = ''
        self.dnd_message = ''
        self.account_name = account_name
        self.current_rpc = {}
        self.locations = {}
        self.quit = False
        self.logger.debug('Loading areas')
        with open('areas.json') as f:
            areas = json.load(f)
        self.logger.debug('Loaded areas')
        self.locations.update(areas)
        self.logger.debug('Loading maps')
        with open('maps.json') as f:
            self.maps = json.load(f)
        self.logger.debug('Loaded maps')

        self.logger.debug('Loading icon refs')
        with open('available_icons.json') as f:
            self.icons = json.load(f)
        self.logger.debug('Loaded icon refs')

        self.logger.debug('Loading xp ref')
        with open('experience.json') as f:
            self.xp = json.load(f)
        self.logger.debug('Loaded xp ref')

    def do_quit(self):
        self.quit = True

    async def check_poe(self):
        """
        Tries to check if PoE is running every 15sec, clears RPC if not.
        Waits for PoE to start again, calls init again with restart as True
        """
        while 1:
            if self.quit:
                break
            poe = self.get_path()
            if not poe:
                if self.on:
                    self.logger.debug('PoE no longer open, setting on to false')
                    self.on = False
                    self.rpc.clear()
            else:
                if not self.on:
                    self.logger.debug(f'Found launched PoE at {poe} ' +
                                      'setting on to True and restarting init')
                    self.on = True
                    self.loop.create_task(self.init(restart=True))
            await asyncio.sleep(15)

    def update_rpc(self, field, value):
        """
        Basically just neater way to indicate
        updating of each field for rpc dict
        """
        self.current_rpc[field] = value

    def submit_update(self):
        """
        rpc.update takes in everything as a kwarg,
        using splat operator the current_rpc dict
        is turned into kwargs and passed to update
        """
        self.logger.debug(
            f'Submitting rpc update with content: {self.current_rpc}')
        self.rpc.update(**self.current_rpc)

    async def fetch_char(self):
        """
        Calls to get-characters at poe API,
        interprets response and updates rpc
        """
        async with self.ses.get('https://www.pathofexile.com/' +
                                'character-window/get-characters?' +
                                f'accountName={self.account_name}') as resp:
            js = await resp.json()
        for char in js:
            # js is still a valid json on error,
            # if you try to iterate over the items,
            # compared to a valid request
            # it is an str and not a dict, thus this works.
            if char == '':
                self.logger.info('Your character tab is set to be hidden ' +
                                 'or your profile is private\nchange private ' +
                                 'to true in config.json and set the value ' +
                                 'for sessid as your POESESSID\n ' +
                                 'Alternatively you can also make your ' +
                                 'character tab or profile public.')
                exit()
            if 'lastActive' in char.keys():
                break
        asc = char['class']
        level = char['level']
        name = char['name']
        xp = char['experience']
        # Calculate percent to next level
        # XP json contains only the total xp,
        # so it must be subtracted from the xp of next level
        # and then calculated with difference of current xp
        max_cur_xp = int(self.xp[str(level)].replace(',', ''))
        needed_xp = int(self.xp[str(min(level + 1, 100))].replace(',', ''))
        diff1 = needed_xp - xp
        diff2 = needed_xp - max_cur_xp
        perc = round(((diff2 - diff1) / diff2) * 100)
        lg_text = f'{name} | Level {level} {asc}\n'
        if level != 100:
            lg_text += f'{perc}% to Level {level + 1}'
        self.update_rpc('large_image', asc.lower())
        self.update_rpc('large_text', lg_text)
        self.update_rpc('state', f'in {char["league"]} league')

    @staticmethod
    def get_path():
        proc = next((p for p in process_iter() if
                     'PathOfExile' in p.name()), None)
        if proc:
            return proc.cwd()
        return None

    @staticmethod
    def fix_names(name):
        """
        Icon names on discord RPC follow a pretty standard pattern,
        no special chars, commas, apostrophes, spaces or unicode chars.
        Nothing other than maelstrom has a unicode char,
        so a chain of replaces just works as well.
        """
        return name.replace(',', '') \
            .replace('\'', '') \
            .replace('ö', 'o') \
            .replace(' ', '_').lower()

    async def fetch_area_data(self, name):
        """
        Runs Area name through a multitude of filters
        to conclude which area the player is in,
        then finds the appropriate icon and then update rpc dict
        """
        loc = None
        if 'hideout' in name.lower():
            loc = {'name': name}
            img = 'hideout'
        if not loc:
            for map in self.maps:
                if name in map['name']:
                    loc = map
                    fixed_name = self.fix_names(name)
                    if fixed_name in self.icons:
                        img = fixed_name
                    elif int(map['tier']) < 6:
                        img = 'white'
                    elif 6 <= int(map['tier']) <= 10:
                        img = 'yellow'
                    elif int(map['tier']) > 10:
                        img = 'red'
                    elif name.lower() in self.locations['guardians']:
                        if 'Phoenix' in name:
                            img = 'phoenix'
                        elif 'Minotaur' in name:
                            img = 'minotaur'
                        elif 'Hydra' in name:
                            img = 'hydra'
                        else:
                            img = 'chimera'
                    elif name in 'Vaal Temple':
                        img = 'vaal_temple'
                    break
        if not loc:
            for town in self.locations['towns']:
                if name in town['name']:
                    loc = town
                    img = 'town'
                    break
        if not loc:
            for part in self.locations['lab_rooms']:
                if part in name:
                    loc = {'name': 'The Lord\'s Labyrinth'}
                    img = 'lab'
                    break

        if not loc:
            if 'Azurite Mine' in name:
                loc = {'name': 'Azurite Mine'}
                img = 'mine'

        if not loc:
            if 'Menagerie' in name or name in self.locations['bestiary_bosses']:
                loc = {'name': name}
                img = 'menagerie'

        if not loc:
            if 'absence of value' in name.lower():
                loc = {'name': name}
                img = 'elder'

        if not loc:
            for guardian in self.locations['elder_guardians']:
                if name in self.locations['elder_guardians'][guardian]:
                    loc = {'name': f'{name} - {guardian}'}
                    img = guardian.split()[1].lower()
                    break

        if not loc:
            loc = {'name': name}
            img = 'waypoint'

        small_text = loc['name']
        timestamp = round(time.time())
        self.update_rpc('small_text', small_text)
        self.update_rpc('small_image', img)
        self.update_rpc('start', timestamp)
        if 'tier' in loc.keys():
            self.update_rpc(
                'details', f'{loc["name"]} | Tier: {loc["tier"]} | ')
        elif 'details' in self.current_rpc:
            if 'Tier' in self.current_rpc['details']:
                del self.current_rpc['details']

    async def handle_log_event(self, log):
        """
        On the event of a log update, handle_log_event is called.
        The log is passed to it and it iters through messages
        to decide what methods to call for which event
        """
        messages = reversed(log.split('\n'))
        event = None
        ping = None
        for ind, message in enumerate(messages):
            if message == self.last_latest_message:
                self.logger.debug(
                    f'Reached last message from previous update: {message}')
                break
            elif 'You have entered' in message:
                loc = message.split('You have entered ')[1].replace('.', '')
                self.logger.info(f'Entered {loc}')
                if self.last_location != loc and loc != 'Arena':
                    event = LogEvents.AREA
                    self.last_location = loc
                else:
                    return
                break
            elif 'Async connecting' in message \
                    or 'Abnormal disconnect' in message:
                self.logger.info('On character selection')
                self.last_location = None
                event = LogEvents.LOGOUT
                break
            elif 'Connect time' in message:
                ping = message.split('was ')[1]
                self.logger.info(f'Ping to instance was: {ping}')
            elif 'AFK mode is now' in message:
                if message.split('AFK mode is now O')[1][0] == 'N':
                    self.afk = True
                    self.afk_message = message.split('Autoreply "')[1][:-1]
                    self.logger.info(f'AFK: {self.afk_message}')
                else:
                    self.afk = False
                    self.afk_message = ''
                    self.logger.info('AFK: Turned Off')
            elif 'DND mode is now' in message:
                if message.split('DND mode is now O')[1][0] == 'N':
                    self.dnd = True
                    self.dnd_message = message.split('Autoreply "')[1][:-1]
                    self.logger.info(f'DND: {self.afk_message}')
                else:
                    self.dnd = False
                    self.dnd_message = ''
                    self.logger.info('DND: Turned Off')
        self.last_latest_message = log.split('\n')[-1] or log.split('\n')[-2]
        if event != LogEvents.LOGOUT:
            await self.fetch_char()
        if event == LogEvents.AREA:
            await self.fetch_area_data(loc)
        elif event == LogEvents.LOGOUT:
            self.current_rpc = {}
            self.update_rpc('large_image', 'login_screen')
            self.update_rpc('state', 'On Character Selection')

        def update_dnd():
            self.update_rpc('details', f'DND: {self.dnd_message}')

        def update_afk():
            self.update_rpc('details', f'AFK: {self.afk_message}')

        if not self.afk and 'AFK' in \
                self.current_rpc.get('details', '') \
                or not self.dnd and 'DND' in \
                self.current_rpc.get('details', ''):
            self.current_rpc.pop('details')

        if self.dnd and self.afk and 'AFK' \
                not in self.current_rpc.get('details', ''):
            update_afk()
        elif self.afk and 'AFK' not in self.current_rpc.get('details', ''):
            update_afk()
        elif self.dnd and 'DND' not in self.current_rpc.get('details', ''):
            update_dnd()

        if ping:
            state = self.current_rpc.get('state', '')
            if 'Ping' not in state:
                self.update_rpc(
                    'state', f'{state}{" | " if state else ""}Ping: {ping}')
            else:
                current_ping = state.split('Ping: ')[1]
                state = state.replace(current_ping, ping)
                self.update_rpc('state', state)
        self.submit_update()
        self.last_event = event

    async def monitor_log(self):
        """
        Monitors if log file has changed by checking last message,
        passes log to handler if yes, tries again in 5 seconds
        """
        self.logger.info('Log monitor has started')
        while 1:
            if self.quit:
                break
            if not self.on:
                self.logger.info('Log monitor now sleeping')
                await self.ses.close()
                break
            with open(self.log_path, encoding='utf-8') as f:
                log = f.read()
            # log = log.encode('utf-8')
            new_last = log.split('\n')[-1] or log.split('\n')[-2]
            if self.last_latest_message != new_last:
                self.logger.debug(f'Log update observed: {new_last}')
                await self.handle_log_event(log)
            await asyncio.sleep(5)

    @staticmethod
    async def get_poe():
        """
        When initializing, keeps trying to find a launched
        Path Of Exile before initializing the monitors
        """
        while 1:
            poe = PoeRPC.get_path()
            if not poe:
                await asyncio.sleep(10)
            else:
                return poe

    async def init(self, restart=False):
        """
        Standard method for initialization called by launcher,
        sets up the aiohttp session and starts monitor loops
        on confirmation from get_poe
        """
        try:
            await self.rpc.connect()
        except Exception:
            self.logger.info(
                'Discord not open, waiting for discord to launch...')
            while 1:
                if self.quit:
                    break
                try:
                    await self.rpc.connect()
                    self.logger.info('Discord launched')
                    break
                except Exception:
                    pass
                await asyncio.sleep(5)

        self.logger.info('Waiting for path of exile to launch...')
        poe = await self.get_poe()
        self.log_path = f'{poe}/logs/Client.txt'
        self.logger.info(f'Found path of exile log at {self.log_path}')
        self.ses = aiohttp.ClientSession(cookies=self.cookies)
        if not restart:
            self.loop.create_task(self.check_poe())
        self.loop.create_task(self.monitor_log())
