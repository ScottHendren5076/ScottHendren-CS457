## 3. Game Behavior & Server Concurrency Architecture (Sprint 2 Deliverable)

### 3.1 Server Concurrency Strategy
- **Architecture Choice:** Non-blocking I/O multiplexing (`select.select` / `selectors`)
  - The server will use a single-threaded, event-driven non-blocking I/O multiplexing with selectors. One event loop will monitor the listening socket and all connected client sockets for read and write readiness.
  - The connection begins when the listening socket accepts a client, and each accepted socket is configured as non-blocking ('sock.setblocking(False)') and registered with the selector. The event loop receives incoming data, parses the newline-delimited JSON messages, and sends them to the appropriate handler.
  - The server will utilize a receive buffer for each client to handle messages that arrive. Outgoing messages will be put into outgoing buffers for each client and will be sent once the socket is writable.
  - When a client disconnects, the server unregisters and closes its socket and handles any required forfeit / leave notifications.
- **Synchronization Logic:** 
  - With the use of the event loop, all actions are executed sequentially. This will prevent resources from being modified by multiple inputs at the same time (single threaded).
  - The server will receive messages and validate each message before applying whatever change is requested (Player X want to execute their MOVE). Each move's validation, update to the board matrix, win/draw check, change of turn, and server response will occur in one event loop which will prevent invalid moves or an out of turn move from modifying the existing game board.

### 3.2 State & Score Synchronization Across Clients
- **Turn Enforcement:**
  - The server keeps track of which players turn it is and will validate incoming MOVE messages to make sure it is that players turn and the MOVE is valid (coordinates are within the 3X3 grid, and the selected cell is not occupied already).
  - If the server declares the MOVE as INVALID, the server will send an ERROR message to the client that sent the INVALID MOVE, and will not update the board grid or the active turn to prevent bad updates. If the server declares the MOVE as VALID, the server will update the board and check for a VICTORY/DRAW condition. If no VICTORY/DRAW is detected, the server will change the active player and broadcast a STATE_UPDATE message to both clients to update the clients boards.
    - Clients only display the state of the game board provided by the server, this will prevent conflicting game states or out-of-turn moves. 
- **Score & Board Synchronization:**
 - The server has the 'Master' 3x3 grid board and round scores. After each VALID move, the server evaluates the board to see if there is a VICTORY/DRAW condition. The server will then broadcast the updated board and the next active player through STATE_UPDATE, this will make sure both clients consistently receive a valid view of the game board grid through a games cycle.
 - Once the server receives a MOVE that causes the game condition to be a VICTORY/DRAW, the server will broadcast a GAME_OVER to the clients with the result (VICTORY and which player won or DRAW and NULL for the player) and the final game board grid. The server will then increment the rounds won counter for the client who won the previous game and will clean up and start a new game if both clients are still connected.
   - The server will have a data structure to keep track of scores (dictionary most likely) that is maintained throughout the game and updated when a round ends. This will most likely be an additional aspect that will be sent to the client on GAME_OVER states and will be updated accordingly. This data structure will store the player (Player 1, Player 2) and each of their wins, draws, and losses. If the server is restarted or the process is ended, the scores will be lost because they are stored in memory so this is only kept if the games continue to go on during the same session.
 - If a player intentionally disconnects or loses their connection during the game, the server will treat this as a forfeit. The server will then declare the remaining client as the winner, update the rounds won counter for that client, and will notify the client of the VICTORY through a GAME_OVER message.
 - Because all board updates, turn transitions, and round win updates are handled by the server, the clients will not have a way to overwrite the game state.
