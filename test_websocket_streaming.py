#!/usr/bin/env python3
"""Test WebSocket streaming functionality for tool visualization."""

import asyncio
import json
import websockets

async def test_websocket_streaming():
    """Test WebSocket with a query that should trigger tool usage."""
    uri = "ws://localhost:8000/ws"

    # Test queries
    test_queries = [
        "aholi soni",  # Should trigger search_sdmx_semantic tool
        "SDMX ID 224 nima haqida",  # Should trigger get_sdmx_metadata tool
        "2013-yil Andijon viloyatida nechta bola tug'ilgan?",  # Should trigger multiple tools
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Testing query: {query}")
        print(f"{'='*60}\n")

        try:
            async with websockets.connect(uri) as websocket:
                # Send query
                await websocket.send(query)
                print(f"✓ Sent query: {query}\n")

                # Receive messages
                message_count = 0
                tool_count = 0

                async for message in websocket:
                    try:
                        data = json.loads(message)
                        message_count += 1

                        msg_type = data.get('type', 'unknown')

                        if msg_type == 'tool_start':
                            tool_count += 1
                            print(f"📌 Tool #{tool_count} Started:")
                            print(f"   Tool Name: {data.get('tool_name')}")
                            print(f"   Arguments: {json.dumps(data.get('tool_args', {}), ensure_ascii=False, indent=6)}")
                            print()

                        elif msg_type == 'tool_result':
                            result = data.get('tool_result', '')
                            # Truncate long results
                            if len(result) > 200:
                                result = result[:200] + "..."
                            print(f"✅ Tool Result:")
                            print(f"   {result}")
                            print()

                        elif msg_type == 'response':
                            content = data.get('content', '')
                            # Truncate long responses
                            if len(content) > 300:
                                content = content[:300] + "..."
                            print(f"💬 Final Response:")
                            print(f"   {content}")
                            print()
                            break  # End of conversation

                        elif msg_type == 'error':
                            print(f"❌ Error:")
                            print(f"   {data.get('content', 'Unknown error')}")
                            print()
                            break

                    except json.JSONDecodeError:
                        print(f"⚠️  Non-JSON message: {message}")

                print(f"\n📊 Summary:")
                print(f"   Total messages: {message_count}")
                print(f"   Tools used: {tool_count}")

        except Exception as e:
            print(f"❌ Error connecting or receiving: {e}")

        # Wait between queries
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(test_websocket_streaming())
