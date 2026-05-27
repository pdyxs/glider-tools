"""Shared utilities for glider-tools scripts."""

import os


def serve_loop(pipe_name: str, label: str, parser) -> None:
    """Generic named-pipe command server.

    Listens on ~/.{pipe_name} for line-oriented commands and dispatches them
    through the given argparse parser. Reopen the pipe each iteration so that
    a writer closing it sends EOF without killing the daemon.

    Args:
        pipe_name: Bare name, e.g. ``'glider-cmd'`` → expands to ``~/.glider-cmd``
        label:     Human-readable name shown in log output, e.g. ``'Glider'``
        parser:    A fully-built argparse.ArgumentParser whose subcommands have
                   ``.func`` defaults set (i.e. ``p.set_defaults(func=...)``).

    Example usage in a device script::

        if __name__ == "__main__":
            from common import serve_loop
            serve_loop("glider-cmd", "Glider", build_parser())
    """
    pipe_path = os.path.expanduser(f"~/.{pipe_name}")
    if not os.path.exists(pipe_path):
        os.mkfifo(pipe_path)
    print(f"{label} daemon listening on {pipe_path}  (Ctrl+C to stop)", flush=True)
    while True:
        try:
            # Reopen each iteration: a writer closing the pipe sends EOF,
            # which ends the inner for-loop cleanly without exiting the daemon.
            with open(pipe_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    print(f"< {line}", flush=True)
                    try:
                        cmd_args = parser.parse_args(line.split())
                        cmd_args.func(cmd_args)
                    except SystemExit as e:
                        print(f"  error: {e}", flush=True)
                    except Exception as e:
                        print(f"  error: {e}", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"pipe error: {e}", flush=True)
    print(f"{label} daemon stopped.", flush=True)
