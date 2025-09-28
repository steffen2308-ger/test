import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


CONFIG_FILE = Path(__file__).with_name("plot_config.json")


def load_configuration(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Konfigurationsdatei '{path}' wurde nicht gefunden.") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Konfigurationsdatei '{path}' ist nicht gültig: {exc}") from exc

    plots = data.get("plots")
    if not isinstance(plots, list) or not plots:
        raise RuntimeError("Die Konfiguration muss eine nicht-leere Liste 'plots' enthalten.")

    return plots


def generate_data(function_name: str) -> tuple[np.ndarray, np.ndarray]:
    function_name = function_name.lower()
    if function_name == "sin":
        x = np.linspace(0, 2 * math.pi, 400)
        y = np.sin(x)
    elif function_name == "cos":
        x = np.linspace(0, 2 * math.pi, 400)
        y = np.cos(x)
    elif function_name == "exp":
        x = np.linspace(0, 2, 400)
        y = np.exp(x)
    elif function_name == "quadratic":
        x = np.linspace(-5, 5, 400)
        y = x**2
    elif function_name == "log":
        x = np.linspace(0.1, 5, 400)
        y = np.log(x)
    else:
        raise ValueError(f"Unbekannte Funktion: {function_name}")
    return x, y


class PlotApp:
    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.root.title("Konfigurierbare Kurvenplots")

        try:
            self.plot_configs = load_configuration(config_path)
        except RuntimeError as exc:
            messagebox.showerror("Konfigurationsfehler", str(exc))
            root.destroy()
            raise SystemExit

        max_plots = min(4, len(self.plot_configs))
        if max_plots == 0:
            messagebox.showerror("Konfigurationsfehler", "Keine Plots in der Konfiguration vorhanden.")
            root.destroy()
            raise SystemExit

        options = [str(i) for i in range(1, max_plots + 1)]
        self.selected_plot_count = tk.StringVar(value=options[0])

        control_frame = ttk.Frame(root, padding=10)
        control_frame.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(control_frame, text="Anzahl der Plots:").pack(side=tk.LEFT)

        self.option_menu = ttk.OptionMenu(
            control_frame,
            self.selected_plot_count,
            options[0],
            *options,
            command=lambda _value: self.update_plots(),
        )
        self.option_menu.pack(side=tk.LEFT, padx=5)

        figure_frame = ttk.Frame(root)
        figure_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=figure_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, figure_frame)
        self.toolbar.update()
        self.canvas._tkcanvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.update_plots()

    def update_plots(self) -> None:
        try:
            count = int(self.selected_plot_count.get())
        except (TypeError, ValueError):
            count = 1
            self.selected_plot_count.set(str(count))

        available = len(self.plot_configs)
        if count > available:
            messagebox.showwarning(
                "Warnung",
                f"Es stehen nur {available} Konfigurationen zur Verfügung. Anzahl wird angepasst.",
            )
            count = available
            self.selected_plot_count.set(str(count))

        layout = self._determine_layout(count)
        self.figure.clear()

        axes = []
        for index in range(count):
            ax = self.figure.add_subplot(layout[0], layout[1], index + 1)
            axes.append(ax)

        for ax, config in zip(axes, self.plot_configs[:count]):
            try:
                x, y = generate_data(config.get("function", "sin"))
            except ValueError as exc:
                ax.text(0.5, 0.5, str(exc), ha="center", va="center", transform=ax.transAxes)
                ax.set_title(config.get("title", "Fehler"))
                continue

            ax.plot(
                x,
                y,
                color=config.get("color"),
                linestyle=config.get("linestyle", "-"),
                linewidth=config.get("linewidth", 2),
                marker=config.get("marker", ""),
                label=config.get("title", "Kurve"),
            )
            ax.set_title(config.get("title", "Kurve"))
            ax.grid(True, linestyle=":", linewidth=0.5)
            ax.legend(loc="best")

        self.figure.tight_layout()
        self.canvas.draw_idle()

    @staticmethod
    def _determine_layout(count: int) -> tuple[int, int]:
        if count == 1:
            return 1, 1
        if count == 2:
            return 1, 2
        return 2, 2


def main() -> None:
    root = tk.Tk()
    PlotApp(root, CONFIG_FILE)
    root.mainloop()


if __name__ == "__main__":
    main()
