'''
Pauses and resumes DiRT Rally 2.0 by sending the Esc key to the game window (Windows only).

Uses SendInput with hardware scan codes, which games reading DirectInput/raw input accept,
unlike virtual-key messages. On other platforms every method is a harmless no-op.

Run `python -m timerecorder.gameControl` to test pausing on your machine.
'''
import ctypes
import sys
import time

from .log import getLogger

logger = getLogger(__name__)

IS_WINDOWS = sys.platform == 'win32'

SCAN_ESC = 0x01
VK_MENU = 0x12
SW_RESTORE = 9

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    ULONG_PTR = wintypes.WPARAM

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    user32.GetForegroundWindow.restype = wintypes.HWND


def _sendKeyboard(scan=0, vk=0, keyUp=False):
    flags = KEYEVENTF_SCANCODE if scan else 0
    if keyUp:
        flags |= KEYEVENTF_KEYUP
    event = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)))
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        logger.debug('SendInput failed: %s', ctypes.get_last_error())
    return sent == 1


def findWindows(titlePart):
    '''Visible top-level windows whose title contains titlePart (case-insensitive), as (hwnd, title).'''
    if not IS_WINDOWS:
        return []

    found = []
    needle = titlePart.casefold()

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if needle in buffer.value.casefold():
                    found.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def bringToFront(hwnd):
    '''
    Makes hwnd the foreground window. Windows only allows this for the process that received the
    last input, so an Alt tap is sent first (a well-known workaround). Returns True on success.
    '''
    if not IS_WINDOWS or not hwnd:
        return False

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    _sendKeyboard(vk=VK_MENU)
    _sendKeyboard(vk=VK_MENU, keyUp=True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    return user32.GetForegroundWindow() == hwnd


class GameController():

    def __init__(self, windowTitle='DiRT Rally 2.0', enabled=True, keyHoldSeconds=0.06, focusDelaySeconds=0.3):
        self.window_title = windowTitle
        self.enabled = enabled and IS_WINDOWS
        self.key_hold = keyHoldSeconds
        self.focus_delay = focusDelaySeconds

        if enabled and not IS_WINDOWS:
            logger.info('Automatic pausing only works on Windows, pause the game manually')

    def findGameWindow(self):
        windows = findWindows(self.window_title)
        return windows[0][0] if windows else None

    def _pressEsc(self):
        _sendKeyboard(scan=SCAN_ESC)
        time.sleep(self.key_hold)
        _sendKeyboard(scan=SCAN_ESC, keyUp=True)

    def _escToGame(self):
        if not self.enabled:
            return False

        hwnd = self.findGameWindow()
        if hwnd is None:
            logger.warning('Could not find a window titled "%s", pause the game manually', self.window_title)
            return False

        if user32.GetForegroundWindow() != hwnd:
            if not bringToFront(hwnd):
                logger.warning('Could not focus the game window, not sending Esc')
                return False
            time.sleep(self.focus_delay)

        self._pressEsc()
        return True

    def pause(self):
        '''Opens the in-game pause menu. Returns True if Esc was sent to the game.'''
        return self._escToGame()

    def resume(self):
        '''Focuses the game and closes the pause menu. Returns True if Esc was sent to the game.'''
        return self._escToGame()

    def focusGame(self):
        if not self.enabled:
            return False
        return bringToFront(self.findGameWindow())


def _selfTest():
    title = sys.argv[1] if len(sys.argv) > 1 else 'DiRT Rally 2.0'
    if not IS_WINDOWS:
        print('This test only works on Windows.')
        return

    windows = findWindows(title)
    if not windows:
        print(f'No visible window containing "{title}". Start the game (borderless/windowed) and try again.')
        return
    for hwnd, text in windows:
        print(f'Found window {hwnd}: {text}')

    controller = GameController(title)
    print('Drive onto a stage. Pausing the game in 5 seconds...')
    time.sleep(5)
    print('Pause sent' if controller.pause() else 'Pause FAILED')
    print('Resuming in 5 seconds...')
    time.sleep(5)
    print('Resume sent' if controller.resume() else 'Resume FAILED')


if __name__ == '__main__':
    _selfTest()
