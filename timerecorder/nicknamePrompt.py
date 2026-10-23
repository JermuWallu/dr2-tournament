'''
The nickname window shown when a stage has loaded (tkinter, runs on the main thread).

Other threads talk to it only through TkUiBridge, which queues calls for the Tk event loop.
'''
import queue

from .tournamentDatabase import DNF, formatTime, MAX_NAME_LENGTH
from . import gameControl

OK = 'ok'
WARNING = 'warning'
INFO = 'info'

LOOKUP_DELAY_MS = 250
POLL_MS = 100

COLORS = {
    'bg': '#16181d', 'panel': '#1f232b', 'text': '#f2f4f8', 'muted': '#9aa3b2',
    'accent': '#ffb000', 'ok': '#5fd18b', 'warning': '#ff6b5b', 'info': '#9aa3b2',
    'button': '#ffb000', 'button_text': '#16181d', 'disabled': '#4a505c',
}

def describeLookup(info):
    '''
    Turns TournamentDatabase.lookup() output into (message, level, canStart).
    An empty nickname shows nothing.
    '''
    if info is None:
        return '', INFO, False

    lines = []
    for attempt in info['attempts']:
        result = 'DNF' if attempt['status'] == DNF else formatTime(attempt['time'])
        lines.append(f"Attempt {attempt['attempt']}: {result}")

    if not info['found']:
        return f"New player. This will be attempt 1 of {info['max']}.", OK, True

    if info['remaining'] == 0:
        header = f"{info['name']} has completed all {info['max']} attempts."
        return '\n'.join([header] + lines), WARNING, False

    header = f"{info['name']}: {info['used']} of {info['max']} attempts used."
    footer = f"Next: attempt {info['used'] + 1} of {info['max']}."
    return '\n'.join([header] + lines + [footer]), OK, True


class TkUiBridge():
    '''Thread-safe UI facade handed to TournamentSession.'''

    def __init__(self):
        self.queue = queue.Queue()

    def showPrompt(self, track, car):
        self.queue.put(('showPrompt', (track, car)))

    def hidePrompt(self):
        self.queue.put(('hidePrompt', ()))

    def setGamePaused(self, paused):
        self.queue.put(('setGamePaused', (paused,)))

    def showResult(self, text):
        self.queue.put(('showResult', (text,)))

    def fatal(self, text):
        self.queue.put(('fatal', (text,)))


class PromptWindow():  #pylint: disable=too-many-instance-attributes

    def __init__(self, session, bridge, leaderboardUrl=None):
        import tkinter as tk  #pylint: disable=import-outside-toplevel
        self.tk = tk
        self.session = session
        self.bridge = bridge
        self.lookup_job = None
        self.can_start = False

        root = tk.Tk()
        self.root = root
        root.title('DR2 Tournament')
        root.configure(bg=COLORS['bg'], padx=28, pady=24)
        root.resizable(False, False)
        root.protocol('WM_DELETE_WINDOW', root.bell)  # players must not close it, admins use Ctrl+C in the console

        label = lambda text, size, color, bold=False: tk.Label(
            root, text=text, bg=COLORS['bg'], fg=color, font=('Segoe UI', size, 'bold' if bold else 'normal'),
            justify='left', anchor='w')

        label('DR2 TOURNAMENT', 10, COLORS['accent'], True).grid(row=0, column=0, sticky='w')
        self.track_label = label('', 18, COLORS['text'], True)
        self.track_label.grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.car_label = label('', 13, COLORS['muted'])
        self.car_label.grid(row=2, column=0, sticky='w')

        label('Nickname', 11, COLORS['muted']).grid(row=3, column=0, sticky='w', pady=(20, 4))
        self.name = tk.StringVar()
        self.name.trace_add('write', self._onType)
        self.entry = tk.Entry(root, textvariable=self.name, font=('Segoe UI', 20), width=22,
                              bg=COLORS['panel'], fg=COLORS['text'], insertbackground=COLORS['text'],
                              relief='flat', highlightthickness=2, highlightcolor=COLORS['accent'],
                              highlightbackground=COLORS['panel'])
        self.entry.grid(row=4, column=0, sticky='we', ipady=6)
        self.entry.bind('<Return>', lambda _event: self._start())

        self.status = label('', 12, COLORS['info'])
        self.status.configure(wraplength=420)
        self.status.grid(row=5, column=0, sticky='w', pady=(12, 0))

        self.button = tk.Button(root, text='START', command=self._start, font=('Segoe UI', 14, 'bold'),
                                bg=COLORS['button'], fg=COLORS['button_text'], activebackground=COLORS['accent'],
                                relief='flat', padx=24, pady=8, disabledforeground=COLORS['muted'])
        self.button.grid(row=6, column=0, sticky='we', pady=(18, 0))

        self.pause_label = label('', 9, COLORS['muted'])
        self.pause_label.grid(row=7, column=0, sticky='w', pady=(10, 0))

        footer = 'Last result: -' if leaderboardUrl is None else f'Leaderboard: {leaderboardUrl}'
        self.footer = label(footer, 9, COLORS['muted'])
        self.footer.grid(row=8, column=0, sticky='w', pady=(4, 0))
        self.leaderboard_url = leaderboardUrl

        self._setCanStart(False)
        root.withdraw()
        root.after(POLL_MS, self._poll)

    def run(self):
        self.root.mainloop()

    def close(self):
        self.root.quit()

    # --- bridge commands ---

    def _poll(self):
        try:
            while True:
                command, args = self.bridge.queue.get_nowait()
                getattr(self, '_cmd_' + command)(*args)
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll)

    def _cmd_showPrompt(self, track, car):
        self.track_label.configure(text=track)
        self.car_label.configure(text=car)
        self.name.set('')
        self._setStatus('', INFO)
        self.pause_label.configure(text='')
        self._setCanStart(False)

        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.after(150, self._grabFocus)

    def _cmd_hidePrompt(self):
        self.root.withdraw()

    def _cmd_setGamePaused(self, paused):
        if paused:
            self.pause_label.configure(text='Game paused', fg=COLORS['muted'])
        else:
            self.pause_label.configure(text='Game does not look paused, press Esc in the game.', fg=COLORS['warning'])

    def _cmd_showResult(self, text):
        print(f'\n*** {text} ***\n')
        if self.leaderboard_url is None:
            self.footer.configure(text=f'Last result: {text}')

    def _cmd_fatal(self, text):
        from tkinter import messagebox  #pylint: disable=import-outside-toplevel
        self.root.deiconify()
        messagebox.showerror('DR2 Tournament', text)
        self.root.quit()

    # --- interaction ---

    def _grabFocus(self):
        self.root.focus_force()
        self.entry.focus_set()
        try:
            gameControl.bringToFront(int(self.root.wm_frame(), 16))
        except (ValueError, OSError):
            pass
        self.entry.focus_set()

    def _onType(self, *_args):
        value = self.name.get()
        if len(value) > MAX_NAME_LENGTH:
            self.name.set(value[:MAX_NAME_LENGTH])
            return
        if self.lookup_job is not None:
            self.root.after_cancel(self.lookup_job)
        self._setCanStart(False)
        self.lookup_job = self.root.after(LOOKUP_DELAY_MS, self._lookup)

    def _lookup(self):
        self.lookup_job = None
        message, level, canStart = describeLookup(self.session.lookup(self.name.get()))
        self._setStatus(message, level)
        self._setCanStart(canStart)

    def _start(self):
        if self.lookup_job is not None:
            self.root.after_cancel(self.lookup_job)
            self._lookup()
        if not self.can_start:
            self.root.bell()
            return

        self.root.withdraw()
        self.root.update()
        error = self.session.start(self.name.get())
        if error is not None:
            self.root.deiconify()
            self._setStatus(error, WARNING)
            self._setCanStart(False)

    def _setStatus(self, text, level):
        self.status.configure(text=text, fg=COLORS[level])

    def _setCanStart(self, canStart):
        self.can_start = canStart
        self.button.configure(state='normal' if canStart else 'disabled',
                              bg=COLORS['button'] if canStart else COLORS['disabled'])
