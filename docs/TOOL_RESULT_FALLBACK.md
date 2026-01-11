# Tool Result Fallback Fix

## Problem

Tool successfully executes and returns data, but agent doesn't respond to user:

```
✅ Tool called: count_reports_for_category
✅ Tool result: "Kategoriya: 30 yillik iqtisodiy makro-ko'rsatkichlar..."
❌ Agent response: Empty / "No response generated"
```

### Root Cause

The LLM model is not generating a follow-up AIMessage after receiving tool results. The message flow is:

```
1. HumanMessage (user question)
2. AIMessage (tool call, no text content)
3. ToolMessage (tool result) ← Has the answer!
4. AIMessage (final response) ← MISSING!
```

## Solution

Implemented **dual fallback mechanism**:

### 1. System Prompt Enhancement

Added explicit instruction at the top of system prompt:

```
CRITICAL INSTRUCTION - ALWAYS RESPOND AFTER TOOL USE:
After calling ANY tool and receiving results, you MUST:
1. Analyze the tool's output carefully
2. Provide a clear, natural language response to the user
3. NEVER just call a tool without explaining the results to the user
4. Format the data in a readable way for the user
```

This tells the LLM to **always respond** after using a tool.

### 2. ToolMessage Fallback

If the agent still doesn't generate a response, we fall back to returning the ToolMessage content directly:

```python
# In extract_final_response()

# After all AIMessages are checked and skipped...
logger.warning("Attempting fallback: searching for ToolMessage content...")
for message in reversed(messages):
    if isinstance(message, ToolMessage) and message.content:
        tool_content = str(message.content).strip()
        if tool_content:
            logger.warning(f"FALLBACK: Using ToolMessage content")
            return tool_content
```

## How It Works

### Scenario 1: Model Responds (Normal Flow)
```
User → Agent → Tool Call → Tool Result → AIMessage (response) ✅
→ Return AIMessage content
```

### Scenario 2: Model Doesn't Respond (Fallback)
```
User → Agent → Tool Call → Tool Result → (no AIMessage)
→ FALLBACK: Return ToolMessage content ✅
```

### Scenario 3: XML Function Call (Fallback)
```
User → Agent → AIMessage with XML text → Parse XML → Execute Tool ✅
→ Return tool result
```

## Logging

New warning logs show when fallback is triggered:

```
WARNING - No valid response found after scanning 1 AIMessages
WARNING - All 1 AIMessages were skipped:
WARNING -   - AIMessage #1: has 1 tool calls but no content
WARNING - Message types in order:
WARNING -   0: HumanMessage (has_content=True)
WARNING -   1: AIMessage (has_content=False)
WARNING -   2: ToolMessage (has_content=True)
WARNING - Attempting fallback: searching for ToolMessage content...
WARNING - FALLBACK: Using ToolMessage content (245 chars)
INFO -   Preview: Kategoriya: 30 yillik iqtisodiy makro-ko'rsatkichlar...
```

## Files Changed

1. **core/agent.py**:
   - Enhanced system prompt with "CRITICAL INSTRUCTION"
   - Added ToolMessage fallback in `extract_final_response()`

## Benefits

1. **Always Returns Data**: Even if LLM doesn't respond, user gets the tool result
2. **Transparent**: Logs show when fallback is used
3. **User-Friendly**: Users don't see "No response generated"
4. **Backward Compatible**: Doesn't break existing functionality

## Testing

Before the fix:
```
User: "30 yillik iqtisodiy makro-ko'rsatkichlar nechta hisobot bor"
Tool: Returns "15 ta hisobot"
Agent: "" (empty)
```

After the fix:
```
User: "30 yillik iqtisodiy makro-ko'rsatkichlar nechta hisobot bor"
Tool: Returns "15 ta hisobot"
Agent: "Kategoriya: 30 yillik iqtisodiy makro-ko'rsatkichlar... 15 ta" ✅
```

## Limitations

This is a **workaround**. The ideal solution would be:

1. Fix the LLM model configuration
2. Use a model with proper ReAct support
3. Ensure `create_agent()` is configured correctly

## Long-term Fix

Check:
1. Which LLM model is being used (`base_llm`)
2. Does it support tool calling properly?
3. Is `create_agent()` using the right agent type?
4. Should we use a different agent framework?

The fallback ensures **users always get responses** while we work on the root cause.
