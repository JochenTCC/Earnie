"""CLI: Mode A fixture mock REST, or Binding P5d contract push harness."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m house_sim",
        description=(
            "HouseSim bench: Mode A golden fixtures (mock HA REST) or "
            "Binding P5d contract mode (push telemetry to Earnie)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("fixture", "contract"),
        default="fixture",
        help="fixture = Mode A goldens + mock REST; contract = activated-key push harness",
    )
    parser.add_argument(
        "--fixture",
        default="evcc_en",
        help="Archetype name under house_sim/fixtures/ (fixture mode; default: evcc_en)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument(
        "--token",
        default=None,
        help="Mock HA token (fixture) or Earnie push token (contract)",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=0,
        help="If >0 (fixture mode), run this many closed-loop ticks then exit.",
    )
    parser.add_argument(
        "--dt-h",
        type=float,
        default=0.25,
        help="Tick duration in hours (fixture mode; default: 0.25 = 15 min).",
    )
    parser.add_argument(
        "--earnie-url",
        default="http://127.0.0.1:8541",
        help="Earnie base URL for contract push (default: http://127.0.0.1:8541)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Contract push interval seconds (default: 10).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="If >0 (contract mode), run this many push cycles then exit.",
    )
    return parser


def _run_fixture(args: argparse.Namespace) -> int:
    from house_sim.archetype import load_archetype
    from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest
    from house_sim.stepper import run_ticks

    token = args.token or DEFAULT_BENCH_TOKEN
    package = load_archetype(args.fixture)
    store = package.build_store()

    if args.ticks > 0:
        state = run_ticks(package, store, n_ticks=args.ticks, dt_h=args.dt_h)
        print(json.dumps(state.as_dict(), indent=2))
        return 0

    server, base_url = start_mock_rest(
        store, host=args.host, port=args.port, token=token
    )
    print("house_sim mock HA listening (Mode A fixture)")
    print(f"  base_url: {base_url}")
    print(f"  token:    {token}")
    print(f"  fixture:  {package.root}")
    print("  Merge golden IDs into house_profiles plant.ehal_bindings")
    print("  (EV keys → first EV consumer when present); keep ehal.ha.sign in config.")
    print("  plant.ehal_bindings (golden field→entity_id):")
    print(json.dumps(package.ehal_entities, indent=2))
    if package.ehal_sign:
        print("  ehal.ha.sign:")
        print(json.dumps(package.ehal_sign, indent=2))
    print("Ctrl+C to stop.")

    def _stop(_signum=None, _frame=None) -> None:
        stop_mock_rest()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        while True:
            time.sleep(1.0)
    finally:
        stop_mock_rest()
        del server
    return 0


def _run_contract(args: argparse.Namespace) -> int:
    import os

    from house_sim.contract import build_contract, minimal_contract_docs
    from house_sim.push_harness import PushClient, PushLoop, push_cycle

    from integrations.ehal_request_http import push_token as env_push_token

    token = args.token or env_push_token()
    if not token:
        print(
            "contract mode needs --token or EARNIE_PUSH_TOKEN",
            file=sys.stderr,
        )
        return 2

    house, components = minimal_contract_docs()
    bundle = build_contract(house, components)
    client = PushClient(args.earnie_url, token=token)

    print("house_sim contract mode (Binding P5d)")
    print(f"  earnie_url: {args.earnie_url}")
    print(f"  interval:   {args.interval}s")
    print(f"  reads:      {[s.ehal_id for s in bundle.read_signals]}")
    print(f"  writes:     {[s.ehal_id for s in bundle.write_signals]}")
    print("  entity map (not stored in Earnie bindings):")
    print(json.dumps(bundle.entity_by_ehal, indent=2))

    if args.cycles > 0:
        for i in range(args.cycles):
            report = push_cycle(bundle, client)
            print(f"cycle {i + 1}: {json.dumps(report)}")
        return 0

    loop = PushLoop(bundle, client, interval_s=args.interval)
    loop.start()
    print("Ctrl+C to stop.")

    def _stop(_signum=None, _frame=None) -> None:
        loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        while True:
            time.sleep(1.0)
    finally:
        loop.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.mode == "contract":
        return _run_contract(args)
    return _run_fixture(args)


if __name__ == "__main__":
    raise SystemExit(main())
