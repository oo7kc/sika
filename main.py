"""CLI entry point — routing only.

Modes:
    interactive  — prompted menu (default)
    train        — train one or all pairs
    predict      — make a prediction for a pair
    log          — record actual values and update accuracy

Examples:
    python main.py
    python main.py --mode train --all
    python main.py --mode predict --pair XAUUSD --open 2650.50
    python main.py --mode log --pair XAUUSD --date 2024-11-22 --high 2651 --low 2645 --close 2648
"""

import argparse
import traceback
from datetime import date
from pathlib import Path

from rich import box
from rich.prompt import Confirm, Prompt
from rich.table import Table

import scripts.display as display
from config import Config
from scripts.fetch import MarketDataPipeline
from scripts.log import LoggingPipeline
from scripts.predict import PredictionPipeline
from scripts.train import TrainingPipeline

cfg = Config()


# / Pair discovery helpers /


def available_pairs() -> list[str]:
    return [p for p in cfg.TRADING_PAIRS if Path(cfg.get_paths(p)["raw_data"]).exists()]


def trained_pairs() -> list[str]:
    return [
        p
        for p in cfg.TRADING_PAIRS
        if Path(cfg.get_paths(p)["model"]).exists()
        and Path(cfg.get_paths(p)["scaler"]).exists()
    ]


def pairs_with_logs() -> list[str]:
    return [p for p in cfg.TRADING_PAIRS if Path(cfg.get_paths(p)["log"]).exists()]


# / Prompt helpers /


def pick_pair(options: list[str], prompt: str) -> str:
    for i, p in enumerate(options, 1):
        display.console.print(f"  {i}. {p}")
    display.console.print(f"  {len(options) + 1}. Custom pair")
    choice = Prompt.ask(
        f"\n[cyan]{prompt}[/cyan]",
        choices=[str(i) for i in range(1, len(options) + 2)],
        default="1",
    )
    idx = int(choice) - 1
    if idx < len(options):
        return options[idx]
    return Prompt.ask("[cyan]Enter trading pair (e.g. EURUSD)[/cyan]").upper()


def ask_price(label: str, min_val: float = 0.0, max_val: float = float("inf")) -> float:
    while True:
        try:
            v = float(Prompt.ask(f"[cyan]{label}[/cyan]"))
            if min_val < v <= max_val:
                return v
            display.console.print(f"[bold red]Must be > {min_val}[/bold red]")
        except ValueError:
            display.console.print("[bold red]Enter a valid number[/bold red]")


def ask_date(prompt: str) -> date:
    while True:
        try:
            return date.fromisoformat(Prompt.ask(f"[cyan]{prompt}[/cyan]"))
        except ValueError:
            display.console.print("[bold red]Use YYYY-MM-DD format[/bold red]")


def run_training(pairs: list[str]):
    ok, fail = 0, 0
    for i, pair in enumerate(pairs, 1):
        display.console.print(
            f"\n{'=' * 50}\nTraining {i}/{len(pairs)}: {pair}\n{'=' * 50}\n"
        )
        try:
            TrainingPipeline(pair=pair).run()
            display.console.print(f"\n[bold green]✓ Trained {pair}[/bold green]")
            ok += 1
        except Exception as e:
            display.console.print(f"\n[bold red]✗ Failed {pair}:[/bold red] {e}")
            fail += 1
            if Confirm.ask("[dim]Show traceback?[/dim]", default=False):
                display.console.print(f"[dim]{traceback.format_exc()}[/dim]")

    display.console.print(f"\n{'=' * 50}")
    display.console.print(
        f"[green]✓ OK: {ok}[/green]"
        + (f"   [red]✗ Failed: {fail}[/red]" if fail else "")
    )
    display.console.print(f"{'=' * 50}\n")


# / Interactive screens /


def train_screen():
    display.console.print("\n[bold cyan]═══ TRAINING MODE ═══[/bold cyan]\n")
    pairs = available_pairs()
    if not pairs:
        display.console.print(
            f"[bold red]✗ No data files found in {cfg.RAW_DATA_DIR}[/bold red]"
        )
        return

    display.console.print(
        f"[bold green]✓ Data found for:[/bold green] {', '.join(pairs)}\n"
    )
    if Confirm.ask("[cyan]Train all available pairs?[/cyan]", default=False):
        to_train = pairs
    else:
        display.console.print("[bold]Available pairs:[/bold]")
        pair = pick_pair(pairs, "Select a pair to train")
        if pair not in pairs and not Path(cfg.get_paths(pair)["raw_data"]).exists():
            display.console.print(f"[bold red]✗ Data not found for {pair}[/bold red]")
            return
        to_train = [pair]

    if Confirm.ask("[bold cyan]Proceed?[/bold cyan]", default=True):
        run_training(to_train)
    else:
        display.console.print("[yellow]Cancelled.[/yellow]")


def predict_screen():
    display.console.print("\n[bold cyan]═══ PREDICTION MODE ═══[/bold cyan]\n")
    pairs = trained_pairs()
    if not pairs:
        display.console.print(
            "[bold red]✗ No trained models found. Train first.[/bold red]"
        )
        return

    display.console.print(
        f"[bold green]✓ Trained models:[/bold green] {', '.join(pairs)}\n"
    )
    display.console.print("[bold]Select pair:[/bold]")
    pair = pick_pair(pairs, "Select a pair")
    if pair not in pairs and not Path(cfg.get_paths(pair)["model"]).exists():
        display.console.print(f"[bold red]✗ No model for {pair}[/bold red]")
        return

    prediction_date = (
        date.today()
        if Confirm.ask("\n[cyan]Use today's date?[/cyan]", default=True)
        else ask_date("Date (YYYY-MM-DD)")
    )
    if Confirm.ask("[cyan]Fetch open/spot from API?[/cyan]", default=True):
        try:
            open_price = MarketDataPipeline(pair=pair).fetch_prediction_open(
                prediction_date=prediction_date
            )
            display.console.print(
                f"[bold green]✓ API open/spot fetched:[/bold green] {open_price:.4f}"
            )
        except Exception as e:
            display.console.print(f"[bold red]API error:[/bold red] {e}")
            open_price = ask_price("Today's Open price")
    else:
        open_price = ask_price("Today's Open price")

    display.console.print(f"\n─ {pair}  {prediction_date}  open={open_price} ─")
    if not Confirm.ask("[bold cyan]Proceed?[/bold cyan]", default=True):
        display.console.print("[yellow]Cancelled.[/yellow]")
        return

    try:
        result = PredictionPipeline(pair=pair).run(
            open_price=open_price, prediction_date=prediction_date
        )
        display.prediction_result(result)
    except Exception as e:
        display.console.print(f"\n[bold red]Error:[/bold red] {e}")
        if Confirm.ask("[dim]Show traceback?[/dim]", default=False):
            display.console.print(f"[dim]{traceback.format_exc()}[/dim]")


def log_screen():
    display.console.print("\n[bold cyan]═══ LOGGING MODE ═══[/bold cyan]\n")
    pairs = pairs_with_logs()
    if not pairs:
        display.console.print(
            "[bold red]✗ No prediction logs found. Make predictions first.[/bold red]"
        )
        return

    display.console.print(f"[bold green]✓ Logs for:[/bold green] {', '.join(pairs)}\n")
    display.console.print("[bold]Select pair:[/bold]")
    for i, p in enumerate(pairs, 1):
        display.console.print(f"  {i}. {p}")
    choice = Prompt.ask(
        "\n[cyan]Select[/cyan]",
        choices=[str(i) for i in range(1, len(pairs) + 1)],
        default="1",
    )
    pair = pairs[int(choice) - 1]

    try:
        pipeline = LoggingPipeline(pair=pair)
        log = pipeline.load_prediction_log()
        pending = pipeline.get_pending_predictions(log)
    except Exception as e:
        display.console.print(f"[bold red]Error:[/bold red] {e}")
        return

    if pending.empty:
        display.console.print("\n[bold yellow]No pending predictions.[/bold yellow]")
        display.accuracy_metrics(
            pair,
            pipeline.calculate_accuracy_metrics(log),
            pipeline.get_accuracy_by_prediction_type(log),
        )
        return

    t = Table(show_header=True, header_style="bold cyan", box=box.SIMPLE)
    t.add_column("Date", style="cyan")
    t.add_column("Predicted", style="yellow")
    for pred_date, row in pending.iterrows():
        sig = int(row["Predicted"])
        t.add_row(
            str(pred_date), display.SIGNAL_LABELS.get(sig, {}).get("short", str(sig))
        )
    display.console.print("\n[bold]Pending:[/bold]")
    display.console.print(t)

    log_date = ask_date("Date to log (YYYY-MM-DD)")
    if log_date not in pending.index:
        display.console.print(
            f"[bold red]No pending prediction for {log_date}[/bold red]"
        )
        return

    high = ask_price("High price")
    low = ask_price("Low price", max_val=high)
    close = ask_price("Close price", min_val=low - 1e-12, max_val=high)
    while True:
        try:
            volume = float(Prompt.ask("[cyan]Volume[/cyan]", default="0"))
            if volume >= 0:
                break
        except ValueError:
            pass

    display.console.print(
        f"\n─ {pair}  {log_date}  H:{high}  L:{low}  C:{close}  V:{volume} ─"
    )
    if not Confirm.ask("[bold cyan]Proceed?[/bold cyan]", default=True):
        display.console.print("[yellow]Cancelled.[/yellow]")
        return

    try:
        result = pipeline.run(
            prediction_date=log_date, high=high, low=low, close=close, volume=volume
        )
        display.logging_result(result)
    except Exception as e:
        display.console.print(f"\n[bold red]Error:[/bold red] {e}")
        if Confirm.ask("[dim]Show traceback?[/dim]", default=False):
            display.console.print(f"[dim]{traceback.format_exc()}[/dim]")


def sync_screen():
    display.console.print("\n[bold cyan]═══ API SYNC MODE ═══[/bold cyan]\n")
    display.console.print("[bold]Available pairs:[/bold]")
    pair = pick_pair(cfg.TRADING_PAIRS, "Select a pair to sync")
    if pair not in cfg.TRADING_PAIRS:
        display.console.print(f"[bold red]✗ Unsupported pair: {pair}[/bold red]")
        return

    try:
        path = MarketDataPipeline(pair=pair).sync_raw_data()
        display.console.print(f"[bold green]✓ Synced[/bold green] {pair} → {path}")
    except Exception as e:
        display.console.print(f"[bold red]Error:[/bold red] {e}")


def interactive_mode():
    display.banner()
    screens = {"1": train_screen, "2": predict_screen, "3": log_screen, "4": sync_screen}
    while True:
        display.console.print("\n[bold]What would you like to do?[/bold]")
        display.console.print(
            "  1. Train Model(s)\n  2. Make Prediction\n  3. Log Actual Values\n  4. Sync API Data\n  5. Exit"
        )
        choice = Prompt.ask(
            "\n[cyan]Select[/cyan]", choices=["1", "2", "3", "4", "5"], default="2"
        )
        if choice == "5":
            display.console.print("\n[bold green]Bye![/bold green]")
            break
        try:
            screens[choice]()
        except KeyboardInterrupt:
            display.console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as e:
            display.console.print(f"\n[bold red]Error:[/bold red] {e}")
        if not Confirm.ask("\n[cyan]Perform another operation?[/cyan]", default=True):
            display.console.print("\n[bold green]Bye![/bold green]")
            break


# CLI entry point


def main():
    parser = argparse.ArgumentParser(description="FX Trading ML Pipeline")
    parser.add_argument(
        "--mode",
        choices=["train", "predict", "log", "sync", "interactive"],
        default="interactive",
    )
    parser.add_argument("--pair", type=str, default=None)
    parser.add_argument("--all", action="store_true", help="Train all pairs")
    parser.add_argument("--open", type=float, default=None)
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--high", type=float, default=None)
    parser.add_argument("--low", type=float, default=None)
    parser.add_argument("--close", type=float, default=None)
    parser.add_argument("--volume", type=float, default=0)
    args = parser.parse_args()

    if args.mode == "interactive":
        interactive_mode()
        return

    display.banner()

    if args.mode == "train":
        pairs = available_pairs()
        if not pairs:
            display.console.print(
                f"[bold red]✗ No data in {cfg.RAW_DATA_DIR}[/bold red]"
            )
            return
        if args.all:
            to_train = pairs
        elif args.pair:
            pair = args.pair.upper()
            if not Path(cfg.get_paths(pair)["raw_data"]).exists():
                display.console.print(
                    f"[bold red]✗ Data not found for {pair}[/bold red]"
                )
                return
            to_train = [pair]
        else:
            to_train = [pairs[0]]
            display.console.print(f"No --pair given, defaulting to {to_train[0]}")
        run_training(to_train)

    elif args.mode == "predict":
        if not args.pair:
            display.console.print("[bold red]--pair is required[/bold red]")
            return
        prediction_date = date.fromisoformat(args.date) if args.date else date.today()
        try:
            open_price = args.open
            if open_price is None:
                open_price = MarketDataPipeline(pair=args.pair.upper()).fetch_prediction_open(
                    prediction_date=prediction_date
                )
                display.console.print(
                    f"[bold green]✓ API open/spot fetched:[/bold green] {open_price:.4f}"
                )
            result = PredictionPipeline(pair=args.pair.upper()).run(
                open_price=open_price, prediction_date=prediction_date
            )
            display.prediction_result(result)
        except Exception as e:
            display.console.print(f"[bold red]Error:[/bold red] {e}")
            traceback.print_exc()

    elif args.mode == "log":
        if not args.pair or not args.date:
            display.console.print("[bold red]--pair and --date are required[/bold red]")
            return
        if None in (args.high, args.low, args.close):
            display.console.print(
                "[bold red]--high, --low, and --close are required[/bold red]"
            )
            return
        try:
            result = LoggingPipeline(pair=args.pair.upper()).run(
                prediction_date=date.fromisoformat(args.date),
                high=args.high,
                low=args.low,
                close=args.close,
                volume=args.volume,
            )
            display.logging_result(result)
        except ValueError as e:
            display.console.print(f"[bold red]Error:[/bold red] {e}")
        except Exception as e:
            display.console.print(f"[bold red]Error:[/bold red] {e}")
            traceback.print_exc()

    elif args.mode == "sync":
        if not args.pair:
            display.console.print("[bold red]--pair is required[/bold red]")
            return
        try:
            path = MarketDataPipeline(pair=args.pair.upper()).sync_raw_data()
            display.console.print(
                f"[bold green]✓ Synced[/bold green] {args.pair.upper()} → {path}"
            )
        except Exception as e:
            display.console.print(f"[bold red]Error:[/bold red] {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
