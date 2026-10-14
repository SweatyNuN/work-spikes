#!/usr/bin/env python3
"""Terminal Space Invaders -- an ASCII animation that doubles as a mini-game.

By default it plays itself (attract mode) so you can just watch it go. The
moment you press a direction key or the space bar you take over the cannon,
and "o" hands control back to the demo.

Usage:
    python space_invaders.py             # watch the demo
    python space_invaders.py --fps 45    # smoother (default 30)
    python space_invaders.py --no-color  # monochrome, for plain terminals
    python space_invaders.py --selftest  # headless logic check, no curses

Keys (while running):
    Left/Right or A/D   move the cannon (also disables attract mode)
    Space               fire
    O                   toggle attract mode on/off
    P                   pause
    Q or Esc            quit

Only the Python standard library is used (curses + random), so it runs under
the folder's venv or the system interpreter. Python 3.8+.
"""

from __future__ import annotations

import argparse
import curses
import random
import sys
import time
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Sprites
# --------------------------------------------------------------------------

# Each alien flips between two frames every fleet step, which is what gives the
# classic "marching" wobble. Every sprite is 3 wide and 3 tall.
ALIEN_W = 3
ALIEN_H = 3
ALIEN_FRAMES = (
    (" # ", "###", "# #"),
    ("# #", "###", " # "),
)

PLAYER_W = 3
PLAYER_H = 2
PLAYER_SPRITE = (" ^ ", "###")

BULLET_CHAR = "|"
BOMB_CHAR = "o"
BOOM_CHAR = "*"

# --------------------------------------------------------------------------
# Color slots. Each index maps to a curses color pair created at startup.
# --------------------------------------------------------------------------

C_DEFAULT = 0
C_HUD = 1
C_PLAYER = 2
C_ALIEN_A = 3
C_ALIEN_B = 4
C_BOMB = 5
C_ALIEN_C = 6
C_FRAME = 7
C_BOOM = C_ALIEN_B  # reuse yellow for explosions

# (foreground, background) per slot; -1 means "terminal default".
PALETTE = (
    (curses.COLOR_WHITE, -1),    # 0 default
    (curses.COLOR_WHITE, -1),    # 1 HUD
    (curses.COLOR_CYAN, -1),     # 2 player
    (curses.COLOR_GREEN, -1),    # 3 alien A
    (curses.COLOR_YELLOW, -1),   # 4 alien B / boom
    (curses.COLOR_RED, -1),      # 5 bomb
    (curses.COLOR_MAGENTA, -1),  # 6 alien C
    (curses.COLOR_BLUE, -1),     # 7 frame / ground
)

# Alien rows are tinted from this cycle, top to bottom.
ROW_COLORS = (C_ALIEN_A, C_ALIEN_C, C_ALIEN_B, C_ALIEN_A, C_ALIEN_C)

# --------------------------------------------------------------------------
# Tunables (all time-based, so they behave the same at any --fps)
# --------------------------------------------------------------------------

PLAYER_SPEED = 22.0     # cells per second
BULLET_SPEED = 30.0     # cells per second, upward
BOMB_SPEED = 8.0        # cells per second, downward
MAX_BOMBS = 4
EXPLOSION_TTL = 0.22    # seconds
DEAD_TIME = 1.1         # seconds of blinking after losing a life
WAVE_TIME = 1.6         # seconds of "wave cleared" banner
GAMEOVER_TIME = 2.8     # seconds before a fresh game starts
INTRO_TIME = 1.4        # seconds of title banner at launch
MAX_BULLETS = 1         # classic rule: one shot in the air at a time


# --------------------------------------------------------------------------
# Screen buffer -- decouples rendering from curses so we can test headlessly.
# --------------------------------------------------------------------------


class Screen:
    def __init__(self, w: int, h: int) -> None:
        self.w = w
        self.h = h
        self.cells = [[(" ", C_DEFAULT) for _ in range(w)] for _ in range(h)]

    def put(self, x: int, y: int, text: str, color: int = C_DEFAULT) -> None:
        if not 0 <= y < self.h:
            return
        for i, ch in enumerate(text):
            xx = x + i
            if 0 <= xx < self.w:
                self.cells[y][xx] = (ch, color)

    def put_sprite(self, x: int, y: int, lines, color: int) -> None:
        for dy, line in enumerate(lines):
            self.put(x, y + dy, line, color)

    def center(self, y: int, text: str, color: int = C_DEFAULT) -> None:
        self.put((self.w - len(text)) // 2, y, text, color)

    def to_lines(self) -> list[str]:
        return ["".join(ch for ch, _ in row) for row in self.cells]

    def blit(self, stdscr, attrs) -> None:
        """Write the buffer to a curses window, grouping runs of one color."""
        for y in range(self.h):
            row = self.cells[y]
            x = 0
            while x < self.w:
                color = row[x][1]
                start = x
                while x < self.w and row[x][1] == color:
                    x += 1
                run = "".join(ch for ch, _ in row[start:x])
                try:
                    stdscr.addstr(y, start, run, attrs[color])
                except curses.error:
                    # Writing the very bottom-right cell is illegal in curses;
                    # simply drop that run's overflow.
                    pass


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


@dataclass
class Alien:
    x: int
    y: int
    row: int
    color: int
    alive: bool = True

    @property
    def w(self) -> int:
        return ALIEN_W


class Game:
    """All the state and rules; rendering lives in `render()`."""

    def __init__(self, w: int, h: int, rng=None, auto: bool = True) -> None:
        self.w = min(max(w, 40), 400)
        self.h = min(max(h, 16), 200)
        self.rng = rng or random.Random()
        self.auto = auto
        self.hi = 0
        self.ground_y = self.h - 2
        self.hud_y = self.h - 1
        self.player_y = self.ground_y - PLAYER_H

        # Frame geometry: 3-wide aliens with a 2-cell gap between them.
        pitch_x = ALIEN_W + 2
        pitch_y = ALIEN_H + 1
        self.cols = max(4, min(9, (self.w - 2) // pitch_x))
        rows_fit = max(3, (self.player_y - 3) // pitch_y)
        self.rows = min(4, rows_fit)
        fleet_w = self.cols * pitch_x - 2
        self.fleet_x0 = (self.w - fleet_w) // 2
        self.fleet_top = 2

        self.reset(full=True)

    # -- lifecycle ---------------------------------------------------------

    def reset(self, full: bool = False) -> None:
        self.score = 0 if full else self.score
        self.lives = 3
        self.wave = 1 if full else self.wave
        self.px = (self.w - PLAYER_W) / 2
        self.bullets: list[dict] = []
        self.bombs: list[dict] = []
        self.explosions: list[dict] = []
        self.paused = False
        self.state = "play"
        self.timer = 0.0
        self.intro = INTRO_TIME
        self.frame = 0
        self.move_acc = 0.0
        self.bomb_acc = 0.0
        self.spawn_wave()

    def spawn_wave(self) -> None:
        self.aliens = []
        for r in range(self.rows):
            color = ROW_COLORS[r % len(ROW_COLORS)]
            for c in range(self.cols):
                self.aliens.append(
                    Alien(
                        x=self.fleet_x0 + c * (ALIEN_W + 2),
                        y=self.fleet_top + r * (ALIEN_H + 1),
                        row=r,
                        color=color,
                    )
                )
        self.dx = 1
        self.move_acc = 0.0
        self.bombs.clear()
        self.bullets.clear()

    # -- helpers -----------------------------------------------------------

    @property
    def alive(self) -> list[Alien]:
        return [a for a in self.aliens if a.alive]

    @property
    def cannon_center(self) -> int:
        return int(self.px) + PLAYER_W // 2

    def add_score(self, amount: int) -> None:
        self.score += amount
        self.hi = max(self.hi, self.score)

    def fleet_interval(self) -> float:
        """Seconds between fleet steps -- shrinks as the wave thins out."""
        total = len(self.aliens)
        frac = len(self.alive) / total if total else 0.0
        base = 0.10 + 0.45 * frac
        speedup = max(0.55, 1.0 - 0.08 * (self.wave - 1))
        return max(0.045, base * speedup)

    # -- attract-mode brain ------------------------------------------------

    def _think(self) -> tuple[int, bool]:
        """Return (move_dir, fire) for the demo. dir is -1, 0 or 1."""
        alive = self.alive
        if not alive:
            return 0, False

        cx = self.cannon_center

        # Dodge an incoming bomb that is lined up with us.
        for b in self.bombs:
            if abs(b["x"] - cx) <= 3 and self.player_y - 9 <= int(b["y"]) <= self.player_y:
                return (-1 if b["x"] >= cx else 1), False

        lowest = max(a.y for a in alive)
        candidates = [a for a in alive if a.y >= lowest - 1]
        target = min(candidates, key=lambda a: abs(a.x + ALIEN_W // 2 - cx))
        tx = target.x + ALIEN_W // 2

        if abs(tx - cx) <= 1:
            return 0, len(self.bullets) < MAX_BULLETS
        return (1 if tx > cx else -1), False

    # -- update ------------------------------------------------------------

    def update(self, dt: float, keys=None) -> None:
        dt = min(dt, 0.1)
        keys = keys or {}

        if self.intro > 0:
            self.intro = max(0.0, self.intro - dt)

        if self.paused:
            return

        # Timed states: wave transitions, death blink, game over.
        if self.timer > 0:
            self.timer = max(0.0, self.timer - dt)
            if self.timer == 0.0:
                if self.state == "wave":
                    self.state = "play"
                    self.wave += 1
                    self.spawn_wave()
                elif self.state == "dead":
                    self.state = "play"
                elif self.state == "gameover":
                    self.reset(full=True)
            return  # freeze the world during a banner/Death
        if self.state != "play":
            return

        self._update_player(dt, keys)
        self._update_bullets(dt)
        self._update_bombs(dt)
        self._update_explosions(dt)
        self._update_fleet(dt)

        if not self.alive:
            self.state = "wave"
            self.timer = WAVE_TIME
            self.add_score(100)  # wave bonus
            return

        # Aliens reaching the cannon line is an instant wipe.
        if any(a.y + ALIEN_H - 1 >= self.player_y for a in self.alive):
            self._game_over()

    def _update_player(self, dt: float, keys) -> None:
        if self.auto:
            move, fire = self._think()
        else:
            move = (1 if keys.get("right") else 0) - (1 if keys.get("left") else 0)
            fire = bool(keys.get("fire"))

        if move:
            self.px += move * PLAYER_SPEED * dt
        self.px = min(max(self.px, 0), self.w - PLAYER_W)

        if fire and len(self.bullets) < MAX_BULLETS:
            self.bullets.append({"x": self.cannon_center, "y": float(self.player_y - 1)})

    def _update_bullets(self, dt: float) -> None:
        survivors = []
        for b in self.bullets:
            b["y"] -= BULLET_SPEED * dt
            if b["y"] < 0:
                continue
            hit = None
            for a in self.alive:
                if a.x <= b["x"] <= a.x + ALIEN_W - 1 and a.y <= b["y"] <= a.y + ALIEN_H - 1:
                    hit = a
                    break
            if hit:
                hit.alive = False
                self.add_score((self.rows - hit.row) * 10)
                self.explosions.append(
                    {"x": hit.x + 1, "y": hit.y + 1, "ttl": EXPLOSION_TTL}
                )
            else:
                survivors.append(b)
        self.bullets = survivors

    def _update_bombs(self, dt: float) -> None:
        survivors = []
        for b in self.bombs:
            b["y"] += BOMB_SPEED * dt
            if b["y"] > self.ground_y:
                continue
            if int(b["y"]) >= self.player_y and int(self.px) <= b["x"] <= int(self.px) + PLAYER_W - 1:
                self._player_hit()
                return
            survivors.append(b)
        self.bombs = survivors

        # Occasionally an alien from the front rank drops a bomb.
        if len(self.bombs) < MAX_BOMBS and self.state == "play":
            self.bomb_acc += dt
            if self.bomb_acc >= self.rng.uniform(0.35, 0.9):
                self.bomb_acc = 0.0
                self._drop_bomb()

    def _drop_bomb(self) -> None:
        alive = self.alive
        if not alive:
            return
        lowest = max(a.y for a in alive)
        shooters = [a for a in alive if a.y == lowest]
        a = self.rng.choice(shooters)
        self.bombs.append({"x": a.x + ALIEN_W // 2, "y": float(a.y + ALIEN_H)})

    def _update_explosions(self, dt: float) -> None:
        for e in self.explosions:
            e["ttl"] -= dt
        self.explosions = [e for e in self.explosions if e["ttl"] > 0]

    def _update_fleet(self, dt: float) -> None:
        self.move_acc += dt
        if self.move_acc < self.fleet_interval():
            return
        self.move_acc = 0.0
        self.frame ^= 1

        alive = self.alive
        minx = min(a.x for a in alive)
        maxx = max(a.x + ALIEN_W - 1 for a in alive)

        if self.dx > 0 and maxx + 1 > self.w - 1:
            self._descend()
            self.dx = -1
        elif self.dx < 0 and minx - 1 < 0:
            self._descend()
            self.dx = 1
        else:
            for a in alive:
                a.x += self.dx

    def _descend(self) -> None:
        for a in self.alive:
            a.y += 1

    def _player_hit(self) -> None:
        self.lives -= 1
        self.bombs.clear()
        self.explosions.append({"x": int(self.px) + 1, "y": self.player_y, "ttl": EXPLOSION_TTL})
        if self.lives <= 0:
            self._game_over()
        else:
            self.state = "dead"
            self.timer = DEAD_TIME

    def _game_over(self) -> None:
        self.lives = 0
        self.state = "gameover"
        self.timer = GAMEOVER_TIME

    # -- rendering ---------------------------------------------------------

    def render(self) -> Screen:
        s = Screen(self.w, self.h)

        s.put(0, self.ground_y, "=" * self.w, C_FRAME)

        for a in self.alive:
            s.put_sprite(a.x, a.y, ALIEN_FRAMES[self.frame], a.color)

        for b in self.bullets:
            s.put(int(b["x"]), int(b["y"]), BULLET_CHAR, C_HUD)
        for b in self.bombs:
            s.put(int(b["x"]), int(b["y"]), BOMB_CHAR, C_BOMB)
        for e in self.explosions:
            s.put(e["x"], e["y"], BOOM_CHAR, C_BOOM)

        if self.state != "gameover":
            blink_ok = self.state != "dead" or int(self.timer * 12) % 2 == 0
            if blink_ok:
                s.put_sprite(int(self.px), self.player_y, PLAYER_SPRITE, C_PLAYER)

        mid = self.h // 2
        if self.intro > 0:
            s.center(mid - 1, "- SPACE INVADERS -", C_ALIEN_B)
            s.center(mid + 1, "the fleet fights itself", C_FRAME)
        elif self.state == "wave":
            s.center(mid, f"WAVE {self.wave} CLEARED!", C_ALIEN_B)
        elif self.state == "gameover":
            s.center(mid - 1, "GAME OVER", C_BOMB)
            s.center(mid + 1, f"FINAL SCORE {self.score}", C_HUD)
        elif self.paused:
            s.center(mid, "PAUSED", C_HUD)

        hud_left = f" SCORE {self.score:05d}  HI {self.hi:05d}  LIVES {self.lives}  WAVE {self.wave}"
        mode = "PAUSED" if self.paused else ("DEMO" if self.auto else "MANUAL")
        hud_right = f"{mode}  [q]uit "
        s.put(0, self.hud_y, hud_left, C_HUD)
        if len(hud_left) + len(hud_right) < self.w:
            s.put(self.w - len(hud_right), self.hud_y, hud_right, C_FRAME)

        return s


# --------------------------------------------------------------------------
# Curses front-end
# --------------------------------------------------------------------------


def _build_attrs(no_color: bool):
    attrs = [curses.A_NORMAL] * len(PALETTE)
    if no_color or not curses.has_colors():
        return attrs
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    for i, (fg, bg) in enumerate(PALETTE):
        curses.init_pair(i + 1, fg, bg)
        attrs[i] = curses.color_pair(i + 1)
    attrs[C_HUD] |= curses.A_BOLD
    attrs[C_ALIEN_B] |= curses.A_BOLD
    return attrs


def run_curses(stdscr, fps: float, no_color: bool) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    stdscr.nodelay(True)
    try:
        curses.mousemask(0)
    except curses.error:
        pass
    attrs = _build_attrs(no_color)
    frame_ms = max(1, round(1000.0 / fps))
    stdscr.timeout(frame_ms)  # getch() also paces the loop

    h, w = stdscr.getmaxyx()
    if h < 16 or w < 40:
        _too_small(stdscr)
        return

    game = Game(w, h)
    last = time.monotonic()

    while True:
        keys = {"left": False, "right": False, "fire": False}
        taking_over = False
        ch = stdscr.getch()
        while ch != -1:
            if ch in (ord("q"), ord("Q"), 27):  # q / Esc
                return
            if ch in (curses.KEY_LEFT, ord("a"), ord("A")):
                keys["left"] = True
                taking_over = True
            elif ch in (curses.KEY_RIGHT, ord("d"), ord("D")):
                keys["right"] = True
                taking_over = True
            elif ch in (ord(" "), curses.KEY_UP, ord("w"), ord("W")):
                keys["fire"] = True
                taking_over = True
            elif ch in (ord("p"), ord("P")):
                game.paused = not game.paused
            elif ch in (ord("o"), ord("O")):
                game.auto = not game.auto
            elif ch == curses.KEY_RESIZE:
                pass
            ch = stdscr.getch()

        if taking_over:
            game.auto = False

        now = time.monotonic()
        dt = now - last
        last = now

        h, w = stdscr.getmaxyx()
        if h != game.h or w != game.w:
            if h < 16 or w < 40:
                _too_small(stdscr)
                return
            game = Game(w, h)  # terminal resized: start clean at the new size

        game.update(dt, keys)
        game.render().blit(stdscr, attrs)
        stdscr.refresh()


def _too_small(stdscr) -> None:
    stdscr.erase()
    msg = "Terminal too small - please resize to at least 40x16."
    h, w = stdscr.getmaxyx()
    try:
        stdscr.addstr(max(0, h // 2), max(0, (w - len(msg)) // 2), msg[: max(0, w - 1)])
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.timeout(-1)
    stdscr.getch()


def _curses_main(stdscr, fps: float, no_color: bool) -> None:
    try:
        run_curses(stdscr, fps, no_color)
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------
# Headless self-test
# --------------------------------------------------------------------------


def selftest(steps: int = 900, w: int = 64, h: int = 24, seed: int = 7) -> int:
    """Run the simulation without a terminal and print a couple of frames."""
    game = Game(w, h, rng=random.Random(seed), auto=True)
    dt = 1.0 / 30.0
    shots = {}
    waves = set()

    for i in range(steps):
        game.update(dt)
        waves.add(game.wave)
        if i in (45, 200, 600):
            shots[i] = game.render().to_lines()

    print("space_invaders selftest")
    print(f"  steps={steps}  size={w}x{h}  dt={dt:.4f}s ({steps * dt:.1f}s simulated)")
    print(f"  score={game.score}  hi={game.hi}  wave seen={sorted(waves)}  "
          f"lives={game.lives}  state={game.state}")
    print(f"  aliens alive={len(game.alive)}/{len(game.aliens)}  "
          f"bullets={len(game.bullets)}  bombs={len(game.bombs)}")

    for i, lines in shots.items():
        print(f"\n--- frame @ step {i} (t={i * dt:.1f}s) ---")
        for line in lines:
            print(line)

    ok = game.score > 0 and len(waves) >= 1
    print("\nRESULT:", "OK" if ok else "FAILED (no scoring observed)")
    return 0 if ok else 1


# --------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Terminal Space Invaders animation.")
    parser.add_argument("--fps", type=float, default=30.0, help="target frames per second")
    parser.add_argument("--no-color", action="store_true", help="disable colors")
    parser.add_argument("--selftest", action="store_true", help="headless logic check, then exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("This animation needs an interactive terminal (a TTY).", file=sys.stderr)
        print("Run it directly in your shell, or try --selftest for a headless check.",
              file=sys.stderr)
        return 1

    fps = min(max(args.fps, 5.0), 120.0)
    curses.wrapper(_curses_main, fps, args.no_color)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
