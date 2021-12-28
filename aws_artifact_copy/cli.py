import argparse
import importlib

import trio_asyncio

from .services import SERVICES


def get_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=SERVICES)
    return parser.parse_known_args(argv)


def main(argv=None):
    args, remaining_argv = get_args(argv)
    module = importlib.import_module(f".services.{args.service}", __package__)
    trio_asyncio.run(module.main, remaining_argv)
