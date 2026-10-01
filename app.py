"""Kingshot Bot control panel.

    python app.py            # desktop window (pywebview)
    python app.py --browser  # default browser instead

Closing the panel stops every bot it started.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser


def run_panel(use_browser: bool) -> None:
    from gui.server import make_server, manager

    httpd = make_server()
    url = f"http://127.0.0.1:{httpd.server_port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        if not use_browser:
            try:
                import webview
            except ImportError:
                print("pywebview is not installed (pip install pywebview); opening in the browser.")
            else:
                webview.create_window("Kingshot Bot", url, width=1200, height=860,
                                      min_size=(820, 600))
                webview.start()
                return
        print(f"Panel at {url}  (Ctrl+C to quit)")
        webbrowser.open(url)
        while True:  # sleep loop instead of Event.wait so Ctrl+C works on Windows
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_all()
        httpd.shutdown()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--bot":
        # Packaged builds have no separate python/main.py: the panel re-runs itself as the bot.
        del sys.argv[1]
        import main as bot_main
        bot_main.main()
        return
    run_panel(use_browser="--browser" in sys.argv)


if __name__ == "__main__":
    main()
