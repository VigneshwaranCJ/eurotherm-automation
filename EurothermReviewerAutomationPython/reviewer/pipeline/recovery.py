"""Conservative recovery: never release a claim whose owner might be active."""
import os


def owner_active(pid):
    if pid == os.getpid():
        return True
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def recover(settings):
    from .batch import DATABASE
    from .state import ProcessingState
    restored, blocked = [], []
    state = ProcessingState(DATABASE)
    with state.connect() as db:
        rows = db.execute("SELECT id,owner FROM tasks WHERE state='Running'").fetchall()
    for key, owner in rows:
        if owner_active(owner) is False:
            state.finish(key, 'Stopped', dict(message='Dead owner confirmed; export checkpoints retained'))
            restored.append(key)
        else:
            blocked.append(key)
    for name in ('batch.lock', 'automation.lock'):
        path = settings.temp / name
        if path.is_file():
            owner = int(path.read_text().strip())
            if owner_active(owner) is False:
                path.unlink()
                restored.append(name)
            else:
                blocked.append(name)
    return dict(recovered=restored, blocked=blocked, importJournalsPreserved=True)
