# ***********************************************************
# ******* WARNING: AUTOGENERATED! ALL EDITS WILL BE LOST ******
# *************************************************************
import select
import socket
import sys
from typing import Awaitable, Callable, ContextManager, Iterator, Optional, Tuple, TYPE_CHECKING, Union

from .._abc import Clock
from .._typing import _HasFileno
from .._core._entry_queue import TrioToken
from .. import _core
from ._run import GLOBAL_RUN_CONTEXT, _NO_SEND, _RunStatistics, Task
from ._ki import LOCALS_KEY_KI_PROTECTION_ENABLED
from ._instrumentation import Instrument

if TYPE_CHECKING and sys.platform == "win32":
    from ._io_windows import CompletionKeyEventInfo

# fmt: off


assert not TYPE_CHECKING or sys.platform == 'linux'


async def wait_readable(fd: Union[int, _HasFileno]) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_readable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


async def wait_writable(fd: Union[int, _HasFileno]) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return await GLOBAL_RUN_CONTEXT.runner.io_manager.wait_writable(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


def notify_closing(fd: Union[int, _HasFileno]) ->None:
    locals()[LOCALS_KEY_KI_PROTECTION_ENABLED] = True
    try:
        return GLOBAL_RUN_CONTEXT.runner.io_manager.notify_closing(fd)
    except AttributeError:
        raise RuntimeError("must be called from async context")


# fmt: on
