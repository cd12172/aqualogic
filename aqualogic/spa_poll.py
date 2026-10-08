# -*- coding: utf-8 -*-
"""Faster spa temperature readings.

The panel only reports the spa temperature on one of its default display
screens, and on its own it shows each screen for ~6 s, so a new Spa Temp
reading arrives only every ~42 s. While the spa is running this poller
presses RIGHT to step through the default screens so a full cycle (and a
fresh Spa Temp reading) takes about `interval` seconds.

Safety:
 - The only key it can ever send is RIGHT (hard-coded in
   AquaLogic.queue_poll_right()); there is no key parameter.
 - It only presses while the operating mode is SPA (SPA on, POOL off,
   neither flashing), the filter is on, and the panel is not in service
   or system-off mode. Unknown mode (no LED frame yet) means no press.
 - It only presses while the LCD shows one of the known default-menu
   screens below. Any other text (settings menus, Check System, ...)
   disarms it.
 - Once disarmed (startup, unknown screen, wrong mode, or a key press
   from a person/HA/web keypad/other bus device), it re-arms only after
   it has seen the panel advance by itself from one known default screen
   to another with no key pressed. Settings menus never auto-advance,
   so this proves the panel is back in the default display menu.
 - The guard is checked again right before the queued frame goes on the
   bus, and the frame is dropped if it no longer passes.
"""

import logging
import re
import threading
import time

from .states import States

_LOGGER = logging.getLogger(__name__)

# Default-menu screens seen in spa mode (notes/aqualogic-default-menu.md).
# Matched against the LCD text with whitespace collapsed.
DEFAULT_SCREENS = [
    ('spa_temp', re.compile(r'^Spa Temp -?\d+\S*[FC]$')),
    ('air_temp', re.compile(r'^Air Temp -?\d+\S*[FC]$')),
    ('spa_chlorinator', re.compile(r'^Spa Chlorinator \d+%$')),
    ('salt_level', re.compile(r'^Salt Level \d+(\.\d+)? (PPM|g/L)$')),
    # Text depends on heater mode (HA's spa thermostat switches it).
    ('heater1', re.compile(r'^Heater1 (Auto Control|Manual Off|Manual On)$')),
    ('filter_speed', re.compile(r'^Filter Speed \d+% Spa Mode$')),
    # Colon blinks: "6:35P" / "6 35P"
    ('day_time', re.compile(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|'
                            r'Saturday|Sunday) \d{1,2}[: ]\d{2}[AP]$')),
]


def screen_id(text):
    """Return the default-screen name for LCD text, or None if unknown."""
    if not text:
        return None
    norm = ' '.join(text.replace('\x00', ' ').split())
    for name, pattern in DEFAULT_SCREENS:
        if pattern.match(norm):
            return name
    return None


def is_spa_mode(states, flashing_states):
    """True only when the panel is definitely in SPA mode with the filter
    running. `states`/`flashing_states` are the raw LED bitmasks."""
    if not states & States.SPA or states & States.POOL:
        return False
    if flashing_states & (States.SPA | States.POOL):
        return False   # valves moving / mode changing
    if not states & States.FILTER:
        return False
    if states & (States.SERVICE | States.SYSTEM_OFF):
        return False
    return True


class SpaTempPoller():
    """Decides when to press RIGHT. Pure logic driven by on_display(),
    on_external_key() and tick(); `clock` is injectable for tests."""

    SCREEN_COUNT = len(DEFAULT_SCREENS)
    MIN_PRESS_GAP = 1.0        # seconds between our presses
    QUIET_BEFORE_REARM = 4.0   # no key at all for this long before an
                               # auto-advance counts as proof

    def __init__(self, panel, interval=10, pause_after_user=60,
                 clock=time.monotonic):
        self._panel = panel
        self.interval = float(interval)
        self.pause_after_user = float(pause_after_user)
        self._clock = clock
        self._lock = threading.Lock()
        self.enabled = True
        self.armed = False
        self._screen = None
        self._screen_since = clock()
        self._last_our_press = -1e9
        self._last_external_key = -1e9

    @property
    def dwell(self):
        """Seconds to leave each screen up: one full cycle per interval."""
        return max(self.MIN_PRESS_GAP, self.interval / self.SCREEN_COUNT)

    def _disarm(self, reason):
        if self.armed:
            _LOGGER.info('Spa temp poll: paused (%s)', reason)
        self.armed = False

    def _mode_ok(self):
        return is_spa_mode(self._panel._states, self._panel._flashing_states)

    def on_display(self, text):
        """Called from the reader thread for every LCD update."""
        with self._lock:
            now = self._clock()
            new = screen_id(text)
            if new is None:
                if self.armed:
                    _LOGGER.info('Spa temp poll: unknown screen %r',
                                 ' '.join(text.split()))
                self._disarm('unknown screen')
            elif (new != self._screen and self._screen is not None and
                  not self.armed and self._mode_ok() and
                  now - self._last_our_press >= self.QUIET_BEFORE_REARM and
                  now - self._last_external_key >= max(
                      self.QUIET_BEFORE_REARM, self.pause_after_user)):
                # Panel advanced by itself between two default screens.
                self.armed = True
                _LOGGER.info('Spa temp poll: armed (auto-advance %s -> %s)',
                             self._screen, new)
            if new != self._screen:
                self._screen_since = now
            self._screen = new

    def on_external_key(self):
        """Any key not sent by this poller (MQTT, web keypad, set_state,
        or a key frame from another device on the bus)."""
        with self._lock:
            self._last_external_key = self._clock()
            self._disarm('key press from user/HA')

    def _panel_busy(self):
        # Back off while any other key is queued or a state change
        # (set_state) is still being verified.
        busy = getattr(self._panel, 'busy', None)
        return busy() if busy is not None else False

    def safe_to_press(self):
        """The guard: checked when deciding and again at send time."""
        return (self.enabled and self.armed and self._screen is not None and
                self._mode_ok() and not self._panel_busy() and
                self._clock() - self._last_external_key >=
                self.pause_after_user)

    def tick(self):
        """Press RIGHT if due and safe. Returns True if a press was queued."""
        with self._lock:
            now = self._clock()
            if not self._mode_ok():
                self._disarm('not in spa mode')
                return False
            if not self.safe_to_press():
                return False
            if now - self._screen_since < self.dwell:
                return False
            if now - self._last_our_press < self.dwell:
                return False
            self._last_our_press = now
        self._panel.queue_poll_right(self.safe_to_press)
        return True

    def run(self):
        """Thread body. Never raises: an error here must not stop the
        service from reporting temperatures."""
        _LOGGER.info('Spa temp poll: started (interval %.0fs, dwell %.1fs)',
                     self.interval, self.dwell)
        while True:
            try:
                self.tick()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception('Spa temp poll: error (ignored)')
                time.sleep(5)
            time.sleep(0.2)

    def start(self):
        thread = threading.Thread(target=self.run, name='spa-temp-poll',
                                  daemon=True)
        thread.start()
        return thread
