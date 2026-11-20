import ctypes
import os
import signal
import sys

PR_SET_PDEATHSIG = 1


def _set_pdeathsig():
    parent = os.getppid()
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    if os.getppid() != parent:
        os._exit(0)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("child_wrap.py: usage: child_wrap.py <cmd> [args...]\n")
        return 2
    _set_pdeathsig()
    try:
        os.execvp(sys.argv[1], sys.argv[1:])
    except OSError as exc:
        sys.stderr.write(f"child_wrap.py: exec {sys.argv[1]} failed: {exc}\n")
        return 127
    return 0


if __name__ == "__main__":
    sys.exit(main())
