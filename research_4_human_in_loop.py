#!/usr/bin/env python3
"""Stdio-based MCP Server for VS Code Integration.

This server provides research, and long-running task capabilities
via stdio communication for VS Code MCP integration.
"""
import asyncio
import json
import logging
import os
from typing import Any, Literal
from uuid import uuid4

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

from deepagents import create_deep_agent
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel
from tavily import TavilyClient

load_dotenv()

os.environ["AZURE_INFERENCE_ENDPOINT"] = os.getenv("AZURE_ENDPOINT")
os.environ["AZURE_INFERENCE_CREDENTIAL"] = os.getenv("AZURE_CREDENTIAL")
tavily_api_key = os.getenv("TAVILY_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
server = Server("research-mcp")
logger.info("Stdio-based MCP server initialized")


class ToolApprovalSchema(BaseModel):
    """Schema for eliciting tool approval decisions."""

    decision: Literal["accept", "decline", "edit"] = Field(
        description="Choose how to handle the proposed tool call",
        default="accept",
    )
    notes: str = Field(
        default="",
        description="Optional message for the agent when declining or editing",
    )
    new_action: str | None = Field(
        default=None,
        description="Override tool name when editing (leave blank to reuse original)",
    )
    new_args: dict[str, Any] | None = Field(
        default=None,
        description="Override the tool arguments when editing",
    )


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List all available tools in the server.
    
    Returns:
        List of Tool objects with their definitions
    """
    return [
        Tool(
            name="research_agent_tool",
            description="Research a topic with progress updates",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Research topic",
                        "default": "AI trends"
                    }
                }
            },
        )
    ]


async def research_agent_tool(
    topic: str,
    ctx: Any | None = None,
    progress_token: Any | None = None,
) -> list[TextContent]:
    """Research a topic with progress updates.
    
    Args:
        topic: Research topic
        ctx: Request context for sending progress notifications
        progress_token: Optional progress token from client for progress notifications
        
    Returns:
        List of TextContent with research results
    """
    tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

    # Search tool to use to do research
    search_invocations = 0
    last_search_payload: dict[str, Any] | None = None

    def internet_search(
        query: str,
        max_results: int = 5,
        topic: Literal["general", "news", "finance"] = "general",
        include_raw_content: bool = False,
    ) -> dict[str, Any]:
        """Run a web search and cache the first result set."""
        nonlocal search_invocations, last_search_payload
        if search_invocations >= 1:
            logger.info("Preventing additional internet_search call; returning cached results")
            assert last_search_payload is not None
            return last_search_payload

        search_invocations += 1
        last_search_payload = tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
        )
        return last_search_payload

    # Prompt prefix to steer the agent to be an expert researcher
    research_instructions = """You are an expert researcher. 
    Your job is to conduct thorough research, and then write a polished report.
    YOU ALWAYS USE A TODO LIST TO TRACK YOUR PROGRESS.

    You have access to a few tools.

    ## `internet_search`

    Use this to run an internet search for a given query. You can specify the number 
    of results, the topic, and whether raw content should be included.
    You must call `internet_search` exactly once per session. Plan carefully before invoking it.
    
    IMPORTANT: Use the todo list tool to track your progress.
    """

    os.environ["AZURE_INFERENCE_ENDPOINT"] = os.getenv("AZURE_ENDPOINT")
    os.environ["AZURE_INFERENCE_CREDENTIAL"] = os.getenv("AZURE_CREDENTIAL")

    interrupt_config = {
        "internet_search": {
            "allow_accept": True,
            "allow_edit": True,
            "allow_respond": True,
            "allow_ignore": False,
        }
    }

    # Create agent with human-in-the-loop interrupts enabled
    model = AzureAIChatCompletionsModel(
        credential=os.getenv("AZURE_CREDENTIAL"),
        endpoint=os.getenv("AZURE_ENDPOINT"),
        model="gpt-5-mini",
    )

    checkpointer = InMemorySaver()
    agent = create_deep_agent(
        [internet_search],
        research_instructions,
        model=model,
        interrupt_config=interrupt_config,
        checkpointer=checkpointer,
    )

    # Track todo progress so we only emit real updates
    last_reported_todos: tuple[tuple[str, str], ...] | None = None

    def parse_message_text(content: Any) -> str:
        """Flatten LangChain content payloads into plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts: list[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    texts.append(str(item["text"]))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        return str(content)

    async def emit_progress(todos: list[dict[str, Any]]) -> None:
        nonlocal last_reported_todos
        if not todos:
            return
        todo_signature = tuple(
            (todo.get("content", ""), todo.get("status", "")) for todo in todos
        )
        if todo_signature == last_reported_todos:
            return
        last_reported_todos = todo_signature

        if ctx is None or progress_token is None:
            return

        total = len(todos) or 1
        completed = sum(1 for _, status in todo_signature if status == "completed")
        status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}

        # Format a compact, multi-line summary so the client renders the progress cleanly.
        header_line = f"Progress: {completed}/{total} tasks complete"
        separator_line = "-" * len(header_line)
        todo_lines = []
        for idx, todo in enumerate(todos, 1):
            status = (todo.get("status") or "pending").strip()
            content = parse_message_text(todo.get("content", "")).strip()
            badge = status_emoji.get(status, "•")
            readable_status = status.replace("_", " ")
            todo_lines.append(f"{idx:>2}. {badge} {content} [{readable_status}]")

        message_body = "\n".join([header_line, separator_line, *todo_lines]) if todo_lines else header_line

        await ctx.session.send_progress_notification(
            progress_token=progress_token,
            progress=completed,
            total=total,
            message=message_body,
        )

    final_response_text = ""

    async def handle_interrupts(interrupts: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Resolve LangGraph interrupts by eliciting user input when available."""
        if not interrupts:
            return [{"type": "accept", "args": None}]

        interrupt_obj = interrupts[0]
        request_payload = getattr(interrupt_obj, "value", None)
        if not isinstance(request_payload, list) or not request_payload:
            return [{"type": "accept", "args": None}]

        request = request_payload[0]
        action_request = request.get("action_request", {}) if isinstance(request, dict) else {}
        tool_name = action_request.get("action", "unknown_tool")
        tool_args = action_request.get("args", {})
        description = request.get("description") or "Tool execution requires approval."

        if ctx is None:
            logger.info("No request context available; auto-approving tool '%s'", tool_name)
            return [{"type": "accept", "args": None}]

        message_lines = [description.strip(), "", f"Tool: {tool_name}", "Arguments:", json.dumps(tool_args, indent=2)]
        message = "\n".join(line for line in message_lines if line)

        try:
            elicitation_result = await ctx.session.elicit(
                message=message,
                requestedSchema=ToolApprovalSchema.model_json_schema(),
                related_request_id=getattr(ctx, "request_id", None),
            )
        except Exception as exc:  # noqa: BLE001 - errors expected when client lacks support
            logger.info("Elicitation failed; auto-approving tool '%s': %s", tool_name, exc)
            return [{"type": "accept", "args": None}]

        decision = "accept"
        notes = ""
        new_action = None
        new_args = None

        if elicitation_result:
            if getattr(elicitation_result, "action", "") == "decline":
                decision = "decline"
            content = getattr(elicitation_result, "content", None)
            if isinstance(content, dict):
                decision = content.get("decision", decision)
                notes = content.get("notes", "")
                new_action = content.get("new_action")
                new_args = content.get("new_args")

        if decision == "accept":
            logger.info("User approved tool '%s'", tool_name)
            return [{"type": "accept", "args": None}]

        if decision == "edit":
            target_action = new_action or tool_name
            edited_args = new_args if isinstance(new_args, dict) else tool_args
            logger.info("User edited tool '%s' -> '%s'", tool_name, target_action)
            return [
                {
                    "type": "edit",
                    "args": {
                        "action": target_action,
                        "args": edited_args,
                    },
                }
            ]

        decline_message = notes or "Request declined by user."
        logger.info("User declined tool '%s' with message: %s", tool_name, decline_message)
        return [{"type": "response", "args": decline_message}]

    thread_config = {"configurable": {"thread_id": str(uuid4())}}
    pending_payload: Command | dict[str, Any] | None = {
        "messages": [{"role": "user", "content": topic}]
    }

    while pending_payload is not None:
        current_payload = pending_payload
        pending_payload = None
        for chunk in agent.stream(current_payload, config=thread_config, stream_mode="values"):
            if isinstance(chunk, dict):
                todos_from_state = chunk.get("state", {}).get("todos")
                if todos_from_state:
                    await emit_progress(todos_from_state)

                interrupts = chunk.get("__interrupt__")
                if interrupts:
                    responses = await handle_interrupts(interrupts)
                    pending_payload = Command(resume=responses)
                    break

                if "messages" not in chunk:
                    continue

                for message in chunk["messages"]:
                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            if tool_call.get("name") == "write_todos":
                                todos = tool_call.get("args", {}).get("todos")
                                if isinstance(todos, list):
                                    await emit_progress(todos)

                    if getattr(message, "type", None) == "ai":
                        final_response_text = parse_message_text(getattr(message, "content", ""))
            else:
                continue

        if pending_payload is None:
            break

    return [TextContent(type="text", text=final_response_text)]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Any):
    """Route tool calls to the appropriate handler function.
    
    Args:
        name: Tool name to execute
        arguments: Arguments for the tool
        
    Returns:
        List of TextContent results from the tool
        
    Raises:
        ValueError: If tool name is not recognized
    """
    logger.info(f"Tool called: {name} with args: {arguments}")
    
    # Get the request context for progress notifications
    ctx = server.request_context
    
    # Extract progress token from request metadata
    progress_token = None
    if ctx.meta:
        progress_token = ctx.meta.progressToken
    
    logger.info(f"Progress token from request: {progress_token}")
    
    # Ensure arguments is dict-like to avoid attribute errors
    if arguments is None:
        arguments = {}

    elif name == "research_agent_tool":
        topic = arguments.get("topic", "AI trends")
        
        result = await research_agent_tool(topic, ctx, progress_token)
        return result
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the stdio server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
