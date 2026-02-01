import random
import json
import collections


# ---------------------------------------------------------------------------
# 1.  ENCODER  (unchanged — do not modify)
# ---------------------------------------------------------------------------

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
        raise ValueError(f"start_room must be in [0, 7], got {start_room}")

    bits = ""

    # Start room (4 bits)
    bits += format(start_room, "04b")

    # Room metadata (8 rooms x 4 bits)
    for i in range(8):
        bits += f"{room_included[i]}{room_locked[i]}{room_haskey[i]}{room_exit[i]}"

    # Connections (8x8)
    for i in range(8):
        for j in range(8):
            bits += str(room_connections[i][j])

    assert len(bits) == 100, f"Expected 100 bits, got {len(bits)}"

    return hex(int(bits, 2))[2:].zfill(25)


# ---------------------------------------------------------------------------
# 2.  GRAPH GENERATORS
#     Three modes, all guaranteed to produce a single connected component.
# ---------------------------------------------------------------------------

def _generate_random_tree(num_rooms: int) -> dict[int, list[int]]:
    """
    Classic random-tree construction.  Each new node attaches to a uniformly
    random existing node.  Result: a connected, cycle-free graph.
    """
    adj: dict[int, list[int]] = {i: [] for i in range(num_rooms)}
    for i in range(1, num_rooms):
        parent = random.randint(0, i - 1)
        adj[parent].append(i)
        adj[i].append(parent)
    return adj


def _generate_binary_tree(num_rooms: int) -> dict[int, list[int]]:
    """
    Strict binary-tree construction.  Each node may have at most 2 children.
    Nodes are assigned as children in BFS order (level by level, left to right).
    Result: a connected, cycle-free graph where every node has degree <= 3
    (<=2 children + 1 parent; root has no parent so degree <= 2).
    """
    adj: dict[int, list[int]] = {i: [] for i in range(num_rooms)}
    parent_queue: collections.deque[tuple[int, int]] = collections.deque([(0, 2)])

    for i in range(1, num_rooms):
        if not parent_queue:
            break
        parent, slots = parent_queue[0]
        adj[parent].append(i)
        adj[i].append(parent)
        slots -= 1
        if slots == 0:
            parent_queue.popleft()
        else:
            parent_queue[0] = (parent, slots)
        parent_queue.append((i, 2))

    return adj


def _generate_general_graph(num_rooms: int) -> dict[int, list[int]]:
    """
    Starts with a random spanning tree (guarantees connectivity), then adds
    extra edges (cycles) at random.  At least 1 extra edge is always added so
    the graph is guaranteed to contain a cycle.
    """
    adj: dict[int, list[int]] = _generate_random_tree(num_rooms)

    existing: set[tuple[int, int]] = set()
    for u in range(num_rooms):
        for v in adj[u]:
            existing.add((min(u, v), max(u, v)))

    all_possible = [
        (u, v)
        for u in range(num_rooms)
        for v in range(u + 1, num_rooms)
        if (u, v) not in existing
    ]

    if all_possible:
        max_extra = min(len(all_possible), max(1, num_rooms - 1))
        num_extra = random.randint(1, max_extra)
        extras = random.sample(all_possible, num_extra)
        for u, v in extras:
            adj[u].append(v)
            adj[v].append(u)

    return adj


def generate_graph(num_rooms: int, mode: str, no_loops: bool) -> dict[int, list[int]]:
    """
    Dispatcher.  Respects the no_loops flag:
      - no_loops=True AND mode="general"  -> falls back to random_tree
      - binary_tree and random_tree are inherently loop-free.

    mode in {"random_tree", "binary_tree", "general"}
    """
    if no_loops and mode == "general":
        mode = "random_tree"

    # A cycle requires >= 3 nodes; fall back silently for tiny graphs
    if mode == "general" and num_rooms < 3:
        mode = "random_tree"

    if mode == "binary_tree":
        return _generate_binary_tree(num_rooms)
    elif mode == "general":
        return _generate_general_graph(num_rooms)
    else:
        return _generate_random_tree(num_rooms)


def _has_cycle(adj: dict[int, list[int]], num_rooms: int) -> bool:
    """Simple DFS cycle detection for undirected graph."""
    visited: set[int] = set()

    def dfs(node: int, parent: int) -> bool:
        visited.add(node)
        for nb in adj[node]:
            if nb >= num_rooms:
                continue
            if nb not in visited:
                if dfs(nb, node):
                    return True
            elif nb != parent:
                return True
        return False

    return dfs(0, -1)


# ---------------------------------------------------------------------------
# 3.  STATE-SPACE BFS SOLVER
# ---------------------------------------------------------------------------

def is_solvable_v2(
    adj: dict[int, list[int]],
    num_rooms: int,
    start: int,
    exit_room: int,
    locked_rooms: set[int],
    key_rooms: set[int],
    *,
    init_opened: frozenset | None = None,
    init_collected: frozenset | None = None,
) -> bool:
    """
    Determines whether there EXISTS any sequence of moves that reaches the exit.

    Keys are fungible: any key opens any single locked door.  The player chooses
    which door to spend a key on, so we must search over all possible choices.

    State = (current_room, frozenset_of_opened_doors, frozenset_of_collected_keys)
    keys_held = len(collected) - len(opened)   (derived)

    Max state space for <= 8 rooms, <= 4 keys: 8 x 2^4 x 2^4 = 2048 -- instant.

    Optional keyword arguments (init_opened, init_collected) let the softlock
    detector seed the search with a pre-existing world state so it can simulate
    "what happens after the player already made one specific choice?"
    """
    locked_frozen = frozenset(locked_rooms)
    key_frozen = frozenset(key_rooms)

    def collect(room: int, collected: frozenset) -> frozenset:
        """Pick up the key in room if one exists."""
        if room in key_frozen:
            return collected | frozenset([room])
        return collected

    # --- Build initial state ---
    if init_opened is None:
        init_opened = frozenset()
    if init_collected is None:
        init_collected = frozenset()

    # Always collect the key at the start room
    init_collected = collect(start, init_collected)

    start_state = (start, init_opened, init_collected)
    visited: set = {start_state}
    queue: collections.deque = collections.deque([start_state])

    while queue:
        curr, opened, collected = queue.popleft()

        if curr == exit_room:
            return True

        held = len(collected) - len(opened)

        for neighbor in adj[curr]:
            if neighbor >= num_rooms:
                continue

            if neighbor in locked_frozen and neighbor not in opened:
                # Locked and sealed -- need a key to open
                if held <= 0:
                    continue

                new_opened = opened | frozenset([neighbor])
                new_collected = collect(neighbor, collected)
                state = (neighbor, new_opened, new_collected)
                if state not in visited:
                    visited.add(state)
                    queue.append(state)
            else:
                # Unlocked or already opened -- free passage
                new_collected = collect(neighbor, collected)
                state = (neighbor, opened, new_collected)
                if state not in visited:
                    visited.add(state)
                    queue.append(state)

    return False


# ---------------------------------------------------------------------------
# 4.  SOFTLOCK DETECTOR
# ---------------------------------------------------------------------------

def can_be_softlocked(
    adj: dict[int, list[int]],
    num_rooms: int,
    start: int,
    exit_room: int,
    locked_rooms: set[int],
    key_rooms: set[int],
) -> bool:
    """
    Returns True if there exists at least one reachable locked door that, if
    opened first ("wastefully"), leaves the player unable to reach the exit.

    Algorithm
    ---------
    1. BFS from start ignoring all locked doors  -> free_area.
    2. Collect all keys in free_area             -> keys the player holds
       before making any door-opening decision.
    3. Identify frontier_locks: locked rooms adjacent to free_area.
    4. For each frontier lock W:
         Seed the solver with:
           opened    = {W}                  <- key already spent on W
           collected = keys_in(free_area)   <- everything freely reachable
         The solver's collect() will additionally pick up any key inside W.
         If the solver returns False -> opening W first is a softlock.
    """
    locked_frozen = frozenset(locked_rooms)
    key_frozen = frozenset(key_rooms)

    # --- 1. Free area (reachable without opening any locked door) ---
    free_area: set[int] = set()
    q: collections.deque = collections.deque([start])
    free_area.add(start)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v >= num_rooms or v in free_area:
                continue
            if v in locked_frozen:
                continue  # blocked
            free_area.add(v)
            q.append(v)

    # --- 2. Keys collected in free area ---
    collected_in_free: frozenset = frozenset(free_area & key_frozen)

    if len(collected_in_free) == 0:
        return False  # no keys to waste

    # --- 3. Frontier locks ---
    frontier_locks: set[int] = set()
    for u in free_area:
        for v in adj[u]:
            if v < num_rooms and v in locked_frozen and v not in free_area:
                frontier_locks.add(v)

    if not frontier_locks:
        return False

    # --- 4. Try wasting a key on each frontier lock ---
    for wasteful_door in frontier_locks:
        seeded_opened = frozenset([wasteful_door])

        still_solvable = is_solvable_v2(
            adj,
            num_rooms,
            start,
            exit_room,
            locked_rooms,
            key_rooms,
            init_opened=seeded_opened,
            init_collected=collected_in_free,
        )

        if not still_solvable:
            return True  # wasting a key on this door -> softlock

    return False


# ---------------------------------------------------------------------------
# 5.  GENERATOR
# ---------------------------------------------------------------------------

GRAPH_MODES = ("random_tree", "binary_tree", "general")


def generate_random_system(
    difficulty_settings: dict,
    graph_mode: str = "random_tree",
    no_loops: bool = True,
    require_softlock: bool = False,
) -> dict:
    """
    Generates a single valid room system.  Retries until all constraints pass.

    Parameters
    ----------
    difficulty_settings : dict
        Must contain 'rooms': (min, max) and 'locks': (min, max).
    graph_mode : str
        One of "random_tree", "binary_tree", "general".
    no_loops : bool
        If True, cycles are forbidden (general mode falls back to random_tree).
    require_softlock : bool
        If True, the generated system must have at least one softlock trap.
        Only meaningful when locks > 0; ignored otherwise.
    """
    min_rooms, max_rooms = difficulty_settings["rooms"]
    min_locks, max_locks = difficulty_settings["locks"]

    attempts = 0
    max_attempts = 5000

    while attempts < max_attempts:
        attempts += 1

        # --- 1. Room count ---
        num_rooms = random.randint(min_rooms, max_rooms)

        # --- 2. Connected graph ---
        adj = generate_graph(num_rooms, graph_mode, no_loops)

        # --- 3. Start and exit (distinct) ---
        start_room = random.randint(0, num_rooms - 1)
        possible_exits = [n for n in range(num_rooms) if n != start_room]
        exit_room = random.choice(possible_exits)

        # --- 4. Lock count ---
        num_locks = random.randint(min_locks, max_locks)

        # Can't lock the start room (player begins there)
        lock_candidates = [n for n in range(num_rooms) if n != start_room]
        if num_locks > len(lock_candidates):
            num_locks = len(lock_candidates)

        locked_rooms = set(random.sample(lock_candidates, num_locks))

        # --- 5. Key placement (exactly num_locks keys, one per room) ---
        if num_locks > num_rooms:
            continue

        key_rooms = set(random.sample(list(range(num_rooms)), num_locks))

        # --- 6. Solvability ---
        if not is_solvable_v2(adj, num_rooms, start_room, exit_room, locked_rooms, key_rooms):
            continue

        # --- 7. Softlock requirement ---
        if require_softlock and num_locks > 0:
            if not can_be_softlocked(
                adj, num_rooms, start_room, exit_room, locked_rooms, key_rooms
            ):
                continue

        # --- 8. Encode ---
        room_included = [1 if i < num_rooms else 0 for i in range(8)]
        room_locked_list = [1 if i in locked_rooms else 0 for i in range(8)]
        room_haskey_list = [1 if i in key_rooms else 0 for i in range(8)]
        room_exit_list = [1 if i == exit_room else 0 for i in range(8)]

        room_connections_matrix = [[0] * 8 for _ in range(8)]
        for i in range(num_rooms):
            for neighbor in adj[i]:
                if neighbor < 8:
                    room_connections_matrix[i][neighbor] = 1

        try:
            hex_string = encode_room_system(
                room_included=room_included,
                room_locked=room_locked_list,
                room_haskey=room_haskey_list,
                room_exit=room_exit_list,
                room_connections=room_connections_matrix,
                start_room=start_room,
            )
        except Exception:
            continue

        # --- 9. Metadata ---
        bfs_q: collections.deque = collections.deque([(start_room, 0)])
        bfs_v: set[int] = {start_room}
        dist = 0
        while bfs_q:
            curr, d = bfs_q.popleft()
            if curr == exit_room:
                dist = d
                break
            for n in adj[curr]:
                if n < num_rooms and n not in bfs_v:
                    bfs_v.add(n)
                    bfs_q.append((n, d + 1))

        has_cycles = _has_cycle(adj, num_rooms)
        softlock_flag = require_softlock and num_locks > 0

        return {
            "encoding": hex_string,
            "optimal_steps": dist + (num_locks * 2),
            "description": (
                f"{graph_mode.replace('_', ' ').title()} with {num_rooms} rooms, "
                f"{num_locks} lock(s)/key(s)"
                + (", cycles present" if has_cycles else "")
                + (", softlock possible" if softlock_flag else "")
            ),
            "graph_mode": graph_mode,
            "has_cycles": has_cycles,
            "softlock_possible": softlock_flag,
        }

    raise RuntimeError(
        f"Failed to generate a valid system after {max_attempts} attempts "
        f"(mode={graph_mode}, no_loops={no_loops}, settings={difficulty_settings})"
    )


# ---------------------------------------------------------------------------
# 6.  DATASET GENERATION
# ---------------------------------------------------------------------------

def generate_dataset(
    graph_mode: str = "random_tree",
    no_loops: bool = True,
) -> dict:
    """
    Main entry point.  Generates the full tiered dataset.

    Parameters
    ----------
    graph_mode : str
        "random_tree" | "binary_tree" | "general"
    no_loops : bool
        If True, general mode is suppressed (falls back to random_tree).
        binary_tree and random_tree are always loop-free.
    """
    difficulties = {
        "tutorial":  {"rooms": (2, 3), "locks": (0, 0), "count": 20, "softlock": False},
        "easy":      {"rooms": (4, 5), "locks": (0, 1), "count": 60, "softlock": False},
        "medium":    {"rooms": (5, 6), "locks": (1, 2), "count": 80, "softlock": True},
        "hard":      {"rooms": (6, 7), "locks": (2, 3), "count": 20, "softlock": True},
        "very_hard": {"rooms": (7, 8), "locks": (3, 4), "count": 20, "softlock": True},
    }

    output_data: dict = {}

    for diff_name, config in difficulties.items():
        output_data[diff_name] = {
            "description": f"{diff_name.capitalize()} difficulty levels",
            "graph_mode": graph_mode,
            "no_loops": no_loops,
            "cases": [],
        }

        for i in range(config["count"]):
            sys_data = generate_random_system(
                difficulty_settings=config,
                graph_mode=graph_mode,
                no_loops=no_loops,
                require_softlock=config["softlock"],
            )

            case = {
                "id": f"{diff_name}_{i + 1:02d}",
                "encoding": sys_data["encoding"],
                "difficulty": diff_name,
                "optimal_steps": sys_data["optimal_steps"],
                "description": sys_data["description"],
                "graph_mode": sys_data["graph_mode"],
                "has_cycles": sys_data["has_cycles"],
                "softlock_possible": sys_data["softlock_possible"],
            }
            output_data[diff_name]["cases"].append(case)

    return output_data


# ---------------------------------------------------------------------------
# 7.  CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate room-system puzzle dataset."
    )
    parser.add_argument(
        "--mode",
        choices=GRAPH_MODES,
        default="random_tree",
        help=(
            "Graph structure mode. "
            "'random_tree': connected tree, random shape. "
            "'binary_tree': each node has <= 2 children. "
            "'general': tree + extra edges (cycles). "
            "Overridden to 'random_tree' if --no-loops is set."
        ),
    )
    parser.add_argument(
        "--no-loops",
        action="store_true",
        default=False,
        help="Forbid cycles. Forces 'general' mode back to 'random_tree'.",
    )
    parser.add_argument(
        "--output",
        default="room_systems.json",
        help="Output JSON file path (default: room_systems.json).",
    )

    args = parser.parse_args()

    print(f"Generating dataset ... (mode={args.mode}, no_loops={args.no_loops})")
    dataset = generate_dataset(graph_mode=args.mode, no_loops=args.no_loops)

    with open(args.output, "w") as f:
        json.dump(dataset, f, indent=2)

    total = sum(len(tier["cases"]) for tier in dataset.values())
    print(f"Done. {total} levels written to {args.output}")
    print()
    for tier_name, tier_data in dataset.items():
        print(f"  {tier_name:12s} -- {len(tier_data['cases']):3d} levels")