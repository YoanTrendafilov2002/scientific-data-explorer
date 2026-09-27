"""Start a loopback-only explorer on an available port and open the browser."""
import sys
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ui_server import DiscoveryHandler


def main():
    with HTTPServer(('127.0.0.1', 0), DiscoveryHandler) as server:
        url = f'http://127.0.0.1:{server.server_port}/explorer'
        print(f'Scientific Data Explorer: {url}\nKeep this window open. Ctrl+C stops the app.', flush=True)
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
