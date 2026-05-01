#!/usr/bin/env python3
"""Test direct response without tool usage."""

import asyncio
import json
import websockets

from core.settings import settings


async def test_direct_response():
    """Test with queries that might not trigger tools."""
    uri = f"ws://localhost:{settings.port}/ws"

    test_queries = [
        "Salom",  # Simple greeting
        "Rahmat",  # Thank you
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Testing: {query}")
        print(f"{'='*60}\n")

        try:
            async with websockets.connect(uri) as websocket:
                await websocket.send(query)

                tool_count = 0
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        msg_type = data.get('type')

                        if msg_type == 'tool_start':
                            tool_count += 1
                            print(f"🔧 Tool: {data.get('tool_name')}")

                        elif msg_type == 'tool_result':
                            print(f"✅ Result received")

                        elif msg_type == 'response':
                            content = data.get('content', '')
                            if len(content) > 200:
                                content = content[:200] + "..."
                            print(f"💬 Response: {content}")
                            print(f"📊 Tools used: {tool_count}")
                            break

                        elif msg_type == 'error':
                            print(f"❌ Error: {data.get('content')}")
                            break

                    except json.JSONDecodeError:
                        print(f"⚠️  Non-JSON: {message}")

        except Exception as e:
            print(f"❌ Error: {e}")

        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(test_direct_response())
