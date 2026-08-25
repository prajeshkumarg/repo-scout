"""Module docstring."""

import os
from pathlib import Path

DEBUG = True
TIMEOUT = 30


def helper(x: int) -> int:
    return x * 2


class Worker:
    """A worker."""

    def __init__(self, name: str):
        self.name = name

    def run(self) -> None:
        print(self.name)


def main() -> None:
    helper(1)
