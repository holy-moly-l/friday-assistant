"""Release local model processes when the owning desktop process exits."""
import ctypes
import os
import threading

def follow_parent(parent_pid):
    if os.name!='nt' or not parent_pid:return
    def watch(pid):
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_uint]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if handle:
            kernel.WaitForSingleObject(handle,0xFFFFFFFF)
            os._exit(0)
    # Windows venv's python.exe is a redirector: watch it as well as the application.
    for pid in {int(parent_pid),os.getppid()}:
        threading.Thread(target=watch,args=(pid,),daemon=True).start()
