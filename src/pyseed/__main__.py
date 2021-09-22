# -*- coding: utf-8 -*-
"""
    __main__
    ~~~~~~~~~~~~~~

    Commands.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/8/31
"""
import argparse
import sys
from typing import List, Tuple, Any

from importlib_metadata import version, entry_points

import pyseed
from pyseed.log import configure_logger


def list_dependencies_and_versions() -> List[Tuple[str, str]]:
    deps = (
        "flask",
        "pymongo",
        "importlib_metadata",
        "inflection",
    )
    return [(dep, version(dep)) for dep in deps]


def dep_versions() -> str:
    return ", ".join(
        "{}: {}".format(*dependency) for dependency in list_dependencies_and_versions()
    )


def main() -> Any:
    argv = sys.argv[1:]
    registered_commands = entry_points(group="pyseed.registered_commands")
    parser = argparse.ArgumentParser(prog="pyseed")
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s version {} ({})".format(pyseed.__version__, dep_versions()),
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print debug information',
    )
    parser.add_argument(
        "command",
        choices=['gen', ],
    )
    parser.add_argument(
        "args",
        help=argparse.SUPPRESS,
        nargs=argparse.REMAINDER,
    )
    parsed_args = parser.parse_args(argv)
    # Setup logger
    configure_logger(stream_level='DEBUG' if parsed_args.verbose else 'INFO')
    # Execute command
    command = registered_commands[parsed_args.command].load()
    return command(parsed_args.args)


if __name__ == "__main__":
    sys.exit(main())
