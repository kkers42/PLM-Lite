"""Command-line interface for PLMLITE."""

import argparse
import sys

from .lifecycle import LifecycleManager, LifecycleState
from .parser import parse_nx_file


def main():
    parser = argparse.ArgumentParser(prog="plmlite")
    subparsers = parser.add_subparsers(dest="command")

    # show state
    show_parser = subparsers.add_parser("state", help="show lifecycle state")
    show_parser.add_argument("part_id")

    # set state
    set_parser = subparsers.add_parser("set", help="set lifecycle state")
    set_parser.add_argument("part_id")
    set_parser.add_argument("state", choices=[s.value for s in LifecycleState])

    # parse
    parse_parser = subparsers.add_parser("parse", help="parse NX file")
    parse_parser.add_argument("file")

    args = parser.parse_args()
    manager = LifecycleManager()

    if args.command == "state":
        state = manager.get_state(args.part_id)
        print(state.value if state else "unknown")
    elif args.command == "set":
        manager.set_state(args.part_id, LifecycleState(args.state))
        print(f"Set {args.part_id} to {args.state}")
    elif args.command == "parse":
        info = parse_nx_file(args.file)
        print(info)
    else:
        parser.print_help()
        sys.exit(1)
