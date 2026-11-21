import sys


def _run():
    if len(sys.argv) > 1 and sys.argv[1] in ("convert", "remesh", "-h", "--help"):
        from .cli import main
    else:
        from .app import main
    main()


# The guard matters: worker processes re-import this module and must not
# start a second window.
if __name__ == "__main__":
    _run()
