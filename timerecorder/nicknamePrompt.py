'''
The nickname window shown when a stage has loaded (tkinter, runs on the main thread).

Other threads talk to it only through TkUiBridge, which queues calls for the Tk event loop.
'''
import math
import queue
import time

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


FULLSCREEN = 'fullscreen'
CENTERED = 'centered'
GO_TEXT = 'HYVÄÄ RALLIA!'
COUNTDOWN_TICK_MS = 100


class PromptWindow():  #pylint: disable=too-many-instance-attributes

    def __init__(self, session, bridge, leaderboardUrl=None, mode=FULLSCREEN, startDelaySeconds=2.0):  #pylint: disable=too-many-arguments,too-many-statements
        import tkinter as tk  #pylint: disable=import-outside-toplevel
        self.tk = tk
        self.session = session
        self.bridge = bridge
        self.lookup_job = None
        self.can_start = False
        self.counting_down = False
        self.mode = mode if mode in (FULLSCREEN, CENTERED) else FULLSCREEN
        self.start_delay = max(0.0, float(startDelaySeconds))
        self.leaderboard_url = leaderboardUrl
        scale = 1.6 if self.mode == FULLSCREEN else 1.0
        size = lambda points: int(round(points * scale))

        root = tk.Tk()
        self.root = root
        root.title('DR2 Tournament')
        root.configure(bg=COLORS['bg'])
        root.resizable(False, False)
        root.protocol('WM_DELETE_WINDOW', root.bell)  # players must not close it, admins use Ctrl+C in the console

        # --- nickname panel ---
        panel = tk.Frame(root, bg=COLORS['bg'], padx=size(28), pady=size(24))
        self.panel = panel

        label = lambda parent, text, points, color, bold=False: tk.Label(
            parent, text=text, bg=COLORS['bg'], fg=color, font=('Segoe UI', size(points), 'bold' if bold else 'normal'),
            justify='left', anchor='w')

        label(panel, 'DR2 TOURNAMENT', 10, COLORS['accent'], True).grid(row=0, column=0, sticky='w')
        self.track_label = label(panel, '', 18, COLORS['text'], True)
        self.track_label.grid(row=1, column=0, sticky='w', pady=(size(6), 0))
        self.car_label = label(panel, '', 13, COLORS['muted'])
        self.car_label.grid(row=2, column=0, sticky='w')

        label(panel, 'Nickname', 11, COLORS['muted']).grid(row=3, column=0, sticky='w', pady=(size(20), size(4)))
        self.name = tk.StringVar()
        self.name.trace_add('write', self._onType)
        self.entry = tk.Entry(panel, textvariable=self.name, font=('Segoe UI', size(20)), width=22,
                              bg=COLORS['panel'], fg=COLORS['text'], insertbackground=COLORS['text'],
                              relief='flat', highlightthickness=2, highlightcolor=COLORS['accent'],
                              highlightbackground=COLORS['panel'])
        self.entry.grid(row=4, column=0, sticky='we', ipady=size(6))
        self.entry.bind('<Return>', lambda _event: self._start())

        self.status = label(panel, '', 12, COLORS['info'])
        self.status.configure(wraplength=size(420))
        self.status.grid(row=5, column=0, sticky='w', pady=(size(12), 0))

        self.button = tk.Button(panel, text='START', command=self._start, font=('Segoe UI', size(14), 'bold'),
                                bg=COLORS['button'], fg=COLORS['button_text'], activebackground=COLORS['accent'],
                                relief='flat', padx=size(24), pady=size(8), disabledforeground=COLORS['muted'])
        self.button.grid(row=6, column=0, sticky='we', pady=(size(18), 0))

        self.pause_label = label(panel, '', 9, COLORS['muted'])
        self.pause_label.grid(row=7, column=0, sticky='w', pady=(size(10), 0))

        footer = 'Last result: -' if leaderboardUrl is None else f'Leaderboard: {leaderboardUrl}'
        self.footer = label(panel, footer, 9, COLORS['muted'])
        self.footer.grid(row=8, column=0, sticky='w', pady=(size(4), 0))

        # --- "hyvää rallia" countdown panel ---
        goScale = 2.0 if self.mode == FULLSCREEN else 1.0
        self.go_panel = tk.Frame(root, bg=COLORS['bg'], padx=size(28), pady=size(24))
        self.go_name = tk.Label(self.go_panel, text='', bg=COLORS['bg'], fg=COLORS['muted'],
                                font=('Segoe UI', int(18 * goScale)))
        self.go_name.pack()
        tk.Label(self.go_panel, text=GO_TEXT, bg=COLORS['bg'], fg=COLORS['accent'],
                 font=('Segoe UI', int(54 * goScale), 'bold')).pack()
        self.countdown = tk.Label(self.go_panel, text='', bg=COLORS['bg'], fg=COLORS['text'],
                                  font=('Segoe UI', int(40 * goScale), 'bold'))
        self.countdown.pack(pady=(int(8 * goScale), 0))

        self._setCanStart(False)
        root.withdraw()
        root.after(POLL_MS, self._poll)

    def run(self):
        self.root.mainloop()

    def close(self):
        self.root.quit()

    # --- layout ---

    def _showPanel(self, panel):
        for other in (self.panel, self.go_panel):
            if other is not panel:
                other.place_forget()
                other.pack_forget()

        if self.mode == FULLSCREEN:
            panel.place(relx=0.5, rely=0.5, anchor='center')
        else:
            panel.pack()

    def _present(self):
        root = self.root
        root.deiconify()
        if self.mode == FULLSCREEN:
            root.attributes('-fullscreen', True)
        else:
            root.update_idletasks()
            width, height = root.winfo_reqwidth(), root.winfo_reqheight()
            x = (root.winfo_screenwidth() - width) // 2
            y = (root.winfo_screenheight() - height) // 2
            root.geometry(f'+{max(0, x)}+{max(0, y)}')
        root.attributes('-topmost', True)
        root.lift()

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
        self.counting_down = False
        self.track_label.configure(text=track)
        self.car_label.configure(text=car)
        self.name.set('')
        self._setStatus('', INFO)
        self.pause_label.configure(text='')
        self._setCanStart(False)

        self._showPanel(self.panel)
        self._present()
        self.root.after(150, self._grabFocus)

    def _cmd_hidePrompt(self):
        self.counting_down = False
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
        self.root.attributes('-fullscreen', False)
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
        if self.counting_down:
            return
        if self.lookup_job is not None:
            self.root.after_cancel(self.lookup_job)
            self._lookup()
        if not self.can_start:
            self.root.bell()
            return

        info = self.session.lookup(self.name.get())
        self.go_name.configure(text=f"{info['name']} · attempt {info['used'] + 1}/{info['max']}" if info else '')
        self.counting_down = True
        self._showPanel(self.go_panel)
        self._present()
        self._countdown(time.monotonic() + self.start_delay)

    def _countdown(self, endsAt):
        if not self.counting_down:
            return  # cancelled, e.g. the stage was left meanwhile
        remaining = endsAt - time.monotonic()
        if remaining > 0:
            self.countdown.configure(text=str(math.ceil(remaining)))
            self.root.after(max(1, min(COUNTDOWN_TICK_MS, int(remaining * 1000))), self._countdown, endsAt)
            return

        self.counting_down = False
        self.countdown.configure(text='')
        self.root.withdraw()
        self.root.update()
        error = self.session.start(self.name.get())
        if error is not None:
            self._showPanel(self.panel)
            self._present()
            self._setStatus(error, WARNING)
            self._setCanStart(False)

    def _setStatus(self, text, level):
        self.status.configure(text=text, fg=COLORS[level])

    def _setCanStart(self, canStart):
        self.can_start = canStart
        self.button.configure(state='normal' if canStart else 'disabled',
                              bg=COLORS['button'] if canStart else COLORS['disabled'])
