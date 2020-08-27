from functools import wraps, partial

from .. import _core
from ..abc import Clock, Instrument


# Use:
#
#    @trio_test
#    async def test_whatever():
#        await ...
#
# Also: if a pytest fixture is passed in that subclasses the Clock abc, then
# that clock is passed to trio.run().
def trio_test(fn=None, *, run=_core.run):
    def decorator(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            __tracebackhide__ = True
            clocks = [c for c in kwargs.values() if isinstance(c, Clock)]
            if not clocks:
                clock = None
            elif len(clocks) == 1:
                clock = clocks[0]
            else:
                raise ValueError("too many clocks spoil the broth!")
            instruments = [i for i in kwargs.values() if isinstance(i, Instrument)]
            return run(partial(fn, **kwargs), clock=clock, instruments=instruments)

        return wrapper

    if fn is None:
        return decorator

    return decorator(fn)
