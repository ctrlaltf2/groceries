import random
from collections.abc import Generator
from typing import Any

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