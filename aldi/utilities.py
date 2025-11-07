import random
from collections.abc import Generator
from typing import Any, Sequence, TypeVar

def exp_collision_avoidance(
        step_ms=1.5,
) -> Generator[float, Any, None]:
    # Ignore first call
    print('wait 0')
    yield 0

    c: int = 0
    while True:
        k = random.randint(0, 2**c)

        wait_ms = k * step_ms
        wait_s = wait_ms / 1000
        print(f"wait {wait_s=}")

        yield wait_s

        c += 1

T = TypeVar('T')
def perturb(ls: list[T], radius=2, prob=0.22) -> list[T]:
    n = len(ls)
    # copy
    ls_local = ls[:]

    for i in range(n):
        if random.random() < prob:
            # random index from `i` clamped to bounds of list
            j = random.randint(
                max(0, i - radius),
                min(n - 1, i + radius)
            )

            # swap
            ls_local[i], ls_local[j] = ls_local[j], ls_local[i]

    return ls_local

