import argparse
import networkx as nx
import matplotlib.pyplot as plt
import sys

def decode_room_system(hex_str):
    """Decodes the 25-char hex string into a dictionary of room data."""
    try:
        bits = bin(int(hex_str, 16))[2:].zfill(100)
    except ValueError:
        print(f"Error: '{hex_str}' is not a valid hexadecimal string.")
        sys.exit(1)

    idx = 0
    current_room = int(bits[idx:idx+4], 2)
    idx += 4

    room_included, room_locked, room_haskey, room_exit = [], [], [], []
    for _ in range(8):
        room_included.append(int(bits[idx]))
        room_locked.append(int(bits[idx+1]))
        room_haskey.append(int(bits[idx+2]))
        room_exit.append(int(bits[idx+3]))
        idx += 4

    room_connections = []
    for i in range(8):
        row = [int(b) for b in bits[idx : idx+8]]
        room_connections.append(row)
        idx += 8

    return {
        "current_room": current_room,
        "room_included": room_included,
        "room_locked": room_locked,
        "room_haskey": room_haskey,
        "room_exit": room_exit,
        "room_connections": room_connections,
    }

def run_visualizer(hex_str):
    data = decode_room_system(hex_str)
    G = nx.DiGraph()

    # Create nodes for included rooms
    for i in range(8):
        if data["room_included"][i]:
            label = f"Room {i}"
            if i == data["current_room"]: label += "\n[START]"
            if data["room_haskey"][i]: label += "\n[Key ☘]"
            if data["room_locked"][i]: label += "\n[Locked ☋]"
            if data["room_exit"][i]: label += "\n[EXIT ☗]"
            
            G.add_node(i, label=label, room_data=data)

    # Add edges based on connection matrix
    for i in range(8):
        for j in range(8):
            if data["room_connections"][i][j] == 1:
                if i in G.nodes and j in G.nodes:
                    G.add_edge(i, j)

    # Style and Draw
    plt.figure(figsize=(10, 7))
    pos = nx.spring_layout(G, k=1.5) # k controls distance between nodes
    
    node_colors = []
    for n in G.nodes:
        if n == data["current_room"]: node_colors.append("#2ecc71") # Green
        elif data["room_exit"][n]: node_colors.append("#f1c40f")    # Gold
        elif data["room_locked"][n]: node_colors.append("#e74c3c")  # Red
        else: node_colors.append("#3498db")                        # Blue

    nx.draw(G, pos, with_labels=True, labels=nx.get_node_attributes(G, 'label'),
            node_color=node_colors, node_size=3500, font_size=9, 
            font_weight='bold', edge_color='#95a5a6', arrows=True)

    plt.title(f"Room System Visualization\nSource: {hex_str}")
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize an 8-room encoded system.")
    parser.add_argument("hex", help="The 25-character hex string to decode.")
    
    args = parser.parse_args()

    if len(args.hex) != 25:
        print(f"Error: Expected 25 hex characters, got {len(args.hex)}")
        sys.exit(1)

    run_visualizer(args.hex)