"""Small command-line helpers for standalone configuration."""

from __future__ import annotations

import argparse

from .config import (
    create_config_from_flink,
    load_config,
    load_flink_csv,
    load_home_assistant_config,
    merge_flink_devices,
    save_config,
)


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

    merge = commands.add_parser(
        "merge-flink",
        help="add F-Link names and models to an existing TOML config",
    )
    merge.add_argument("config")
    merge.add_argument("csv")
    merge.add_argument("destination")
    merge.add_argument("--include-serial-numbers", action="store_true")

    import_flink = commands.add_parser(
        "import-flink",
        help="create a starter TOML config from an F-Link CSV export",
    )
    import_flink.add_argument("csv")
    import_flink.add_argument("destination")
    import_flink.add_argument("--number-of-devices", type=int)
    import_flink.add_argument("--number-of-pg-outputs", type=int, default=0)

    args = parser.parse_args()
    if args.command == "convert-ha":
        config = load_home_assistant_config(
            args.source, entry_id=args.entry_id
        )
        save_config(config, args.destination)
        print(f"Created {args.destination} without the authorisation code.")
        print("Set the JABLOTRON_CODE environment variable before running.")
    elif args.command == "check-config":
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
    elif args.command == "merge-flink":
        config = merge_flink_devices(
            load_config(args.config),
            load_flink_csv(args.csv),
            include_serial_numbers=args.include_serial_numbers,
        )
        save_config(config, args.destination)
        named = sum(bool(device.name) for device in config.devices)
        print(f"Created {args.destination} with {named} named devices.")
    else:
        config = create_config_from_flink(
            load_flink_csv(args.csv),
            number_of_devices=args.number_of_devices,
            number_of_pg_outputs=args.number_of_pg_outputs,
        )
        save_config(config, args.destination)
        custom = sum(
            device.device_type.value == "custom" for device in config.devices
        )
        print(f"Created {args.destination}.")
        if custom:
            print(
                f"Review the type of {custom} custom devices in the TOML file."
            )


if __name__ == "__main__":
    main()
