#!/usr/bin/env python3
"""Tic-Tac-Toe console client (CS 457 Sprint 3).

Speaks the newline-delimited JSON protocol from Sprint 1. The server is the
source of truth; this client only renders what the server sends.

Usage:
    python3 client.py -h
    python3 client.py -i server.hendren.edu -p 8080
"""

import argparse
import json
import socket
import sys
import time


def port_number(value):
    """argparse type: validate port range 1024-65535."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid integer")
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def make_message(msg_type, player_id, payload):
    return {"msg_type": msg_type, "player_id": player_id,
            "payload": payload, "timestamp": int(time.time())}


class GameClient:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""
        self.pending = []          # decoded messages not yet consumed
        self.player_id = "Unassigned"
        self.symbols = {}
        self.board = [["" for _ in range(3)] for _ in range(3)]

    # ------------------------------------------------------------------ #
    # Networking
    # ------------------------------------------------------------------ #
    def send(self, msg_type, payload):
        data = json.dumps(make_message(msg_type, self.player_id, payload)) + "\n"
        self.sock.sendall(data.encode("utf-8"))

    def recv_message(self):
        """Block until one full newline-terminated message arrives.

        Returns the decoded dict, or None if the server closed the socket.
        """
        while not self.pending:
            while b"\n" not in self.buffer:
                data = self.sock.recv(4096)
                if not data:                      # TCP EOF
                    return None
                self.buffer += data
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                self.pending.append(json.loads(line.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                print("[WARN] Ignoring malformed packet from server")
        return self.pending.pop(0)

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def render_board(self, board):
        print("\n      0   1   2")
        for r in range(3):
            cells = " | ".join(board[r][c] or " " for c in range(3))
            print(f"  {r}   {cells}")
            if r < 2:
                print("     ---+---+---")
        print()

    def render_scores(self, scores):
        if not scores:
            return
        print("Scores:")
        for pid in ("Player_1", "Player_2"):
            s = scores.get(pid, {})
            tag = " (you)" if pid == self.player_id else ""
            print(f"  {pid} [{self.symbols.get(pid, '?')}]{tag}: "
                  f"{s.get('wins', 0)} W / {s.get('draws', 0)} D / "
                  f"{s.get('losses', 0)} L")

    # ------------------------------------------------------------------ #
    # Input
    # ------------------------------------------------------------------ #
    def prompt_move(self):
        """Ask for 'row col'. Returns (row, col) or None if the player quits."""
        while True:
            try:
                text = input("Your Turn - enter 'row col' (0-2), or 'q' to quit: ")
            except EOFError:
                return None
            text = text.strip().lower()
            if text in ("q", "quit"):
                return None
            parts = text.replace(",", " ").split()
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                row, col = int(parts[0]), int(parts[1])
                if 0 <= row <= 2 and 0 <= col <= 2:
                    return row, col
            print("Invalid input. Example: 1 2  (row 1, column 2)")

    # ------------------------------------------------------------------ #
    # Message handling
    # ------------------------------------------------------------------ #
    def play(self):
        """Main loop. Returns an exit code."""
        self.send("CONNECT", {})
        while True:
            msg = self.recv_message()
            if msg is None:
                print("\n[ERROR] Server closed the connection.")
                return 1
            mtype = msg.get("msg_type")
            payload = msg.get("payload", {})

            if mtype == "LOBBY_WAIT":
                self.player_id = msg.get("player_id", self.player_id)
                print(f"\n{payload.get('message', 'Waiting for Player 2...')}")
                print("Waiting for Player 2...")

            elif mtype == "GAME_START":
                self.symbols = payload.get("players", {})
                self.player_id = payload.get("assigned_id", self.player_id)
                print("\n=== GAME START ===")
                print(f"You are {self.player_id} playing "
                      f"'{self.symbols.get(self.player_id, '?')}'. "
                      f"{payload.get('starting_player')} goes first.")
                self.render_scores(payload.get("scores"))

            elif mtype == "STATE_UPDATE":
                self.board = payload.get("board", self.board)
                self.render_board(self.board)
                if payload.get("next_turn") == self.player_id:
                    move = self.prompt_move()
                    if move is None:
                        self.quit()
                        return 0
                    self.send("MOVE", {"row": move[0], "col": move[1]})
                else:
                    print("Waiting for opponent's move...")

            elif mtype == "ERROR":
                print(f"[SERVER ERROR] {payload.get('error_code')}: "
                      f"{payload.get('message')}")
                # An invalid move leaves it our turn: ask again.
                if payload.get("error_code") in ("INVALID_MOVE", "NOT_YOUR_TURN"):
                    move = self.prompt_move()
                    if move is None:
                        self.quit()
                        return 0
                    self.send("MOVE", {"row": move[0], "col": move[1]})

            elif mtype == "GAME_OVER":
                self.render_board(payload.get("final_board", self.board))
                result, winner = payload.get("result"), payload.get("winner")
                if result == "DRAW":
                    print("=== GAME OVER: It's a draw! ===")
                elif winner == self.player_id:
                    extra = (" (opponent forfeited)"
                             if payload.get("reason") == "FORFEIT" else "")
                    print(f"=== GAME OVER: You win!{extra} ===")
                else:
                    print("=== GAME OVER: You lose. ===")
                self.render_scores(payload.get("scores"))
                print("A new round will start automatically when ready.")

    def quit(self):
        """Tell the server we are leaving (counts as a forfeit mid-game)."""
        try:
            self.send("DISCONNECT", {"reason": "Quit"})
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Tic-Tac-Toe console client.")
    parser.add_argument("-i", "--hostname", required=True,
                        help="server DNS hostname (e.g. server.hendren.edu)")
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        help="server port (1024-65535)")
    args = parser.parse_args()

    # Resolve via DNS (no hardcoded IPs); fail gracefully if it cannot.
    try:
        server_ip = socket.gethostbyname(args.hostname)
    except socket.gaierror:
        print(f"[ERROR] Unable to resolve DNS hostname '{args.hostname}'.")
        print("Please check your Cisco router DNS configuration "
              "('ip dns server' / 'ip host') or verify domain spelling.")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((server_ip, args.port))
    except OSError as exc:
        print(f"[ERROR] Could not connect to {args.hostname} "
              f"({server_ip}):{args.port} - {exc.strerror or exc}")
        sys.exit(1)
    print(f"Connected to {args.hostname} ({server_ip}):{args.port}")

    client = GameClient(sock)
    code = 0
    try:
        code = client.play()
    except KeyboardInterrupt:
        print("\nLeaving game...")
        client.quit()
    except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError) as exc:
        print(f"\n[ERROR] Network error: {exc}")
        code = 1
    finally:
        sock.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
