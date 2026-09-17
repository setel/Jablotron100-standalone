"""Small command-line helpers for standalone configuration."""

from __future__ import annotations

import argparse

from .config import load_config, load_home_assistant_config, save_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m jablotron100")
    commands = parser.add_subparsers(dest="command", required=True)

    convert = commands.add_parser(
        "convert-ha", help="convert Home Assistant configuration to TOML"
    )
    convert.add_argument("source", help="path to core.config_entries")
    convert.add_argument("destination", help="output TOML path")
    convert.add_argument("--entry-id")

    check = commands.add_parser(
        "check-config", help="validate TOML and print a redacted summary"
    )
    check.add_argument("path")

    args = parser.parse_args()
    if args.command == "convert-ha":
        config = load_home_assistant_config(
            args.source, entry_id=args.entry_id
        )
        save_config(config, args.destination)
        print(f"Created {args.destination} without the authorisation code.")
        print("Set the JABLOTRON_CODE environment variable before running.")
    else:
        config = load_config(args.path)
        active = sum(
            device.device_type.value not in ("empty", "other")
            for device in config.devices
        )
        print(
            f"Configuration is valid: {config.number_of_devices} positions, "
            f"{active} installed devices, "
            f"{config.number_of_pg_outputs} PG outputs."
        )


if __name__ == "__main__":
    main()
