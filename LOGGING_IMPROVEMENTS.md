# Logging Improvements

## Overview
Added comprehensive logging to debug "No response generated" errors and provide better visibility into agent execution.

## Changes Made

### 1. Agent Execution Logging (`core/agent.py`)

#### Tool Registration
- **Location**: `create_sdmx_agent()`
- **Added**: List all tools being registered with their names
- **Level**: INFO

```
Creating SDMX ReAct agent with tools
Registering 19 tools:
  1. search_sdmx_semantic
  2. search_sdmx_with_score
  ...
  19. compare_years
```

#### Agent Invocation
- **Location**: `run_agent()` and `run_agent_async()`
- **Added**: Detailed message analysis
- **Levels**: INFO, DEBUG, WARNING

**What's Logged:**
1. Agent invocation completion
2. Number of messages received
3. Message types (for each message)
4. Message scanning progress
5. AIMessage analysis:
   - Number of tool calls
   - Content length
   - Content preview (first 100 chars)
   - Skip reasons (tool calls only, JSON, XML, etc.)
6. Final decision (what content is returned or why not)

**Example Output:**
```
INFO - Agent invocation completed
INFO - Received 5 messages from agent
DEBUG - Message 0: SystemMessage
DEBUG - Message 1: HumanMessage
DEBUG - Message 2: AIMessage
DEBUG - Message 3: ToolMessage
DEBUG - Message 4: AIMessage
INFO - Scanning messages for final response...
DEBUG - Found AIMessage #1
DEBUG -   Content length: 245 chars
DEBUG -   Content preview: Kategoriya: 30 yillik iqtisodiy makro-ko'rsatkichlar...
INFO - Returning text content (245 chars)
```

### 2. Tool Execution Logging (`tools/sdmx_count_tool.py`)

#### count_reports_for_category
- **Added**: Response length logging
- **Level**: INFO

```
INFO - Counting reports for category: 30 yillik iqtisodiy makro-ko'rsatkichlar
INFO - Found 15 reports for category '30 yillik iqtisodiy makro-ko'rsatkichlar'
INFO - Returning response: 245 chars
```

#### count_reports_by_id
- **Added**: Response length logging
- **Level**: INFO

### 3. Response Extraction Logging (`extract_final_response()`)

Same detailed logging as agent execution, useful for streaming responses.

## How to Use

### Enable All Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Enable Only INFO and Above
```python
import logging
logging.basicConfig(level=logging.INFO)
```

### Run Test Script
```bash
python3 test_logging.py
```

This will show all logging levels and demonstrate the improved visibility.

## New Features (v2)

### Enhanced Skip Reason Logging
Now shows **exactly why** each AIMessage was skipped:
```
INFO - Extracting final response from 3 messages
INFO -   SKIP: AIMessage #1: has 1 tool calls but no content
WARNING - No valid response found after scanning 1 AIMessages
WARNING - All 1 AIMessages were skipped:
WARNING -   - AIMessage #1: has 1 tool calls but no content
WARNING - Message types in order:
WARNING -   0: HumanMessage (has_content=True)
WARNING -   1: AIMessage (has_content=False)
WARNING -   2: ToolMessage (has_content=True)
```

### Tool Call Streaming Logging
```
INFO - Processing messages and streaming tool calls...
INFO - Tool call #1: count_reports_for_category
INFO - Tool result #1: 245 chars
INFO - Streamed 1 tool calls and 1 tool results
```

### Success Logging
```
INFO - ✓ Returning text content (245 chars)
INFO -   Preview: Kategoriya: 30 yillik iqtisodiy makro-ko'rsatkichlar...
```

## Debugging "No Response Generated" Error

When you see "No response generated", check the logs for:

1. **Was the agent invoked?**
   - Look for: `"Agent invocation completed"`

2. **How many messages were received?**
   - Look for: `"Received X messages from agent"`

3. **What types of messages?**
   - Look for: `"Message 0: SystemMessage"`, etc.

4. **Were AIMessages found?**
   - Look for: `"Found AIMessage #1"`

5. **Why were they skipped?**
   - Look for: `"Skipping: has tool calls but no content"`
   - Look for: `"Skipping: short JSON-like content"`
   - Look for: `"Skipping: XML-style function call"`

6. **Final verdict:**
   - Success: `"Returning text content (X chars)"`
   - Failure: `"No valid response found after scanning X AIMessages"`

## Common Issues and Solutions

### Issue: "No valid response found after scanning 0 AIMessages"
**Cause**: Agent didn't generate any AI responses
**Solution**: Check if agent is properly initialized and tools are registered

### Issue: "Skipping: has tool calls but no content"
**Cause**: AI only made tool calls without generating text response
**Solution**: Check system prompt - agent may need explicit instruction to respond after tool use

### Issue: "Skipping: short JSON-like content"
**Cause**: Response looks like a tool call, not actual content
**Solution**: Check if agent is returning raw tool output instead of formatted response

## Next Steps

If logging shows messages are being received but not extracted:
1. Check `message.content` type - should be string
2. Check for unexpected formatting in content
3. Consider adjusting skip logic in extraction function
