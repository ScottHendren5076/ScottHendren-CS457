```mermaid
A["INIT"] --> B["WAITING_FOR_PLAYERS"] 
B -->|CONNECT - Player 1| C["LOBBY_WAIT"] 
C -->|Send LOBBY_WAIT| B 
B -->|CONNECT - Player 2| D["GAME_START"] 
D -->|Send GAME_START| E["PLAYER_TURN"] 
E -->|MOVE received| F["EVALUATE_MOVE"] 
E -->|DISCONNECT - FORFEIT/QUIT| G["GAME_OVER"] 
E -->|Unexpected TCP disconnect|G 
F -->|Invalid move| H["ERROR"] 
H -->|Send ERROR| E 
F -->|Valid move| I["CHECK_WIN_DRAW"] 
I -->|Player wins| G 
I -->|Board full - Draw| G 
I -->|Game continues| J["STATE_UPDATE"] 
J -->|Send STATE_UPDATE| E 
G -->|Victory / Draw / Forfeit| K["Send GAME_OVER"] 
K --> L["CLEANUP"] 
L -->|Reset for new game| B 
L -->|Server shutdown| M["END"]
```
