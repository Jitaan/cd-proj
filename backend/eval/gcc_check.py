# eval/gcc_check.py
import os, subprocess, tempfile

def have_gcc():
    try:
        subprocess.run(["gcc", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

def gcc_run(c_path, inputs):
    # compile and run
    exe = c_path + ".exe"
    r = subprocess.run(["gcc", "-O0", "-fwrapv", "-std=c99", "-w", c_path, "-o", exe],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return ("", r.returncode)
    inp = "\n".join(str(x) for x in inputs) + "\n"
    r2 = subprocess.run([exe], input=inp, capture_output=True, text=True, timeout=5)
    try:
        os.remove(exe)
    except Exception:
        pass
    return (r2.stdout, r2.returncode)
