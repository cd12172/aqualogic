"""Unit tests for the spa temp poller guard. No hardware needed:
`serial` and the web server are stubbed out before core is imported.
Run: python3 -m unittest discover -s tests"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Stub hardware/network modules so core imports without them.
_serial = types.ModuleType('serial')
_serial.SerialTimeoutException = type('SerialTimeoutException', (Exception,), {})
_serial.STOPBITS_TWO = 2
sys.modules.setdefault('serial', _serial)
_web = types.ModuleType('aqualogic.web')
_web.WebServer = object
sys.modules.setdefault('aqualogic.web', _web)

from aqualogic.core import AquaLogic          # noqa: E402
from aqualogic.keys import Keys               # noqa: E402
from aqualogic.states import States           # noqa: E402
from aqualogic.spa_poll import (SpaTempPoller, screen_id,  # noqa: E402
                                is_spa_mode)

SPA_MODE = States.SPA | States.FILTER
POOL_MODE = States.POOL | States.FILTER
SPILLOVER = States.POOL | States.SPA | States.FILTER

# Exactly as captured from splitcreek/poollcd on 2026-10-08
CAPTURED = [
    '   Spa Temp  64°F                       \x00',
    '  Air Temp   62°F                       \x00',
    '  Spa Chlorinator            0%         \x00',
    '     Salt Level           2800 PPM      \x00',
    '      Heater1           Auto Control    \x00',
    '      Heater1            Manual Off     \x00',
    '    Filter Speed      100% Spa Mode     \x00',
    '      Thursday              6:35P       \x00',
    '      Thursday              6 35P       \x00',
]


class Clock():
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakePanel():
    def __init__(self, states=SPA_MODE, flashing=0):
        self._states = states
        self._flashing_states = flashing
        self.queued = []

    def queue_poll_right(self, guard):
        self.queued.append(guard)


def armed_poller(states=SPA_MODE):
    """A poller that has seen the panel auto-advance in spa mode."""
    clock = Clock()
    panel = FakePanel(states)
    poller = SpaTempPoller(panel, interval=10, pause_after_user=60,
                           clock=clock)
    poller.on_display(CAPTURED[0])
    clock.t += 6
    poller.on_display(CAPTURED[1])   # auto-advance, no key pressed
    clock.t += 2
    return poller, panel, clock


class ScreenTests(unittest.TestCase):
    def test_captured_screens_known(self):
        for text in CAPTURED:
            self.assertIsNotNone(screen_id(text), text)
        self.assertEqual(screen_id(CAPTURED[7]), screen_id(CAPTURED[8]))
        self.assertEqual(screen_id(CAPTURED[4]), 'heater1')
        self.assertEqual(screen_id(CAPTURED[5]), 'heater1')
        self.assertEqual(screen_id('  Heater1   Manual On  \x00'), 'heater1')

    def test_unknown_screens(self):
        for text in ['Settings Menu', 'Spa Heater1 102°F',
                     'Set Day and Time', 'Configuration Menu-Locked',
                     'Check System Low Salt', 'Pool Temp 55°F',
                     'Thursday 6:35P Set', '', None, 'Heater1 Off',
                     'Heater1 Manual Off Set',
                     'Heater1 Auto', 'Spa Heater1 Manual Off']:
            self.assertIsNone(screen_id(text), text)


class ModeTests(unittest.TestCase):
    def test_modes(self):
        self.assertTrue(is_spa_mode(SPA_MODE, 0))
        self.assertFalse(is_spa_mode(POOL_MODE, 0))
        self.assertFalse(is_spa_mode(SPILLOVER, 0))
        self.assertFalse(is_spa_mode(0, 0))                       # unknown
        self.assertFalse(is_spa_mode(States.SPA, 0))              # filter off
        self.assertFalse(is_spa_mode(SPA_MODE, States.SPA))       # flashing
        self.assertFalse(is_spa_mode(SPA_MODE | States.SERVICE, 0))
        self.assertFalse(is_spa_mode(SPA_MODE | States.SYSTEM_OFF, 0))


class PollerTests(unittest.TestCase):
    def test_spa_mode_known_screen_presses(self):
        poller, panel, _ = armed_poller()
        self.assertTrue(poller.armed)
        self.assertTrue(poller.tick())
        self.assertEqual(len(panel.queued), 1)

    def test_pool_mode_never_presses(self):
        poller, panel, clock = armed_poller(POOL_MODE)
        self.assertFalse(poller.armed)
        for _ in range(20):
            clock.t += 2
            self.assertFalse(poller.tick())
        self.assertEqual(panel.queued, [])

    def test_unknown_mode_never_presses(self):
        poller, panel, _ = armed_poller(0)
        self.assertFalse(poller.tick())
        self.assertEqual(panel.queued, [])

    def test_mode_change_disarms(self):
        poller, panel, clock = armed_poller()
        panel._states = POOL_MODE
        self.assertFalse(poller.tick())
        panel._states = SPA_MODE
        clock.t += 10
        self.assertFalse(poller.tick())   # needs a new auto-advance
        self.assertEqual(panel.queued, [])

    def test_unknown_screen_no_press(self):
        poller, panel, clock = armed_poller()
        poller.on_display('Settings Menu')
        clock.t += 5
        self.assertFalse(poller.tick())
        # Back on a known screen is not enough by itself ...
        poller.on_display(CAPTURED[2])
        clock.t += 5
        self.assertFalse(poller.tick())
        self.assertEqual(panel.queued, [])
        # ... it needs the panel to auto-advance between known screens.
        clock.t += 1
        poller.on_display(CAPTURED[3])
        clock.t += 2
        self.assertTrue(poller.tick())

    def test_not_armed_at_start(self):
        clock = Clock()
        panel = FakePanel()
        poller = SpaTempPoller(panel, clock=clock)
        poller.on_display(CAPTURED[0])
        clock.t += 30
        self.assertFalse(poller.tick())
        self.assertEqual(panel.queued, [])

    def test_external_key_pauses(self):
        poller, panel, clock = armed_poller()
        poller.on_external_key()
        clock.t += 30
        poller.on_display(CAPTURED[2])     # too soon to re-arm
        clock.t += 2
        self.assertFalse(poller.tick())
        clock.t += 40
        poller.on_display(CAPTURED[3])     # auto-advance after the pause
        clock.t += 2
        self.assertTrue(poller.tick())

    def test_own_press_does_not_arm(self):
        clock = Clock()
        panel = FakePanel()
        poller = SpaTempPoller(panel, clock=clock)
        poller.on_display(CAPTURED[0])
        poller._last_our_press = clock.t
        clock.t += 1
        poller.on_display(CAPTURED[1])     # changed right after our press
        self.assertFalse(poller.armed)

    def test_rate_limit(self):
        poller, panel, clock = armed_poller()
        self.assertTrue(poller.tick())
        self.assertFalse(poller.tick())             # same instant
        poller.on_display(CAPTURED[2])
        clock.t += poller.dwell - 0.1
        self.assertFalse(poller.tick())
        clock.t += 0.2
        self.assertTrue(poller.tick())
        self.assertGreaterEqual(poller.dwell, 1.0)

    def test_heater_manual_off_screen_stays_armed(self):
        poller, panel, clock = armed_poller()
        poller.on_display(CAPTURED[5])     # 'Heater1 Manual Off'
        self.assertTrue(poller.armed)
        clock.t += 2
        self.assertTrue(poller.tick())

    def test_disabled(self):
        poller, panel, _ = armed_poller()
        poller.enabled = False
        self.assertFalse(poller.tick())

    def test_guard_rechecked_at_send(self):
        poller, panel, _ = armed_poller()
        poller.tick()
        guard = panel.queued[0]
        self.assertTrue(guard())
        poller.on_display('Settings Menu')
        self.assertFalse(guard())


class CoreTests(unittest.TestCase):
    def setUp(self):
        AquaLogic._start_spa_temp_decay_timer = lambda self: None
        AquaLogic.STATE_FILE = '/nonexistent/.state.json'
        self.panel = AquaLogic(web_port=0)
        self.sent = []
        self.panel._write = self.sent.append

    def test_poll_frame_is_right(self):
        ok = [True]
        self.panel.queue_poll_right(lambda: ok[0])
        self.panel._send_frame()
        self.assertEqual(self.sent,
                         [self.panel._get_key_event_frame(Keys.RIGHT)])

    def test_guard_failure_drops_frame(self):
        self.panel.queue_poll_right(lambda: False)
        self.panel._send_frame()
        self.assertEqual(self.sent, [])
        self.assertTrue(self.panel._send_queue.empty())

    def test_guard_exception_drops_frame(self):
        def boom():
            raise RuntimeError('x')
        self.panel.queue_poll_right(boom)
        self.panel._send_frame()
        self.assertEqual(self.sent, [])

    def test_queue_poll_right_has_no_key_arg(self):
        with self.assertRaises(TypeError):
            self.panel.queue_poll_right(lambda: True, Keys.PLUS)

    def test_send_key_notifies_poller(self):
        poller, _, _ = armed_poller()
        self.panel._spa_poller = poller
        self.panel.send_key(Keys.RIGHT)
        self.assertFalse(poller.armed)

    def test_poller_error_does_not_raise_in_reader(self):
        class Broken():
            def on_display(self, text):
                raise RuntimeError('x')

            def on_external_key(self):
                raise RuntimeError('x')
        self.panel._spa_poller = Broken()
        self.panel._notify_external_key()     # must not raise
        self.panel._last_tx_time = 0
        self.panel._bus_key_seen()            # must not raise


if __name__ == '__main__':
    unittest.main()


class FakeTimer():
    """Replaces core.Timer: records the 2 s state checks so tests run them."""
    pending = []

    def __init__(self, delay, func, args):
        self.call = (func, args)

    def start(self):
        FakeTimer.pending.append(self.call)


class SetStateRetryTests(unittest.TestCase):
    """Last command wins: opposite LIGHTS requests must not fight."""

    def setUp(self):
        import aqualogic.core as core
        self._orig_timer = core.Timer
        core.Timer = FakeTimer
        FakeTimer.pending = []
        AquaLogic._start_spa_temp_decay_timer = lambda self: None
        AquaLogic.STATE_FILE = '/nonexistent/.state.json'
        self.panel = AquaLogic(web_port=0)
        self.lights_frame = self.panel._get_key_event_frame(Keys.LIGHTS)
        self.sent = []
        self.lose_next = False

        def write(frame):
            # Simulated panel: each LIGHTS key toggles the lights.
            self.sent.append(frame)
            if frame == self.lights_frame:
                if self.lose_next:
                    self.lose_next = False
                else:
                    self.panel._states ^= States.LIGHTS
        self.panel._write = write

    def tearDown(self):
        import aqualogic.core as core
        core.Timer = self._orig_timer

    def lights(self):
        return bool(self.panel._states & States.LIGHTS)

    def run_checks(self):
        calls, FakeTimer.pending = FakeTimer.pending, []
        for func, args in calls:
            func(*args)

    def drain(self, rounds=20):
        for _ in range(rounds):
            while not self.panel._send_queue.empty():
                self.panel._send_frame()
            if not FakeTimer.pending:
                break
            self.run_checks()

    def test_queued_opposite_request_replaced(self):
        self.panel.set_state(States.LIGHTS, True)
        self.panel._states |= States.LIGHTS   # pretend it already lit
        self.panel.set_state(States.LIGHTS, False)
        self.assertEqual(self.panel._send_queue.qsize(), 1)

    def test_on_then_off_both_sent_no_fight(self):
        # The 19:17:53 case: off sent, then on 0.9 s later, both in flight.
        self.panel._states |= States.LIGHTS
        self.panel.set_state(States.LIGHTS, False)
        self.panel._send_frame()                 # off
        self.panel.set_state(States.LIGHTS, True)
        self.panel._send_frame()                 # on
        self.drain()
        self.assertTrue(self.lights())           # last command wins
        self.assertEqual(len(self.sent), 2)      # no ping-pong
        self.assertFalse(self.panel.busy())

    def test_many_taps_settle_on_last(self):
        want = True
        for _ in range(5):
            self.panel.set_state(States.LIGHTS, want)
            self.panel._send_frame()
            want = not want
        self.drain()
        self.assertEqual(self.lights(), not want)   # last tap's value
        self.assertLessEqual(len(self.sent), 5)

    def test_lost_key_is_retried(self):
        self.lose_next = True
        self.panel.set_state(States.LIGHTS, True)
        self.drain()
        self.assertTrue(self.lights())
        self.assertEqual(len(self.sent), 2)

    def test_retry_skipped_if_already_desired(self):
        self.lose_next = True
        self.panel.set_state(States.LIGHTS, True)
        self.panel._send_frame()
        self.run_checks()                        # requeued as a retry
        self.panel._states |= States.LIGHTS      # e.g. changed at the panel
        self.panel._send_frame()
        self.assertEqual(len(self.sent), 1)      # retry not sent
        self.assertTrue(self.lights())

    def test_busy_while_queued_or_checking(self):
        self.assertFalse(self.panel.busy())
        self.panel.set_state(States.LIGHTS, True)
        self.assertTrue(self.panel.busy())       # queued
        self.panel._send_frame()
        self.assertTrue(self.panel.busy())       # awaiting check
        self.run_checks()
        self.assertFalse(self.panel.busy())

    def test_send_key_unaffected(self):
        self.panel.send_key(Keys.RIGHT)
        self.panel.set_state(States.LIGHTS, True)
        self.assertEqual(self.panel._send_queue.qsize(), 2)

    def test_poller_backs_off_while_busy(self):
        poller, panel, _ = armed_poller()
        panel.busy = lambda: True
        self.assertFalse(poller.tick())
        self.assertEqual(panel.queued, [])
        panel.busy = lambda: False
        self.assertTrue(poller.tick())
