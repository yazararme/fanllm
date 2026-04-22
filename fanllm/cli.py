from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

import fanllm
from fanllm.providers import REGISTRY, available_providers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fanllm",
        description="Fire one prompt at multiple LLMs in parallel.",
    )
    parser.add_argument("prompt", help="The prompt to send to each provider.")
    parser.add_argument(
        "--models",
        help="Comma-separated provider names to restrict to (e.g. openai,anthropic).",
    )
    parser.add_argument("--system", help="Optional system prompt.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Per-provider timeout in seconds (default: 90).",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit results as a JSON array instead of pretty-printing.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"fanllm {fanllm.__version__}",
    )
    return parser.parse_args()


def resolve_providers(models_arg: str | None, console: Console) -> list[str] | None:
    if models_arg is None:
        return None
    requested = [m.strip() for m in models_arg.split(",") if m.strip()]
    unknown = [m for m in requested if m not in REGISTRY]
    if unknown:
        console.print(
            f"[bold red]error:[/] unknown provider(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(REGISTRY))}."
        )
        sys.exit(1)
    runnable = [m for m in requested if m in available_providers()]
    if not runnable:
        console.print(
            "[bold red]error:[/] no API keys set for the requested provider(s). "
            "See .env.example for the expected environment variables."
        )
        sys.exit(1)
    return runnable


def render_pretty(results: list, console: Console, elapsed: float) -> None:
    for result in results:
        console.print(Rule(f"{result.provider} / {result.model or '?'}"))
        if result.error:
            console.print(f"[red]{result.error}[/red]")
        elif result.response:
            console.print(Markdown(result.response))
        footer = (
            f"latency {result.latency_ms}ms · "
            f"in: {result.input_tokens if result.input_tokens is not None else '?'} tokens · "
            f"out: {result.output_tokens if result.output_tokens is not None else '?'} tokens"
        )
        console.print(f"[dim]{footer}[/dim]")
        console.print()
    total = len(results)
    ok = sum(1 for r in results if r.error is None)
    failed = total - ok
    console.print(
        f"[bold]{total} providers · {ok} succeeded · {failed} failed · "
        f"{elapsed:.1f}s total[/bold]"
    )


def render_json(results: list) -> None:
    payload = [
        {
            "provider": r.provider,
            "model": r.model,
            "response": r.response,
            "error": r.error,
            "latency_ms": r.latency_ms,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
        }
        for r in results
    ]
    print(json.dumps(payload, indent=2))


def main() -> None:
    args = parse_args()
    console = Console()
    providers = resolve_providers(args.models, console)

    if providers is None and not available_providers():
        console.print(
            "[bold red]error:[/] no API keys set for any provider. "
            "See .env.example for the expected environment variables."
        )
        sys.exit(1)

    start = time.perf_counter()
    try:
        results = asyncio.run(
            fanllm.run(
                args.prompt,
                providers=providers,
                system_prompt=args.system,
                timeout=args.timeout,
            )
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(130)
    elapsed = time.perf_counter() - start

    if args.as_json:
        render_json(results)
    else:
        render_pretty(results, console, elapsed)

    any_ok = any(r.error is None for r in results)
    sys.exit(0 if any_ok else 1)


if __name__ == "__main__":
    main()
