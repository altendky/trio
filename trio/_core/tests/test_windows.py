from io import BufferedWriter
import os
import tempfile
from contextlib import contextmanager
import sys
from typing import Iterator, Tuple

import pytest

on_windows = os.name == "nt"
# Mark all the tests in this file as being windows-only
pytestmark = pytest.mark.skipif(not on_windows, reason="windows only")

from .tutil import slow, gc_collect_harder
from ... import _core, sleep, move_on_after
from ...testing import wait_all_tasks_blocked

if on_windows:
    from .._windows_cffi import (
        ffi,
        kernel32,
        INVALID_HANDLE_VALUE,
        raise_winerror,
        FileFlags,
    )


# mypy recognizes this.  an assert would break the pytest skipif
if sys.platform == "win32":
    # The undocumented API that this is testing should be changed to stop using
    # UnboundedQueue (or just removed until we have time to redo it), but until
    # then we filter out the warning.
    @pytest.mark.filterwarnings("ignore:.*UnboundedQueue:trio.TrioDeprecationWarning")
    async def test_completion_key_listen() -> None:
        async def post(key):
            iocp = ffi.cast("HANDLE", _core.current_iocp())
            for i in range(10):
                print("post", i)
                if i % 3 == 0:
                    await _core.checkpoint()
                success = kernel32.PostQueuedCompletionStatus(iocp, i, key, ffi.NULL)
                assert success

        with _core.monitor_completion_key() as (key, queue):
            async with _core.open_nursery() as nursery:
                nursery.start_soon(post, key)
                i = 0
                print("loop")
                async for batch in queue:  # pragma: no branch
                    print("got some", batch)
                    for info in batch:
                        assert info.lpOverlapped == 0
                        assert info.dwNumberOfBytesTransferred == i
                        i += 1
                    if i == 10:
                        break
                print("end loop")

    async def test_readinto_overlapped() -> None:
        data = b"1" * 1024 + b"2" * 1024 + b"3" * 1024 + b"4" * 1024
        buffer = bytearray(len(data))

        with tempfile.TemporaryDirectory() as tdir:
            tfile = os.path.join(tdir, "numbers.txt")
            with open(tfile, "wb") as fp:
                fp.write(data)
                fp.flush()

            rawname = tfile.encode("utf-16le") + b"\0\0"
            rawname_buf = ffi.from_buffer(rawname)
            handle = kernel32.CreateFileW(
                ffi.cast("LPCWSTR", rawname_buf),
                FileFlags.GENERIC_READ,
                FileFlags.FILE_SHARE_READ,
                ffi.NULL,  # no security attributes
                FileFlags.OPEN_EXISTING,
                FileFlags.FILE_FLAG_OVERLAPPED,
                ffi.NULL,  # no template file
            )
            if handle == INVALID_HANDLE_VALUE:  # pragma: no cover
                raise_winerror()

            try:
                with memoryview(buffer) as buffer_view:

                    async def read_region(start, end):
                        await _core.readinto_overlapped(
                            handle, buffer_view[start:end], start
                        )

                    _core.register_with_iocp(handle)
                    async with _core.open_nursery() as nursery:
                        for start in range(0, 4096, 512):
                            nursery.start_soon(read_region, start, start + 512)

                    assert buffer == data

                    with pytest.raises(BufferError):
                        await _core.readinto_overlapped(handle, b"immutable")
            finally:
                kernel32.CloseHandle(handle)

    @contextmanager
    def pipe_with_overlapped_read() -> Iterator[Tuple[BufferedWriter, int]]:
        from asyncio.windows_utils import pipe
        import msvcrt

        read_handle, write_handle = pipe(overlapped=(True, False))
        try:
            write_fd = msvcrt.open_osfhandle(write_handle, 0)
            yield os.fdopen(write_fd, "wb", closefd=False), read_handle
        finally:
            kernel32.CloseHandle(ffi.cast("HANDLE", read_handle))
            kernel32.CloseHandle(ffi.cast("HANDLE", write_handle))

    def test_forgot_to_register_with_iocp() -> None:
        with pipe_with_overlapped_read() as (write_fp, read_handle):
            with write_fp:
                write_fp.write(b"test\n")

            left_run_yet = False

            async def main():
                target = bytearray(1)
                try:
                    async with _core.open_nursery() as nursery:
                        nursery.start_soon(
                            _core.readinto_overlapped, read_handle, target, name="xyz"
                        )
                        await wait_all_tasks_blocked()
                        nursery.cancel_scope.cancel()
                finally:
                    # Run loop is exited without unwinding running tasks, so
                    # we don't get here until the main() coroutine is GC'ed
                    assert left_run_yet

            with pytest.raises(_core.TrioInternalError) as exc_info:
                _core.run(main)
            left_run_yet = True
            assert "Failed to cancel overlapped I/O in xyz " in str(exc_info.value)
            assert "forget to call register_with_iocp()?" in str(exc_info.value)

            # Make sure the Nursery.__del__ assertion about dangling children
            # gets put with the correct test
            del exc_info
            gc_collect_harder()

    @slow
    async def test_too_late_to_cancel() -> None:
        import time

        with pipe_with_overlapped_read() as (write_fp, read_handle):
            _core.register_with_iocp(read_handle)
            target = bytearray(6)
            async with _core.open_nursery() as nursery:
                # Start an async read in the background
                nursery.start_soon(_core.readinto_overlapped, read_handle, target)
                await wait_all_tasks_blocked()

                # Synchronous write to the other end of the pipe
                with write_fp:
                    write_fp.write(b"test1\ntest2\n")

                # Note: not trio.sleep! We're making sure the OS level
                # ReadFile completes, before Trio has a chance to execute
                # another checkpoint and notice it completed.
                time.sleep(1)
                nursery.cancel_scope.cancel()
            assert target[:6] == b"test1\n"

            # Do another I/O to make sure we've actually processed the
            # fallback completion that was posted when CancelIoEx failed.
            assert await _core.readinto_overlapped(read_handle, target) == 6
            assert target[:6] == b"test2\n"

    def test_lsp_that_hooks_select_gives_good_error(monkeypatch) -> None:
        from .._windows_cffi import WSAIoctls, _handle
        from .. import _io_windows

        def patched_get_underlying(sock, *, which=WSAIoctls.SIO_BASE_HANDLE):
            if hasattr(sock, "fileno"):  # pragma: no branch
                sock = sock.fileno()
            if which == WSAIoctls.SIO_BSP_HANDLE_SELECT:
                return _handle(sock + 1)
            else:
                return _handle(sock)

        monkeypatch.setattr(
            _io_windows, "_get_underlying_socket", patched_get_underlying
        )
        with pytest.raises(
            RuntimeError, match="SIO_BASE_HANDLE and SIO_BSP_HANDLE_SELECT differ"
        ):
            _core.run(sleep, 0)

    def test_lsp_that_completely_hides_base_socket_gives_good_error(
        monkeypatch,
    ) -> None:
        # This tests behavior with an LSP that fails SIO_BASE_HANDLE and returns
        # self for SIO_BSP_HANDLE_SELECT (like Komodia), but also returns
        # self for SIO_BSP_HANDLE_POLL. No known LSP does this, but we want to
        # make sure we get an error rather than an infinite loop.

        from .._windows_cffi import WSAIoctls, _handle
        from .. import _io_windows

        def patched_get_underlying(sock, *, which=WSAIoctls.SIO_BASE_HANDLE):
            if hasattr(sock, "fileno"):  # pragma: no branch
                sock = sock.fileno()
            if which == WSAIoctls.SIO_BASE_HANDLE:
                raise OSError("nope")
            else:
                return _handle(sock)

        monkeypatch.setattr(
            _io_windows, "_get_underlying_socket", patched_get_underlying
        )
        with pytest.raises(
            RuntimeError,
            match="SIO_BASE_HANDLE failed and SIO_BSP_HANDLE_POLL didn't return a diff",
        ):
            _core.run(sleep, 0)
