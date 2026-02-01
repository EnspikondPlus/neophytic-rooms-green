import httpx
import pytest
import subprocess
import time
import sys
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption(
        "--agent-url",
        default="http://localhost:9009",
        help="Green agent (proctor) URL (default: http://localhost:9009)",
    )
    parser.addoption(
        "--start-server",
        action="store_true",
        default=False,
        help="Start the green agent server automatically for tests",
    )


@pytest.fixture(scope="session")
def agent_server(request):
    """Start green agent server if --start-server flag is used."""
    if not request.config.getoption("--start-server"):
        yield None
        return

    project_root = Path(__file__).parent.parent
    server_script = project_root / "src" / "server.py"

    print("\n🟢 Starting green agent server...")
    process = subprocess.Popen(
        [sys.executable, str(server_script), "--host", "127.0.0.1", "--port", "9009"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(3)

    yield process

    print("\n🛑 Stopping green agent server...")
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture(scope="session")
def agent(request, agent_server):
    """Green agent URL fixture. Green agent must be running before tests start."""
    url = request.config.getoption("--agent-url")

    if agent_server:
        time.sleep(2)

    max_retries = 5
    for i in range(max_retries):
        try:
            response = httpx.get(f"{url}/.well-known/agent-card.json", timeout=5)
            if response.status_code == 200:
                print(f"\n✅ Connected to green agent at {url}")
                return url
        except Exception as e:
            if i < max_retries - 1:
                time.sleep(2)
            else:
                pytest.exit(
                    f"❌ Could not connect to green agent at {url} after {max_retries} retries: {e}\n"
                    f"   Make sure the green agent is running: python src/server.py",
                    returncode=1,
                )

    pytest.exit(f"Green agent at {url} returned status {response.status_code}", returncode=1)