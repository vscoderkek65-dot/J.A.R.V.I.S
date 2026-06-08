from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from actions import mcp_client  # noqa: E402


class MCPClientTests(unittest.TestCase):
    def test_run_async_times_out_when_called_inside_running_loop(self) -> None:
        async def never_finishes():
            await asyncio.Event().wait()

        async def call_from_running_loop():
            with self.assertRaises(mcp_client.MCPClientError):
                mcp_client._run_async(never_finishes(), timeout_seconds=0.01)

        asyncio.run(call_from_running_loop())


if __name__ == "__main__":
    unittest.main()
