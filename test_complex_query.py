#!/usr/bin/env python3
"""Test complex query that requires multiple tool calls."""

import asyncio
import json
import websockets

async def test_complex_query():
    """Test with a query that requires semantic search + data fetching + calculation."""
    uri = "ws://localhost:8000/ws"

    # This query should trigger:
    # 1. search_sdmx_semantic to find population indicator
    # 2. get_sdmx_data_by_code to fetch data
    # 3. calculate_yearly_growth to calculate growth rate
    query = "Toshkent shahar aholisining 2020-2023 yillardagi o'sish sur'atini hisoblang"

    print(f"Testing complex query: {query}\n")
    print("="*70)

    try:
        async with websockets.connect(uri) as websocket:
            # Send query
            await websocket.send(query)

            # Receive messages
            tool_calls = []
            tool_results = []

            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get('type', 'unknown')

                    if msg_type == 'tool_start':
                        tool_name = data.get('tool_name')
                        tool_args = data.get('tool_args', {})
                        tool_calls.append((tool_name, tool_args))

                        print(f"\n🔧 Tool Call #{len(tool_calls)}")
                        print(f"   Name: {tool_name}")
                        print(f"   Args: {json.dumps(tool_args, ensure_ascii=False, indent=8)}")

                    elif msg_type == 'tool_result':
                        result = data.get('tool_result', '')
                        tool_results.append(result)

                        # Truncate long results
                        display_result = result[:300] + "..." if len(result) > 300 else result
                        print(f"\n✅ Tool Result #{len(tool_results)}")
                        print(f"   {display_result}")

                    elif msg_type == 'response':
                        content = data.get('content', '')
                        print(f"\n" + "="*70)
                        print(f"💬 FINAL RESPONSE:")
                        print(f"="*70)
                        print(content)
                        print(f"\n" + "="*70)
                        print(f"📊 SUMMARY:")
                        print(f"   Total tool calls: {len(tool_calls)}")
                        print(f"   Total tool results: {len(tool_results)}")
                        print(f"   Tools used: {', '.join([t[0] for t in tool_calls])}")
                        print(f"="*70)
                        break

                    elif msg_type == 'error':
                        print(f"\n❌ ERROR: {data.get('content', 'Unknown error')}")
                        break

                except json.JSONDecodeError:
                    print(f"⚠️  Non-JSON message: {message}")

    except Exception as e:
        print(f"❌ Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_complex_query())
