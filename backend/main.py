# main.py - thin CLI wrapper over service.py
import argparse
import sys

import service

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--passes", choices=["none", "all", "ai", "custom"], default="ai")
    ap.add_argument("--pass-list", default="")
    ap.add_argument("--lang", choices=["mini","c"], default="mini")
    ap.add_argument("--benchmark", metavar="DIR")
    args = ap.parse_args()

    if args.benchmark:
        import os
        for fn in sorted(os.listdir(args.benchmark)):
            if not fn.endswith(".c"):
                continue
            src = open(os.path.join(args.benchmark, fn)).read()
            print("==", fn)
            for mode in ("none", "ai", "all"):
                r = service.run_pipeline(src, mode=mode)
                m = r["metrics"]
                print("  %-4s passes=%d static=%d dynamic=%d" % (
                    mode, len(r["passes_run"]), m["static_after"], m["dynamic_after"]))
        return

    if not args.file:
        ap.error("file required")
    src = open(args.file).read()
    passes = [p for p in args.pass_list.split(",") if p] if args.pass_list else None
    mode = args.passes if args.passes != "custom" else "custom"
    r = service.run_pipeline(src, mode=mode, passes=passes, lang=args.lang)
    if r["error"]:
        e = r["error"]
        print("ERROR stage=%s line=%s: %s" % (e["stage"], e["line"], e["msg"]))
        sys.exit(1)
    print("Original TAC:")
    print("\n".join(r["tac_before"]))
    print()
    print("Optimised TAC:")
    print("\n".join(r["tac_after"]))
    print()
    m = r["metrics"]
    print("Static: %d -> %d" % (m["static_before"], m["static_after"]))
    print("Dynamic: %d -> %d" % (m["dynamic_before"], m["dynamic_after"]))
    print("Output match:", r["match"])
    if not r["match"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
