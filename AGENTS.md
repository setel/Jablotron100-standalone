# AGENTS.md

## Project scope

This repository contains a standalone Python library for communication with Jablotron 100 alarm systems.

Work only inside this repository:

`/home/emil/prj_jablotron100-standalone`

Do not modify files outside this repository unless explicitly requested.

Especially do not modify:

`/home/emil/prj_automat`

or any other project under `/home/emil`.

## Python environment

Use the Python virtual environment:

`/home/emil/python3env/bin/python`

When running Python scripts, tests, or tools, prefer the executables from this environment.

Examples:

`/home/emil/python3env/bin/python`

`/home/emil/python3env/bin/pip`

## Git

This directory is an independent Git repository.

Do not create commits, branches, tags, merges, rebases, or pushes unless explicitly requested.

Before making larger changes, inspect the current Git status.

Do not modify Git history.

Do not change remotes unless explicitly requested.

## Upstream project

This project is derived partly from an existing MIT-licensed Jablotron/Home Assistant project.

Some low-level communication and protocol files may remain based on the original project.

Keep upstream-derived code reasonably separated from new standalone-library code where practical.

Avoid unnecessary rewrites of upstream-derived communication code, because future fixes from the original project may need to be transferred into this project.

Preserve all required MIT license notices and original copyright notices.

## Architecture

Prefer a modular structure.

Low-level Jablotron communication, transport, protocol parsing, device handling, and high-level API should be separated into logical modules.

Do not put large amounts of application logic into one file.

The library should not depend on Home Assistant unless explicitly required.

The goal is a standalone Python library that can later be used by other projects, including `/home/emil/prj_automat`.

## Compatibility

Target Raspberry Pi 5 running Debian 13 / Python 3.

Avoid platform-specific dependencies unless necessary.

Communication with the Jablotron alarm currently uses the JA-100 Flexi USB/HID interface.

Do not change hardware communication assumptions without checking the existing implementation first.

## Code changes

Before modifying existing code:

1. Read the relevant implementation.
2. Understand how the existing protocol and communication layer works.
3. Prefer small, focused changes.
4. Preserve existing working behavior unless the task explicitly requires changing it.
5. Avoid broad refactoring unrelated to the requested task.

When adding functionality, reuse existing abstractions where reasonable instead of duplicating logic.

## Testing

Whenever practical, add or update tests for new functionality.

Do not require physical Jablotron hardware for all automated tests.

Separate protocol parsing and data processing from physical HID communication so they can be tested independently.

When hardware access is required, clearly distinguish hardware/integration tests from unit tests.

## Safety

Do not send commands to the physical Jablotron alarm system unless explicitly requested.

Reading data is preferable during development and testing.

Potentially disruptive commands such as arming, disarming, changing configuration, activating outputs, or modifying alarm settings must not be executed without explicit instruction.

## Documentation

Document public classes, methods, and important protocol behavior.

Keep README and usage examples consistent with the actual public API.

When behavior is uncertain or reverse-engineered, describe that uncertainty rather than presenting assumptions as confirmed facts.
