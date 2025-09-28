"""Rundenbasiertes Jump-&-Run-Spiel mit einem Frosch auf schrumpfenden Blättern."""

from __future__ import annotations

import math
import random
import sys
import threading
from array import array
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import pygame

try:
    import pyttsx3  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyttsx3 = None  # type: ignore


# Fenster- und Layoutparameter
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 900
HUD_HEIGHT = 110
GRID_MARGIN = 40
MAX_FPS = 60
SOUND_SAMPLE_RATE = 44100

# Farben
BACKGROUND_COLOR = (18, 32, 64)
HUD_COLOR = (12, 24, 48)
TEXT_COLOR = (240, 240, 240)
WATER_COLOR = (30, 60, 120)
GRID_LINE_COLOR = (12, 28, 60)
LEAF_COLOR = (18, 140, 62)
LEAF_DANGER_COLOR = (222, 184, 54)
LEAF_DEAD_COLOR = (80, 80, 80)
GOAL_COLOR = (200, 60, 60)
FROG_BODY_COLOR = (62, 168, 74)
FROG_LIMB_COLOR = (48, 130, 60)
FROG_BELLY_COLOR = (204, 232, 182)
FROG_EYE_COLOR = (250, 250, 250)
FROG_PUPIL_COLOR = (20, 40, 20)
FROG_SCALE = 0.2
DIAMOND_COLOR = (210, 42, 42)

# Punktesystem
DIAMOND_SCORE = 10.0
JUMP_SCORE = 0.1
SURVIVAL_SCORE_PER_SECOND = 0.5
DIAMOND_SPAWN_PROBABILITY = 0.05

# Spielparameter
INITIAL_GRID_SIZE = 4
INITIAL_LIFETIME = 10.0  # Sekunden
LIFETIME_FACTOR = 0.9
LEAF_MIN_RADIUS = 6.0
LEAF_RADIUS_RANGE = (0.3, 0.65)
DRAG_THRESHOLD = 30


@dataclass
class Leaf:
    """Repräsentiert ein einzelnes Blatt, das im Lauf der Zeit schrumpft."""

    creation_ticks: int
    lifetime: float
    base_radius: float
    has_diamond: bool = False

    def radius(self, now_ticks: int) -> float:
        elapsed_seconds = max(0.0, (now_ticks - self.creation_ticks) / 1000.0)
        if self.lifetime <= 0:
            return 0.0
        progress = min(1.0, elapsed_seconds / self.lifetime)
        return max(0.0, self.base_radius * (1.0 - progress))


@dataclass
class LevelResult:
    """Ergebnisdaten eines abgeschlossenen Levels."""

    level: int
    grid_size: int
    time_seconds: float
    points: float


@dataclass
class FailureInfo:
    """Informationen über ein fehlgeschlagenes Level."""

    level: int
    grid_size: int
    time_seconds: float


class FrogJumpGame:
    """Hauptspielklasse für das rundenbasierte Froschspiel."""

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Frosch auf wackeligen Blättern")
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 24)
        self.small_font = pygame.font.SysFont("arial", 20)
        self.big_font = pygame.font.SysFont("arial", 36, bold=True)

        self.jump_sound: Optional[pygame.mixer.Sound] = None
        self.drop_sound: Optional[pygame.mixer.Sound] = None
        self.fanfare_sound: Optional[pygame.mixer.Sound] = None
        self.drown_sound: Optional[pygame.mixer.Sound] = None
        self.diamond_sound: Optional[pygame.mixer.Sound] = None
        self._init_sounds()

        self.voice_settings = self._init_voice_settings()

        self.running = True
        self.level = 1
        self.total_points = 0.0
        self.results: List[LevelResult] = []
        self.failure: Optional[FailureInfo] = None
        self.drag_start: Optional[Tuple[int, int]] = None
        self.current_level_points = 0.0

    def run(self) -> None:
        """Steuert den gesamten Spielablauf."""

        self._show_game_rules()

        while self.running:
            outcome, data = self.play_level()
            if outcome == "quit":
                break
            if outcome == "completed" and isinstance(data, LevelResult):
                self.results.append(data)
                self.total_points += data.points
                self.draw_level_summary(data)
                self.level += 1
                continue
            if outcome == "drowned" and isinstance(data, FailureInfo):
                self.failure = data
                break

        if self.running:
            self.draw_final_summary()

        pygame.quit()

    def play_level(self) -> Tuple[str, Optional[object]]:
        """Führt ein Level aus und liefert das Ergebnis."""

        grid_size = INITIAL_GRID_SIZE + self.level - 1
        lifetime = INITIAL_LIFETIME * (LIFETIME_FACTOR ** (self.level - 1))

        self._show_level_briefing(grid_size, lifetime)

        metrics = self._grid_metrics(grid_size)
        level_start_ticks = pygame.time.get_ticks()


        start_position = (0, 0)
        goal_position = (grid_size - 1, grid_size - 1)
        leaves = self._create_leaves(
            grid_size,
            lifetime,
            level_start_ticks,
            metrics.cell_size,
            start_position,
            goal_position,
        )
        frog_position = [start_position[0], start_position[1]]  # (x, y) mit y = 0 unterste Reihe
        self.current_level_points = math.sqrt(grid_size * grid_size)
        last_update_ticks = level_start_ticks


        while self.running:
            now_ticks = pygame.time.get_ticks()
            elapsed_seconds = (now_ticks - level_start_ticks) / 1000.0
            delta_seconds = max(0.0, (now_ticks - last_update_ticks) / 1000.0)
            last_update_ticks = now_ticks
            if delta_seconds > 0:
                self.current_level_points += SURVIVAL_SCORE_PER_SECOND * delta_seconds

            self._update_leaves(
                leaves,
                now_ticks,
                lifetime,
                metrics.cell_size,
                delta_seconds,
                (start_position, goal_position),
                (frog_position[0], frog_position[1]),
                grid_size,
            )

            outcome = self._handle_events(frog_position, grid_size)
            if outcome == "quit":
                return "quit", None

            current_leaf = leaves[frog_position[1]][frog_position[0]]
            if current_leaf is None or current_leaf.radius(now_ticks) <= LEAF_MIN_RADIUS:
                # Frosch ertrinkt
                time_seconds = (now_ticks - level_start_ticks) / 1000.0
                self._play_sound(self.drown_sound)
                return "drowned", FailureInfo(self.level, grid_size, time_seconds)

            if current_leaf.has_diamond:
                current_leaf.has_diamond = False
                self.current_level_points += DIAMOND_SCORE
                self._play_sound(self.diamond_sound)

            if tuple(frog_position) == goal_position:
                time_seconds = (now_ticks - level_start_ticks) / 1000.0
                self._play_sound(self.fanfare_sound)
                return "completed", LevelResult(
                    self.level, grid_size, time_seconds, self.current_level_points
                )

            self._draw_level(
                leaves,
                grid_size,
                metrics,
                frog_position,
                goal_position,
                lifetime,
                self.current_level_points,
                elapsed_seconds,
            )
            self.clock.tick(MAX_FPS)

        return "quit", None

    def _handle_events(self, frog_position: List[int], grid_size: int) -> str:
        """Verarbeitet Eingaben für Tastatur und Maus."""

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return "quit"

            if event.type == pygame.KEYDOWN:
                direction = self._direction_for_key(event.key)
                if direction:
                    self._try_move(frog_position, direction, grid_size)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.drag_start = event.pos

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.drag_start:
                dx = event.pos[0] - self.drag_start[0]
                dy = event.pos[1] - self.drag_start[1]
                if abs(dx) >= DRAG_THRESHOLD or abs(dy) >= DRAG_THRESHOLD:
                    direction = self._direction_from_drag(dx, dy)
                    if direction:
                        self._try_move(frog_position, direction, grid_size)
                self.drag_start = None

        return "continue"

    def _direction_for_key(self, key: int) -> Optional[Tuple[int, int]]:
        """Ordnet Richtungstasten und WASD einer Bewegungsrichtung zu."""

        mapping = {
            pygame.K_UP: (0, 1),
            pygame.K_w: (0, 1),
            pygame.K_DOWN: (0, -1),
            pygame.K_s: (0, -1),
            pygame.K_LEFT: (-1, 0),
            pygame.K_a: (-1, 0),
            pygame.K_RIGHT: (1, 0),
            pygame.K_d: (1, 0),
        }
        return mapping.get(key)

    def _direction_from_drag(self, dx: int, dy: int) -> Optional[Tuple[int, int]]:
        """Berechnet aus einer Drag-Bewegung die Sprungrichtung."""

        if abs(dx) > abs(dy):
            return (1, 0) if dx > 0 else (-1, 0)
        if abs(dy) > 0:
            # Bildschirm y wächst nach unten, daher Vorzeichen invertieren
            return (0, 1) if dy < 0 else (0, -1)
        return None

    def _try_move(self, frog_position: List[int], direction: Tuple[int, int], grid_size: int) -> None:
        """Bewegt den Frosch, sofern das Ziel innerhalb des Spielfelds liegt."""

        new_x = frog_position[0] + direction[0]
        new_y = frog_position[1] + direction[1]
        if 0 <= new_x < grid_size and 0 <= new_y < grid_size:
            frog_position[0] = new_x
            frog_position[1] = new_y
            self.current_level_points += JUMP_SCORE
            self._play_sound(self.jump_sound)

    def _create_leaves(
        self,
        grid_size: int,
        lifetime: float,
        creation_ticks: int,
        cell_size: float,
        start_position: Tuple[int, int],
        goal_position: Tuple[int, int],
    ) -> List[List[Optional[Leaf]]]:
        """Erzeugt die Blattmatrix mit zufälligen Startgrößen und Lücken."""

        required_positions = {start_position, goal_position}
        leaves: List[List[Optional[Leaf]]] = []
        for row in range(grid_size):
            row_leaves: List[Optional[Leaf]] = []
            for col in range(grid_size):
                position = (col, row)
                if position in required_positions or random.random() < 0.5:
                    row_leaves.append(
                        self._generate_leaf(creation_ticks, lifetime, cell_size)
                    )
                else:
                    row_leaves.append(None)
            leaves.append(row_leaves)
        return leaves

    def _generate_leaf(
        self, creation_ticks: int, lifetime: float, cell_size: float
    ) -> Leaf:
        """Erzeugt ein neues Blatt mit zufälligem Basisradius."""

        factor = random.uniform(*LEAF_RADIUS_RANGE)
        max_radius = cell_size * 0.48
        radius = min(cell_size * factor, max_radius)
        has_diamond = random.random() < DIAMOND_SPAWN_PROBABILITY
        return Leaf(creation_ticks, lifetime, radius, has_diamond)

    def _update_leaves(
        self,
        leaves: List[List[Optional[Leaf]]],
        now_ticks: int,
        lifetime: float,
        cell_size: float,
        delta_seconds: float,
        required_positions: Sequence[Tuple[int, int]],
        frog_position: Tuple[int, int],
        grid_size: int,
    ) -> None:
        """Aktualisiert vorhandene Blätter und lässt neue entstehen."""

        spawn_probability = 1.0 if lifetime <= 0 else 1.0 - math.exp(-delta_seconds / lifetime)
        required = set(required_positions)

        self._ensure_escape_leaf(
            leaves, now_ticks, lifetime, cell_size, frog_position, grid_size
        )

        drop_triggered = False
        for row in range(len(leaves)):
            for col in range(len(leaves[row])):
                leaf = leaves[row][col]
                if leaf is not None:
                    if leaf.radius(now_ticks) <= 0.0:
                        drop_triggered = True
                        leaves[row][col] = None
                else:
                    position = (col, row)
                    if position in required:
                        leaves[row][col] = self._generate_leaf(now_ticks, lifetime, cell_size)
                    elif random.random() < spawn_probability:
                        leaves[row][col] = self._generate_leaf(now_ticks, lifetime, cell_size)
        if drop_triggered:
            self._play_sound(self.drop_sound)

    def _ensure_escape_leaf(
        self,
        leaves: List[List[Optional[Leaf]]],
        now_ticks: int,
        lifetime: float,
        cell_size: float,
        frog_position: Tuple[int, int],
        grid_size: int,
    ) -> None:
        """Stellt sicher, dass kurz vor Ablauf des aktuellen Blatts ein Ausweg existiert."""

        if not (0 <= frog_position[0] < grid_size and 0 <= frog_position[1] < grid_size):
            return

        frog_leaf = leaves[frog_position[1]][frog_position[0]]
        if frog_leaf is None:
            return

        elapsed = (now_ticks - frog_leaf.creation_ticks) / 1000.0
        time_remaining = frog_leaf.lifetime - elapsed
        if time_remaining > 0.1:
            return

        directions = [(0, 1), (1, 0), (0, -1), (-1, 0)]
        safe_exists = False
        candidate_positions: List[Tuple[int, int]] = []

        for dx, dy in directions:
            nx = frog_position[0] + dx
            ny = frog_position[1] + dy
            if not (0 <= nx < grid_size and 0 <= ny < grid_size):
                continue
            neighbour = leaves[ny][nx]
            if neighbour is not None:
                if neighbour.radius(now_ticks) > LEAF_MIN_RADIUS:
                    safe_exists = True
                    break
                candidate_positions.append((nx, ny))
            else:
                candidate_positions.append((nx, ny))

        if safe_exists or not candidate_positions:
            return

        spawn_position = random.choice(candidate_positions)
        leaves[spawn_position[1]][spawn_position[0]] = self._generate_leaf(
            now_ticks, lifetime, cell_size
        )

    def _grid_metrics(self, grid_size: int) -> "GridMetrics":
        """Berechnet Zellgröße und Offsets für die Darstellung."""

        usable_width = WINDOW_WIDTH - 2 * GRID_MARGIN
        usable_height = WINDOW_HEIGHT - HUD_HEIGHT - 2 * GRID_MARGIN
        cell_size = min(usable_width / grid_size, usable_height / grid_size)
        offset_x = (WINDOW_WIDTH - cell_size * grid_size) / 2
        offset_y = HUD_HEIGHT + (WINDOW_HEIGHT - HUD_HEIGHT - cell_size * grid_size) / 2
        return GridMetrics(cell_size, offset_x, offset_y)

    def _draw_level(
        self,
        leaves: Sequence[Sequence[Optional[Leaf]]],
        grid_size: int,
        metrics: "GridMetrics",
        frog_position: Sequence[int],
        goal_position: Tuple[int, int],
        lifetime: float,
        level_points: float,
        elapsed_seconds: float,
    ) -> None:
        """Zeichnet Spielfeld, Frosch, HUD und Instruktionen."""

        self.screen.fill(BACKGROUND_COLOR)

        now_ticks = pygame.time.get_ticks()
        for row in range(grid_size):
            for col in range(grid_size):
                rect = self._cell_rect(col, row, grid_size, metrics)
                pygame.draw.rect(self.screen, WATER_COLOR, rect)
                pygame.draw.rect(self.screen, GRID_LINE_COLOR, rect, 1)

                leaf = leaves[row][col]
                if leaf is not None:
                    radius = leaf.radius(now_ticks)
                    if radius > 0:
                        ratio = radius / leaf.base_radius if leaf.base_radius > 0 else 0.0
                        color = self._blend_color(LEAF_DANGER_COLOR, LEAF_COLOR, ratio)
                        pygame.draw.circle(self.screen, color, rect.center, int(radius))
                        if leaf.has_diamond:
                            diamond_size = max(4, int(radius * 0.6))
                            cx, cy = rect.center
                            points = [
                                (cx, cy - diamond_size),
                                (cx + diamond_size, cy),
                                (cx, cy + diamond_size),
                                (cx - diamond_size, cy),
                            ]
                            pygame.draw.polygon(self.screen, DIAMOND_COLOR, points)

                if (col, row) == goal_position:
                    pygame.draw.rect(self.screen, GOAL_COLOR, rect, 3)

        frog_rect = self._cell_rect(frog_position[0], frog_position[1], grid_size, metrics)
        if FROG_SCALE != 1.0:
            frog_rect = frog_rect.inflate(
                -frog_rect.width * (1.0 - FROG_SCALE),
                -frog_rect.height * (1.0 - FROG_SCALE),
            )
        self._draw_frog(frog_rect)

        self._draw_hud(grid_size, lifetime, level_points, elapsed_seconds)
        self._draw_instructions()

        pygame.display.flip()

    def _draw_hud(
        self,
        grid_size: int,
        lifetime: float,
        level_points: float,
        elapsed_seconds: float,
    ) -> None:
        """Zeigt Levelinformationen und Punktestand."""

        hud_rect = pygame.Rect(0, 0, WINDOW_WIDTH, HUD_HEIGHT)
        pygame.draw.rect(self.screen, HUD_COLOR, hud_rect)

        texts = [
            f"Level: {self.level} ({grid_size}x{grid_size})",
            f"Gesamtpunkte: {self.total_points:.1f}",
            f"Punkte in diesem Level: {level_points:.1f}",
            f"Levelzeit: {elapsed_seconds:.1f}s",
            f"Blattlebensdauer: {lifetime:.1f}s",
        ]

        for index, text in enumerate(texts):
            label = self.font.render(text, True, TEXT_COLOR)
            self.screen.blit(label, (20, 10 + index * 20))

    def _draw_instructions(self) -> None:
        """Stellt Steuerungshinweise am unteren Bildschirmrand dar."""

        instruction = (
            "Steuerung: Pfeiltasten / WASD oder Maus ziehen. Ziel: rotes Feld rechts oben."
        )
        label = self.small_font.render(instruction, True, TEXT_COLOR)
        self.screen.blit(label, (20, WINDOW_HEIGHT - 30))

    def _show_game_rules(self) -> None:
        """Zeigt vor Spielbeginn die wichtigsten Regeln an."""

        lines = [
            "Springe von Blatt zu Blatt und erreiche das rote Ziel oben rechts.",
            "Blätter schrumpfen mit der Zeit – halte den Frosch in Bewegung.",
            "Nutze Pfeiltasten/WASD oder ziehe mit der Maus, um zu springen.",
            "Wenn ein Blatt verschwindet, fällt der Frosch ins Wasser und das Level endet.",
        ]
        self._speak_with_darth_voice(lines)
        self._show_overlay(
            "Spielregeln",
            lines,
            "Start mit Enter, Leertaste oder Mausklick",
        )

    def _show_level_briefing(self, grid_size: int, lifetime: float) -> None:
        """Erläutert vor jedem Level das Punktesystem."""

        points_start = self._format_points(math.sqrt(grid_size * grid_size))
        points_jump = self._format_points(JUMP_SCORE)
        points_survival = self._format_points(SURVIVAL_SCORE_PER_SECOND)
        points_diamond = self._format_points(DIAMOND_SCORE)

        lines = [
            f"Level {self.level}: Spielfeld {grid_size}x{grid_size}, Blätter leben ca. {lifetime:.1f}s.",
            f"Du startest mit {points_start} Punkten in diesem Level.",
            f"Jeder Sprung bringt +{points_jump} Punkte.",
            f"Überleben bringt +{points_survival} Punkte pro Sekunde.",
            f"Jeder Diamant liefert +{points_diamond} Punkte.",
        ]

        self._show_overlay(
            "Punkteübersicht",
            lines,
            "Level starten mit Enter, Leertaste oder Mausklick",
        )

    def _format_points(self, value: float) -> str:
        """Formatiert Punktwerte ohne überflüssige Nachkommastellen."""

        rounded = round(value)
        if math.isclose(value, rounded, rel_tol=1e-9, abs_tol=1e-9):
            return str(int(rounded))
        return f"{value:.1f}"

    def _cell_rect(
        self,
        col: int,
        row: int,
        grid_size: int,
        metrics: "GridMetrics",
    ) -> pygame.Rect:
        """Berechnet das Rechteck einer Zelle basierend auf der Spielkoordinate."""

        x = metrics.offset_x + col * metrics.cell_size
        inverted_row = grid_size - 1 - row
        y = metrics.offset_y + inverted_row * metrics.cell_size
        return pygame.Rect(int(x), int(y), int(metrics.cell_size), int(metrics.cell_size))

    def draw_level_summary(self, result: LevelResult) -> None:
        """Zeigt eine Übersicht nach einem abgeschlossenen Level."""

        title = f"Level {result.level} geschafft!"
        lines = [
            f"Benötigte Zeit: {result.time_seconds:.1f} Sekunden",
            f"Punkte in diesem Level: {result.points:.1f}",
            f"Gesamtpunkte: {self.total_points:.1f}",
        ]
        self._show_overlay(title, lines, "Weiter mit Enter, Leertaste oder Mausklick")

    def draw_final_summary(self) -> None:
        """Zeigt die Übersicht am Ende des Spiels."""

        total_time = math.fsum(result.time_seconds for result in self.results)

        lines: List[str] = []
        if self.results:
            lines.append("Abgeschlossene Level:")
            for result in self.results:
                lines.append(
                    f"  Level {result.level} ({result.grid_size}x{result.grid_size}): "
                    f"{result.time_seconds:.1f}s – {result.points:.1f} Punkte"
                )
        else:
            lines.append("Keine Level abgeschlossen.")

        lines.append(f"Gesamtpunkte: {self.total_points:.1f}")
        lines.append(f"Gesamtzeit: {total_time:.1f} Sekunden")

        if self.failure:
            lines.append(
                f"Spielende in Level {self.failure.level} nach {self.failure.time_seconds:.1f} Sekunden."
            )

        self._show_overlay("Spiel beendet", lines, "Fenster schließen oder Taste drücken, um zu beenden")

    def _show_overlay(self, title: str, lines: Sequence[str], prompt: str) -> None:
        """Blendet ein halbtransparentes Overlay mit Text ein und wartet auf Eingabe."""

        while self.running:
            self._draw_overlay_contents(title, lines, prompt)
            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    return
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return
                if event.type == pygame.MOUSEBUTTONDOWN:
                    return

            self.clock.tick(30)

    def _draw_overlay_contents(self, title: str, lines: Sequence[str], prompt: str) -> None:
        """Zeichnet den Inhalt des Overlays."""

        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
        overlay.set_alpha(210)
        overlay.fill((0, 0, 0))
        self.screen.blit(overlay, (0, 0))

        title_label = self.big_font.render(title, True, TEXT_COLOR)
        title_rect = title_label.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 100))
        self.screen.blit(title_label, title_rect)

        for index, line in enumerate(lines):
            label = self.font.render(line, True, TEXT_COLOR)
            rect = label.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 40 + index * 30))
            self.screen.blit(label, rect)

        prompt_label = self.small_font.render(prompt, True, TEXT_COLOR)
        prompt_rect = prompt_label.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 120))
        self.screen.blit(prompt_label, prompt_rect)

    def _blend_color(
        self,
        start_color: Tuple[int, int, int],
        end_color: Tuple[int, int, int],
        ratio: float,
    ) -> Tuple[int, int, int]:
        """Mischt zwei Farben anhand eines Faktors im Bereich [0, 1]."""

        clamped = max(0.0, min(1.0, ratio))
        return tuple(
            int(start + (end - start) * clamped) for start, end in zip(start_color, end_color)
        )

    def _draw_frog(self, cell_rect: pygame.Rect) -> None:
        """Zeichnet einen stilisierten Frosch innerhalb der gegebenen Zelle."""

        body_rect = cell_rect.inflate(-cell_rect.width * 0.25, -cell_rect.height * 0.3)
        head_rect = pygame.Rect(0, 0, int(cell_rect.width * 0.6), int(cell_rect.height * 0.45))
        head_rect.center = (
            cell_rect.centerx,
            int(cell_rect.centery - cell_rect.height * 0.2),
        )
        belly_rect = body_rect.inflate(-body_rect.width * 0.45, -body_rect.height * 0.35)

        pygame.draw.ellipse(self.screen, FROG_BODY_COLOR, body_rect)
        pygame.draw.ellipse(self.screen, FROG_BODY_COLOR, head_rect)
        pygame.draw.ellipse(self.screen, FROG_BELLY_COLOR, belly_rect)

        leg_width = max(2, int(cell_rect.width * 0.1))
        leg_length = int(cell_rect.height * 0.35)
        back_leg_y = int(cell_rect.bottom - cell_rect.height * 0.2)
        front_leg_y = int(cell_rect.centery + cell_rect.height * 0.15)
        pygame.draw.line(
            self.screen,
            FROG_LIMB_COLOR,
            (int(cell_rect.centerx - cell_rect.width * 0.25), front_leg_y),
            (int(cell_rect.centerx - cell_rect.width * 0.35), front_leg_y + leg_length // 2),
            leg_width,
        )
        pygame.draw.line(
            self.screen,
            FROG_LIMB_COLOR,
            (int(cell_rect.centerx + cell_rect.width * 0.25), front_leg_y),
            (int(cell_rect.centerx + cell_rect.width * 0.35), front_leg_y + leg_length // 2),
            leg_width,
        )
        pygame.draw.line(
            self.screen,
            FROG_LIMB_COLOR,
            (int(cell_rect.centerx - cell_rect.width * 0.35), back_leg_y),
            (int(cell_rect.centerx - cell_rect.width * 0.2), back_leg_y + leg_length // 3),
            leg_width,
        )
        pygame.draw.line(
            self.screen,
            FROG_LIMB_COLOR,
            (int(cell_rect.centerx + cell_rect.width * 0.35), back_leg_y),
            (int(cell_rect.centerx + cell_rect.width * 0.2), back_leg_y + leg_length // 3),
            leg_width,
        )

        eye_radius = max(2, int(cell_rect.width * 0.08))
        eye_offset_x = int(cell_rect.width * 0.18)
        eye_offset_y = int(cell_rect.height * 0.33)
        left_eye_center = (cell_rect.centerx - eye_offset_x, cell_rect.centery - eye_offset_y)
        right_eye_center = (cell_rect.centerx + eye_offset_x, cell_rect.centery - eye_offset_y)
        pygame.draw.circle(self.screen, FROG_EYE_COLOR, left_eye_center, eye_radius)
        pygame.draw.circle(self.screen, FROG_EYE_COLOR, right_eye_center, eye_radius)

        pupil_radius = max(1, int(eye_radius * 0.5))
        pygame.draw.circle(self.screen, FROG_PUPIL_COLOR, left_eye_center, pupil_radius)
        pygame.draw.circle(self.screen, FROG_PUPIL_COLOR, right_eye_center, pupil_radius)

        mouth_width = int(cell_rect.width * 0.35)
        mouth_y = int(cell_rect.centery - cell_rect.height * 0.02)
        pygame.draw.arc(
            self.screen,
            FROG_PUPIL_COLOR,
            pygame.Rect(
                cell_rect.centerx - mouth_width,
                mouth_y,
                mouth_width * 2,
                int(cell_rect.height * 0.25),
            ),
            math.radians(10),
            math.radians(170),
            max(1, int(cell_rect.height * 0.03)),
        )

    def _init_sounds(self) -> None:
        """Initialisiert einfache Synthesizer-Sounds für Spielereignisse."""

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=SOUND_SAMPLE_RATE, size=-16, channels=1)
        except pygame.error:
            return

        self.jump_sound = self._create_tone([(780, 60, 0.5), (880, 40, 0.45)])
        self.drop_sound = self._create_tone([(1400, 30, 0.5), (900, 80, 0.4)])
        self.fanfare_sound = self._create_tone(
            [
                (392, 120, 0.55),
                (523, 160, 0.6),
                (659, 160, 0.65),
                (784, 200, 0.7),
                (988, 220, 0.75),
                (1175, 260, 0.75),
            ]
        )
        self.drown_sound = self._create_tone(
            [
                (220, 120, 0.6),
                (160, 140, 0.55),
                (110, 200, 0.5),
                (80, 260, 0.45),
            ]
        )
        self.diamond_sound = self._create_tone(
            [
                (660, 70, 0.55),
                (990, 90, 0.6),
                (1320, 160, 0.75),
            ]
        )

    def _init_voice_settings(self) -> Optional[dict]:
        """Bereitet Einstellungen für die Sprachsynthese im Darth-Vader-Stil vor."""

        if pyttsx3 is None:
            return None

        try:
            engine = pyttsx3.init()
        except Exception:
            return None

        try:
            voice_id = self._select_darth_voice(engine)
            settings = {
                "voice_id": voice_id,
                "rate": 110,
                "volume": 1.0,
                "pitch": 35,
            }
            engine.stop()
            return settings
        except Exception:
            return None

    def _select_darth_voice(self, engine: "pyttsx3.Engine") -> Optional[str]:
        """Wählt eine tiefe Stimme aus und bevorzugt deutschsprachige Varianten."""

        try:
            voices = engine.getProperty("voices")
        except Exception:
            return None

        if not voices:
            return None

        fallback = voices[0].id

        keyword_orders = [
            ("vader", "dark"),
            ("darth",),
            ("bass", "baritone"),
            ("male", "mann"),
        ]

        for keywords in keyword_orders:
            for voice in voices:
                descriptor = f"{voice.id} {voice.name}".lower()
                if all(keyword in descriptor for keyword in keywords):
                    return voice.id

        german_preferences = ("de+", "german", "deu")
        for preference in german_preferences:
            for voice in voices:
                descriptor = f"{voice.id} {voice.name}".lower()
                if preference in descriptor and ("m3" in descriptor or "male" in descriptor):
                    return voice.id

        return fallback

    def _create_tone(
        self, tones: Sequence[Tuple[float, int, float]]
    ) -> Optional[pygame.mixer.Sound]:
        """Erzeugt einen Ton aus Frequenz-, Dauer- und Lautstärkeangaben."""

        if not tones:
            return None

        samples = array("h")
        sample_rate = SOUND_SAMPLE_RATE

        for frequency, duration_ms, volume in tones:
            clamped_volume = max(0.0, min(1.0, volume))
            amplitude = int(32767 * clamped_volume)
            sample_count = max(1, int(sample_rate * (duration_ms / 1000.0)))
            angular_frequency = 2.0 * math.pi * max(0.0, frequency)
            for index in range(sample_count):
                value = (
                    math.sin(angular_frequency * index / sample_rate)
                    if frequency > 0
                    else 0.0
                )
                samples.append(int(amplitude * value))

        try:
            return pygame.mixer.Sound(buffer=samples.tobytes())
        except pygame.error:
            return None

    def _play_sound(self, sound: Optional[pygame.mixer.Sound]) -> None:
        """Spielt einen Sound ab, sofern verfügbar."""

        if sound is not None:
            try:
                sound.play()
            except pygame.error:
                pass

    def _speak_with_darth_voice(self, lines: Sequence[str]) -> None:
        """Liest Text mithilfe von Sprachausgabe in tiefer Darth-Vader-Stimme vor."""

        if pyttsx3 is None or self.voice_settings is None:
            return

        text = " ".join(line.strip() for line in lines if line.strip())
        if not text:
            return

        settings = dict(self.voice_settings)

        def _run_voice() -> None:
            try:
                engine = pyttsx3.init()
                voice_id = settings.get("voice_id")
                if voice_id:
                    try:
                        engine.setProperty("voice", voice_id)
                    except Exception:
                        pass
                try:
                    engine.setProperty("rate", settings.get("rate", 110))
                except Exception:
                    pass
                try:
                    engine.setProperty("volume", settings.get("volume", 1.0))
                except Exception:
                    pass
                try:
                    engine.setProperty("pitch", settings.get("pitch", 35))
                except Exception:
                    pass

                intro = "Ich bin dein Spielleiter. *schweres Atmen*."
                engine.say(intro)
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception:
                pass

        threading.Thread(target=_run_voice, daemon=True).start()


@dataclass
class GridMetrics:
    """Hilfsstruktur mit Darstellungsparametern für das Raster."""

    cell_size: float
    offset_x: float
    offset_y: float


def main() -> None:
    """Startpunkt für das Spiel."""

    game = FrogJumpGame()
    try:
        game.run()
    except Exception:
        pygame.quit()
        raise


if __name__ == "__main__":
    sys.exit(main())
