from ..models import RoomsState, RoomsObservation

def encode_room_system(
    room_included: list[int],
    room_locked: list[int],
    room_haskey: list[int],
    room_exit: list[int],
    room_connections: list[list[int]],
    start_room: int,
):
    """
    Encode 8-room system into a fixed 100-bit hex string (25 hex chars).
    """
    if not (0 <= start_room <= 7):
        raise ValueError("start_room must be in [0, 7]")
    bits = ""

    # Start room --> 4 bits total
    bits += format(start_room, "04b")
    # Room metadata --> 8 rooms, 4 bits each, 32 bits total
    for i in range(8):
        bits += f"{room_included[i]}{room_locked[i]}{room_haskey[i]}{room_exit[i]}"
    # Connections --> 64 bits
    for i in range(8):
        for j in range(8):
            bits += str(room_connections[i][j])

    assert len(bits) == 100, f"Expected 100 bits, got {len(bits)}"
    return hex(int(bits, 2))[2:].zfill(25)      # expected 25 hex chars out


def decode_room_system(hex_str):
    """
    Decode 25-hex-char room encoding into room system data.
    """

    if len(hex_str) != 25:
        raise ValueError(f"Expected 25 hex characters, got {len(hex_str)}")
    bits = bin(int(hex_str, 16))[2:].zfill(100)
    idx = 0

    # Start room
    current_room = int(bits[idx:idx+4], 2)
    idx += 4

    # Room system layout
    room_included = []
    room_locked = []
    room_haskey = []
    room_exit = []
    for _ in range(8):
        room_included.append(int(bits[idx]))
        room_locked.append(int(bits[idx+1]))
        room_haskey.append(int(bits[idx+2]))
        room_exit.append(int(bits[idx+3]))
        idx += 4

    # Connections
    room_connections = []
    for i in range(8):
        row = []
        for j in range(8):
            row.append(int(bits[idx]))
            idx += 1
        room_connections.append(row)

    return {
        "current_room": current_room,
        "room_included": room_included,
        "room_locked": room_locked,
        "room_haskey": room_haskey,
        "room_exit": room_exit,
        "room_connections": room_connections,
    }


def build_observation(state: RoomsState) -> RoomsObservation :
    room_known_connects = [[state.room_connections[x][y] if
                            (state.room_inspected[x] == 1 or state.room_inspected[y] == 1) else -1
                            for y in range(8)] for x in range(8)]
    
    return RoomsObservation(
        current_room=state.current_room,
        committed=state.committed,
        failure_last=state.failure_last if state.failure_show else -1,
        room_visited=state.room_visited,
        room_inspected=state.room_inspected,
        room_known_connects=room_known_connects,
        room_locked=[state.room_locked[i] if state.room_inspected[i] == 1 else -1 for i in range(8)],
        room_haskey=[state.room_haskey[i] if state.room_inspected[i] == 1 else -1 for i in range(8)],
        room_exit=[state.room_exit[i] if state.room_inspected[i] == 1 else -1 for i in range(8)],
        current_keys=state.current_keys,
        steps_remaining=state.steps_remaining,
        obs_inspect_weight=state.obs_inspect_weight
    )