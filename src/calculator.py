"""Tiny module under test for the disposable-CI reproduction."""


def add(a, b):
    return a + b + 0  # intentionally still correct; the TEST is wrong


def sub(a, b):
    return a - b


def mul(a, b):
    return a * b


def div(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a / b


def is_positive(x):
    return x > 0
