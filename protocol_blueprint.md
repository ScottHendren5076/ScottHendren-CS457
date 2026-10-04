### 2.1 Message Transport & Serialization Format
- **Transport Protocol:** TCP
- **Serialization Format:** JSON
- **Framing Mechanism:** Newline-delimited (`\n`)
  - ***Framing Rule:*** Every JSON object is UTF-8 encoded and terminated by a newline character \n (0x0A). The receiver accumulates incoming bytes into a stream buffer until a \n is encountered, extracts the complete line, and deserializes the JSON object.
  - ***Wire Stream Example (Continuous Stream):***
  ```text
  {"msg_type":"CONNECT","player_id":"Player_1","payload":{},"timestamp":1727000000}\n{"msg_type":"MOVE","player_id":"Player_1","payload":{"row":0,"col":2},"timestamp":1727000005}\n
  ```

### 2.2 Message Schema Definitions

### Message Schema
| Field | Data Type | Required | Description|
| --- | --- | --- | --- |
| msg_type | String | Yes | Identifies the type of message being sent |
| player_id | String | Yes | Identifies the player who is sending the message. (e.g. "Player_1", "Player_2", "Server") |
| payload | Object | Yes | The specific data relating the the message type |
| timestamp | Integer | Yes | Shows when message was ceated |

#### Message Types:
1. `CONNECT` (Client -> Server): Request to join the game room.
2. `LOBBY_WAIT` (Server -> Client): Notification that server is waiting for Player 2.
3. `GAME_START` (Server -> Clients): Game initiated, assigns roles (e.g. Player X vs Player O).
4. `MOVE` (Client -> Server): Player action submits their move in row/column format(e.g., cell coordinates or answer choice).
5. `STATE_UPDATE` (Server -> Clients): Broadcast current game board / state and active player turn.
6. `ERROR` (Server -> Client): Invalid move or malformed packet error.
7. `DISCONNECT`  (Client -> Server): Client notifies serer of intentional departure / quit
8. `GAME_OVER` (Server -> Clients): Victory / Draw notification with final scores.

#### Example JSON Protocol Schema (CONNECT):
```json
{
  "msg_type": "CONNECT",
  "player_id": "Player_1",
  "payload": {},
  "timestamp": 1727000000
}
```
#### Example JSON Protocol Schema (LOBBY_WAIT):
```json
{
  "msg_type": "LOBBY_WAIT",
  "player_id": "Player_1",
  "payload": {
    "message": "Waiting for Player 2 to connect."
  },
  "timestamp": 1727000001
}
```
#### Example JSON Protocol Schema (GAME_START):
```json
{
  "msg_type": "GAME_START",
  "player_id": "Server",
  "payload": {
    "players": {
      "Player_1": "X",
      "Player_2": "O"
    },
    "starting_player": "Player_1"
  },
  "timestamp": 1727000002
}
```
#### Example JSON Protocol Schema (MOVE):
```json
{
  "msg_type": "MOVE",
  "player_id": "Player_1",
  "payload": {
      "row": 0,
      "col": 2
  },
  "timestamp": 1727000003
}
```
#### Example JSON Protocol Schema (STATE_UPDATE):
```json
{
  "msg_type": "STATE_UPDATE",
  "player_id": "Server",
  "payload": {
    "board": [["X", "", ""],["", "O", ""],["", "", ""]],
    "next_turn": "Player_1"
  },
  "timestamp": 1727000004
}
```
#### Example JSON Protocol Schema (ERROR, INVALID_MOVE):
```json
{
  "msg_type": "ERROR",
  "player_id": "Player_1",
  "payload": {
    "error_code": "INVALID_MOVE",
    "message": "The cell chosen is already used, choose another cell"
  },
  "timestamp": 1727000007
}
```
#### Example JSON Protocol Schema (ERROR, MALFORMED_PACKET):
```json
{
  "msg_type": "ERROR",
  "player_id": "Player_1",
  "payload": {
    "error_code": "MALFORMED_PACKET",
    "message": "Packet received is missing required information"
  },
  "timestamp": 1727000008
}
```
#### Example JSON Protocol Schema (DISCONNECT):
```json
{
  "msg_type": "DISCONNECT",
  "player_id": "Player_1",
  "payload": {
    "reason": "Forfeit"
  },
  "timestamp": 1727000000
}
```
#### Example JSON Protocol Schema (GAME_OVER, VICTORY):
```json
{
  "msg_type": "GAME_OVER",
  "player_id": "Server",
  "payload": {
    "result": "VICTORY",
    "winner": "Player_1",
    "final_board":[["X", "X", "X"], ["O", "O", ""], ["", "", ""]]
  },
  "timestamp": 1727000005
}
```
#### Example JSON Protocol Schema (GAME_OVER, DRAW):
```json
{
  "msg_type": "GAME_OVER",
  "player_id": "Server",
  "payload": {
    "result": "DRAW",
    "winner": "null",
    "final_board":[["X", "O", "X"], ["X", "O", "O"], ["O", "X", "X"]]
  },
  "timestamp": 1727000006
}
```

