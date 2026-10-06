"""Terminal display logic — single source of truth for signal labels."""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

SIGNAL_LABELS: dict[int, dict] = {
    1: {"action": "Buy / Go Long", "emoji": "📈", "color": "green", "short": "📈 Buy"},
    0: {
        "action": "Hold / No Change",
        "emoji": "➡️",
        "color": "yellow",
        "short": "➡️ Hold",
    },
    -1: {
        "action": "Sell / Go Short",
        "emoji": "📉",
        "color": "red",
        "short": "📉 Sell",
    },
}


def banner() -> None:
    console.print(
        """
    ╔═══════════════════════════════════════════════╗
    ║     FX Trading ML Pipeline System             ║
    ║     Train Models & Make Predictions           ║
    ╚═══════════════════════════════════════════════╝
    """,
        style="bold cyan",
    )


def prediction_result(result: dict) -> None:
    sig = SIGNAL_LABELS.get(
        result["prediction"], {"action": "Unknown", "emoji": "❓", "color": "white"}
    )

    table = Table(
        title=f"{result['pair']} Prediction Result",
        box=box.ROUNDED,
        style="bold",
    )
    table.add_column("Date", justify="center", style="cyan")
    table.add_column("Open Price", justify="center", style="yellow")
    table.add_column("Prediction", justify="center", style=sig["color"])
    table.add_column("Recommended Action", justify="center", style=sig["color"])
    table.add_row(
        str(result["date"]),
        f"{result['open_price']:.4f}",
        f"{sig['emoji']} {result['prediction']}",
        sig["action"],
    )
    console.print(
        Panel(
            table,
            title="[bold]Prediction Complete[/bold]",
            subtitle="Powered by MLPClassifier",
            expand=False,
            border_style=sig["color"],
        )
    )

    p = result["prediction"]
    console.print("\n[bold]Interpretation:[/bold]")
    if p == 1:
        console.print(
            "  • Expected [green]bullish[/green] move — consider buying / going long"
        )
    elif p == -1:
        console.print(
            "  • Expected [red]bearish[/red] move — consider selling / going short"
        )
    else:
        console.print("  • Expected [yellow]neutral[/yellow] move — consider holding")
    console.print("\n[dim]⚠ Model prediction only — not financial advice.[/dim]")


def logging_result(result: dict) -> None:
    ohlcv = Table(
        title=f"{result['pair']} Market Data — {result['date']}",
        box=box.ROUNDED,
        style="bold cyan",
    )
    for col in ("Open", "High", "Low", "Close", "Volume"):
        ohlcv.add_column(col, justify="right")
    ohlcv.add_row(
        f"{result['open_price']:.4f}",
        f"{result['high']:.4f}",
        f"{result['low']:.4f}",
        f"{result['close']:.4f}",
        f"{result['volume']:.0f}",
    )
    console.print("\n")
    console.print(ohlcv)

    pred_lbl = SIGNAL_LABELS.get(result["predicted"], {}).get("short", "❓")
    actual_lbl = SIGNAL_LABELS.get(result["actual"], {}).get("short", "❓")
    correct = result["correct"]

    res_table = Table(title="Prediction vs Actual", box=box.ROUNDED, style="bold")
    res_table.add_column("Predicted", justify="center", style="yellow")
    res_table.add_column("Actual", justify="center", style="yellow")
    res_table.add_column("Result", justify="center")
    res_table.add_row(
        f"{pred_lbl} ({result['predicted']})",
        f"{actual_lbl} ({result['actual']})",
        (
            "[bold green]✓ CORRECT[/bold green]"
            if correct
            else "[bold red]✗ INCORRECT[/bold red]"
        ),
    )
    console.print(
        Panel(
            res_table,
            title="[bold]Actual Values Logged[/bold]",
            expand=False,
            border_style="green" if correct else "red",
        )
    )

    delta = result["close"] - result["open_price"]
    color = "green" if delta > 0 else ("red" if delta < 0 else "yellow")
    word = "increased" if delta > 0 else ("decreased" if delta < 0 else "unchanged")
    console.print("[bold]Analysis:[/bold]")
    console.print(f"  • Price [{color}]{word}[/{color}] by {abs(delta):.4f}")

    accuracy_metrics(result["pair"], result["metrics"], result["accuracy_by_type"])


def accuracy_metrics(pair: str, metrics: dict, by_type: dict) -> None:
    console.print("\n[bold cyan]═══ Accuracy Metrics ═══[/bold cyan]\n")

    t = Table(title=f"{pair} Overall Performance", box=box.ROUNDED)
    t.add_column("Metric", style="cyan")
    t.add_column("Value", justify="right", style="yellow")
    t.add_row("Total Predictions", str(metrics["total_predictions"]))
    t.add_row("Completed", str(metrics["completed_predictions"]))
    t.add_row("Correct", f"[green]{metrics['correct_count']}[/green]")
    t.add_row("Incorrect", f"[red]{metrics['incorrect_count']}[/red]")
    t.add_row("Overall Accuracy", f"{metrics['overall_accuracy']:.2f}%")
    if metrics["completed_predictions"] >= 10:
        t.add_row("Rolling (10)", f"{metrics['rolling_accuracy_10']:.2f}%")
    if metrics["completed_predictions"] >= 30:
        t.add_row("Rolling (30)", f"{metrics['rolling_accuracy_30']:.2f}%")
    console.print(t)

    if by_type:
        t2 = Table(title="Accuracy by Signal Type", box=box.ROUNDED)
        t2.add_column("Signal", style="cyan")
        t2.add_column("Count", justify="right")
        t2.add_column("Correct", justify="right", style="green")
        t2.add_column("Accuracy", justify="right", style="yellow")
        for sig, stats in sorted(by_type.items()):
            label = SIGNAL_LABELS.get(sig, {}).get("short", str(sig))
            t2.add_row(
                label,
                str(stats["count"]),
                str(stats["correct"]),
                f"{stats['accuracy']:.2f}%",
            )
        console.print("\n")
        console.print(t2)
