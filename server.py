#!/usr/bin/env python3
"""Tic-Tac-Toe game server (CS 457 Sprint 3).

Single-threaded, event-driven server built on ``selectors`` (Sprint 2 design).
Messages are newline-delimited UTF-8 JSON objects (Sprint 1 protocol).
The server owns the master board, turn order and scores; clients only render.

Usage:
    python3 server.py -h
    python3 server.py -p 8080
"""

import argparse
import json
import selectors
import socket
import sys
import time

MAX_BUFFER = 64 * 1024          # drop clients that send an unterminated flood
PLAYERS = ("Player_1", "Player_2")
SYMBOLS = {"Player_1": "X", "Player_2": "O"}

# FSM states (see fsm_specification.md)
INIT = "INIT"
WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
LOBBY_WAIT = "LOBBY_WAIT"
GAME_START = "GAME_START"
PLAYER_TURN = "PLAYER_TURN"
EVALUATE_MOVE = "EVALUATE_MOVE"
CHECK_WIN_DRAW = "CHECK_WIN_DRAW"
STATE_UPDATE = "STATE_UPDATE"
ERROR = "ERROR"
GAME_OVER = "GAME_OVER"
CLEANUP = "CLEANUP"
END = "END"

WIN_LINES = (
    [[(r, c) for c in range(3)] for r in range(3)]            # rows
    + [[(r, c) for r in range(3)] for c in range(3)]          # columns
    + [[(i, i) for i in range(3)], [(i, 2 - i) for i in range(3)]]  # diagonals
)


def log(text):
    """Timestamped console log."""
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def make_message(msg_type, player_id, payload):
    """Build a protocol message dict."""
    return {
        "msg_type": msg_type,
        "player_id": player_id,
        "payload": payload,
        "timestamp": int(time.time()),
    }


class ClientConn:
    """Per-connection state: socket, receive buffer, outgoing buffer."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.inbuf = b""
        self.outbuf = b""
        self.player_id = None      # assigned on CONNECT
        self.closing = False       # close once outbuf is flushed


class GameServer:
    def __init__(self, port):
        self.port = port
        self.sel = selectors.DefaultSelector()
        self.clients = {}                         # socket -> ClientConn
        self.slots = {p: None for p in PLAYERS}   # player_id -> ClientConn
        self.state = INIT
        self.board = self.empty_board()
        self.turn = PLAYERS[0]
        self.scores = self.empty_scores()
        self.listener = None
        self.running = True

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def empty_board():
        return [["" for _ in range(3)] for _ in range(3)]

    @staticmethod
    def empty_scores():
        return {p: {"wins": 0, "draws": 0, "losses": 0} for p in PLAYERS}

    def set_state(self, new_state):
        if new_state != self.state:
            log(f"FSM: {self.state} -> {new_state}")
            self.state = new_state

    def connected_players(self):
        return [p for p in PLAYERS if self.slots[p] is not None]

    def winner_of(self):
        """Return the winning symbol ('X'/'O') or None."""
        for line in WIN_LINES:
            cells = [self.board[r][c] for r, c in line]
            if cells[0] and cells[0] == cells[1] == cells[2]:
                return cells[0]
        return None

    def board_full(self):
        return all(cell for row in self.board for cell in row)

    # ------------------------------------------------------------------ #
    # Outgoing data (buffered; flushed when the socket is writable)
    # ------------------------------------------------------------------ #
    def send(self, conn, msg_type, player_id, payload):
        data = (json.dumps(make_message(msg_type, player_id, payload))
                + "\n").encode("utf-8")
        conn.outbuf += data
        self.update_interest(conn)

    def broadcast(self, msg_type, payload):
        for pid in self.connected_players():
            self.send(self.slots[pid], msg_type, "Server", payload)

    def update_interest(self, conn):
        events = selectors.EVENT_READ
        if conn.outbuf:
            events |= selectors.EVENT_WRITE
        try:
            self.sel.modify(conn.sock, events, data=conn)
        except (KeyError, ValueError):
            pass  # already unregistered

    def send_error(self, conn, code, message):
        self.send(conn, "ERROR", conn.player_id or "Unassigned",
                  {"error_code": code, "message": message})

    def on_writable(self, conn):
        try:
            sent = conn.sock.send(conn.outbuf)
            conn.outbuf = conn.outbuf[sent:]
        except BlockingIOError:
            return
        except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError) as exc:
            log(f"Write error from {conn.addr}: {exc!r}")
            self.remove_client(conn, "connection error")
            return
        if not conn.outbuf:
            if conn.closing:
                self.remove_client(conn, "closed after flush")
            else:
                self.update_interest(conn)

    # ------------------------------------------------------------------ #
    # Incoming data
    # ------------------------------------------------------------------ #
    def on_readable(self, conn):
        try:
            data = conn.sock.recv(4096)
        except BlockingIOError:
            return
        except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError) as exc:
            log(f"Read error from {conn.addr}: {exc!r}")
            self.remove_client(conn, "connection error")
            return
        if not data:  # TCP EOF -> treat as forfeit / DISCONNECT
            log(f"TCP EOF from {conn.player_id or conn.addr}")
            self.remove_client(conn, "tcp disconnect")
            return

        conn.inbuf += data
        if len(conn.inbuf) > MAX_BUFFER and b"\n" not in conn.inbuf:
            self.send_error(conn, "MALFORMED_PACKET", "Message too large")
            conn.closing = True
            return

        # Extract every complete newline-terminated message.
        while b"\n" in conn.inbuf and conn.sock in self.clients:
            line, conn.inbuf = conn.inbuf.split(b"\n", 1)
            if line.strip():
                self.handle_line(conn, line)

    def handle_line(self, conn, line):
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(conn, "MALFORMED_PACKET", "Packet is not valid JSON")
            return
        if (not isinstance(msg, dict)
                or not isinstance(msg.get("msg_type"), str)
                or not isinstance(msg.get("player_id"), str)
                or not isinstance(msg.get("payload"), dict)
                or not isinstance(msg.get("timestamp"), int)):
            self.send_error(conn, "MALFORMED_PACKET",
                            "Packet received is missing required information")
            return

        mtype = msg["msg_type"]
        if mtype == "CONNECT":
            self.handle_connect(conn)
        elif mtype == "MOVE":
            self.handle_move(conn, msg)
        elif mtype == "DISCONNECT":
            reason = msg["payload"].get("reason", "Quit")
            log(f"DISCONNECT from {conn.player_id}: {reason}")
            self.remove_client(conn, f"disconnect ({reason})")
        else:
            self.send_error(conn, "MALFORMED_PACKET",
                            f"Unexpected message type '{mtype}'")

    # ------------------------------------------------------------------ #
    # Message handlers
    # ------------------------------------------------------------------ #
    def handle_connect(self, conn):
        if conn.player_id is not None:
            self.send_error(conn, "ALREADY_CONNECTED", "You have already joined")
            return
        free = [p for p in PLAYERS if self.slots[p] is None]
        if not free:
            self.send_error(conn, "SERVER_FULL", "Game room is full")
            conn.closing = True
            return

        conn.player_id = free[0]
        self.slots[conn.player_id] = conn
        self.scores = self.empty_scores()   # new opponent -> new session
        log(f"{conn.player_id} joined from {conn.addr}")

        if len(self.connected_players()) < 2:
            self.set_state(LOBBY_WAIT)
            self.send(conn, "LOBBY_WAIT", conn.player_id,
                      {"message": "Waiting for Player 2 to connect."})
            self.set_state(WAITING_FOR_PLAYERS)
        else:
            self.start_game()

    def start_game(self):
        self.set_state(GAME_START)
        self.board = self.empty_board()
        self.turn = PLAYERS[0]
        for pid in PLAYERS:
            self.send(self.slots[pid], "GAME_START", "Server", {
                "players": dict(SYMBOLS),
                "starting_player": self.turn,
                "assigned_id": pid,           # tells each client who it is
                "scores": self.scores,
            })
        self.set_state(PLAYER_TURN)
        self.broadcast("STATE_UPDATE", {"board": self.board,
                                        "next_turn": self.turn})

    def handle_move(self, conn, msg):
        if conn.player_id is None:
            self.send_error(conn, "NOT_CONNECTED", "Send CONNECT first")
            return
        if self.state != PLAYER_TURN:
            self.send_error(conn, "NO_GAME_IN_PROGRESS",
                            "The game has not started yet")
            return

        self.set_state(EVALUATE_MOVE)
        if conn.player_id != self.turn:
            self.reject(conn, "NOT_YOUR_TURN", "It is not your turn")
            return
        row, col = msg["payload"].get("row"), msg["payload"].get("col")
        # bool is a subclass of int, so exclude it explicitly.
        if (not all(isinstance(v, int) and not isinstance(v, bool)
                    for v in (row, col))
                or not (0 <= row <= 2 and 0 <= col <= 2)):
            self.reject(conn, "INVALID_MOVE",
                        "Coordinates must be integers from 0 to 2")
            return
        if self.board[row][col]:
            self.reject(conn, "INVALID_MOVE",
                        "The cell chosen is already used, choose another cell")
            return

        # Valid move: apply it, then check for win / draw.
        self.board[row][col] = SYMBOLS[conn.player_id]
        log(f"{conn.player_id} ({SYMBOLS[conn.player_id]}) played ({row},{col})")
        self.set_state(CHECK_WIN_DRAW)
        if self.winner_of():
            self.finish_game("VICTORY", conn.player_id)
        elif self.board_full():
            self.finish_game("DRAW", None)
        else:
            self.set_state(STATE_UPDATE)
            self.turn = PLAYERS[1] if self.turn == PLAYERS[0] else PLAYERS[0]
            self.broadcast("STATE_UPDATE", {"board": self.board,
                                            "next_turn": self.turn})
            self.set_state(PLAYER_TURN)

    def reject(self, conn, code, message):
        """Invalid move: ERROR to sender only, board and turn unchanged."""
        self.set_state(ERROR)
        self.send_error(conn, code, message)
        self.set_state(PLAYER_TURN)

    # ------------------------------------------------------------------ #
    # Game end / cleanup
    # ------------------------------------------------------------------ #
    def finish_game(self, result, winner, reason=None):
        self.set_state(GAME_OVER)
        if result == "VICTORY":
            loser = PLAYERS[1] if winner == PLAYERS[0] else PLAYERS[0]
            self.scores[winner]["wins"] += 1
            self.scores[loser]["losses"] += 1
        else:
            for pid in PLAYERS:
                self.scores[pid]["draws"] += 1
        payload = {
            "result": result,
            "winner": winner if winner else "null",
            "final_board": self.board,
            "scores": self.scores,
        }
        if reason:
            payload["reason"] = reason
        log(f"GAME_OVER: {result} winner={winner} reason={reason}")
        self.broadcast("GAME_OVER", payload)
        self.cleanup()

    def cleanup(self):
        """CLEANUP state: reset the round, then restart or wait for players."""
        self.set_state(CLEANUP)
        self.board = self.empty_board()
        self.turn = PLAYERS[0]
        if len(self.connected_players()) == 2:
            self.start_game()
        else:
            self.set_state(WAITING_FOR_PLAYERS)
            for pid in self.connected_players():
                self.send(self.slots[pid], "LOBBY_WAIT", pid, {
                    "message": "Opponent left. Waiting for a new player."})

    def remove_client(self, conn, reason):
        """Unregister and close a socket; forfeit the game if one is running."""
        if conn.sock not in self.clients:
            return
        log(f"Closing connection {conn.player_id or conn.addr}: {reason}")
        del self.clients[conn.sock]
        try:
            self.sel.unregister(conn.sock)
        except (KeyError, ValueError):
            pass
        try:
            conn.sock.close()
        except OSError:
            pass

        pid = conn.player_id
        if pid is None or self.slots.get(pid) is not conn:
            return
        self.slots[pid] = None
        remaining = self.connected_players()
        if self.state == PLAYER_TURN and remaining:
            # Mid-game departure counts as a forfeit; opponent wins.
            self.finish_game("VICTORY", remaining[0], reason="FORFEIT")
        elif self.state not in (END, INIT):
            self.cleanup()

    # ------------------------------------------------------------------ #
    # Event loop
    # ------------------------------------------------------------------ #
    def accept(self):
        try:
            sock, addr = self.listener.accept()
        except (BlockingIOError, OSError):
            return
        sock.setblocking(False)
        conn = ClientConn(sock, addr)
        self.clients[sock] = conn
        self.sel.register(sock, selectors.EVENT_READ, data=conn)
        log(f"Accepted connection from {addr}")

    def run(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.listener.bind(("0.0.0.0", self.port))
            self.listener.listen()
        except OSError as exc:
            print(f"[ERROR] Cannot listen on port {self.port}: {exc}")
            return 1
        self.listener.setblocking(False)
        self.sel.register(self.listener, selectors.EVENT_READ, data=None)
        self.set_state(WAITING_FOR_PLAYERS)
        log(f"Server listening on 0.0.0.0:{self.port}")

        try:
            while self.running:
                for key, mask in self.sel.select(timeout=1.0):
                    if key.data is None:
                        self.accept()
                        continue
                    conn = key.data
                    if conn.sock not in self.clients:
                        continue            # removed earlier this iteration
                    if mask & selectors.EVENT_READ:
                        self.on_readable(conn)
                    if mask & selectors.EVENT_WRITE and conn.sock in self.clients:
                        self.on_writable(conn)
        except KeyboardInterrupt:
            log("Shutdown requested")
        finally:
            self.set_state(END)
            for conn in list(self.clients.values()):
                try:
                    conn.sock.close()
                except OSError:
                    pass
            self.listener.close()
            self.sel.close()
        return 0


def port_number(value):
    """argparse type: validate port range 1024-65535."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid integer")
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def main():
    parser = argparse.ArgumentParser(
        description="Tic-Tac-Toe game server (listens on 0.0.0.0).")
    parser.add_argument("-p", "--port", type=port_number, required=True,
                        help="listening port (1024-65535)")
    args = parser.parse_args()
    sys.exit(GameServer(args.port).run())


if __name__ == "__main__":
    main()
