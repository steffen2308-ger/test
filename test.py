"""Rundenbasiertes Jump-&-Run-Spiel mit einem Frosch auf schrumpfenden Blättern."""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import pygame


# Fenster- und Layoutparameter
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 900
HUD_HEIGHT = 110
GRID_MARGIN = 40
MAX_FPS = 60

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
FROG_COLOR = (240, 240, 120)

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

        self.running = True
        self.level = 1
        self.total_points = 0.0
        self.results: List[LevelResult] = []
        self.failure: Optional[FailureInfo] = None
        self.drag_start: Optional[Tuple[int, int]] = None

    def run(self) -> None:
        """Steuert den gesamten Spielablauf."""

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
        level_points = math.sqrt(grid_size * grid_size)
        last_update_ticks = level_start_ticks


        while self.running:
            now_ticks = pygame.time.get_ticks()
            elapsed_seconds = (now_ticks - level_start_ticks) / 1000.0
            delta_seconds = max(0.0, (now_ticks - last_update_ticks) / 1000.0)
            last_update_ticks = now_ticks

            self._update_leaves(
                leaves,
                now_ticks,
                lifetime,
                metrics.cell_size,
                delta_seconds,
                (start_position, goal_position),
            )

            outcome = self._handle_events(frog_position, grid_size)
            if outcome == "quit":
                return "quit", None

            current_leaf = leaves[frog_position[1]][frog_position[0]]
            if current_leaf is None or current_leaf.radius(now_ticks) <= LEAF_MIN_RADIUS:
                # Frosch ertrinkt
                time_seconds = (now_ticks - level_start_ticks) / 1000.0
                return "drowned", FailureInfo(self.level, grid_size, time_seconds)

            if tuple(frog_position) == goal_position:
                time_seconds = (now_ticks - level_start_ticks) / 1000.0
                return "completed", LevelResult(self.level, grid_size, time_seconds, level_points)

            self._draw_level(
                leaves,
                grid_size,
                metrics,
                frog_position,
                goal_position,
                lifetime,
                level_points,
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
        radius = cell_size * factor
        return Leaf(creation_ticks, lifetime, radius)

    def _update_leaves(
        self,
        leaves: List[List[Optional[Leaf]]],
        now_ticks: int,
        lifetime: float,
        cell_size: float,
        delta_seconds: float,
        required_positions: Sequence[Tuple[int, int]],
    ) -> None:
        """Aktualisiert vorhandene Blätter und lässt neue entstehen."""

        spawn_probability = 1.0 if lifetime <= 0 else 1.0 - math.exp(-delta_seconds / lifetime)
        required = set(required_positions)

        for row in range(len(leaves)):
            for col in range(len(leaves[row])):
                leaf = leaves[row][col]
                if leaf is not None:
                    if leaf.radius(now_ticks) <= 0.0:
                        leaves[row][col] = None
                else:
                    position = (col, row)
                    if position in required:
                        leaves[row][col] = self._generate_leaf(now_ticks, lifetime, cell_size)
                    elif random.random() < spawn_probability:
                        leaves[row][col] = self._generate_leaf(now_ticks, lifetime, cell_size)

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

                if (col, row) == goal_position:
                    pygame.draw.rect(self.screen, GOAL_COLOR, rect, 3)

        frog_rect = self._cell_rect(frog_position[0], frog_position[1], grid_size, metrics)
        pygame.draw.circle(self.screen, FROG_COLOR, frog_rect.center, int(metrics.cell_size * 0.3))

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
