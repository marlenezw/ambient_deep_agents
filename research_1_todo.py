#!/usr/bin/env python3
"""Stdio-based MCP Server for VS Code Integration.

This server provides research, and long-running task capabilities
via stdio communication for VS Code MCP integration.
"""
import os
from typing import Literal
import asyncio
import logging
from typing import Any

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from tavily import TavilyClient
from deepagents import create_deep_agent
from langchain_azure_ai.chat_models import AzureAIChatCompletionsModel

from dotenv import load_dotenv
load_dotenv()

os.environ["AZURE_INFERENCE_ENDPOINT"]  = os.getenv("AZURE_ENDPOINT")
os.environ["AZURE_INFERENCE_CREDENTIAL"] = os.getenv("AZURE_CREDENTIAL")
tavily_api_key = os.getenv("TAVILY_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
server = Server("research-mcp")
logger.info("Stdio-based MCP server initialized")


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


async def research_agent_tool(topic: str, ctx, progress_token=None) -> list[TextContent]:
    """Research a topic with progress updates.
    
    Args:
        topic: Research topic
        ctx: Request context for sending progress notifications
        progress_token: Optional progress token from client for progress notifications
        
    Returns:
        List of TextContent with research results
    """
    logger.info(f"Research agent: topic={topic}")
    
    steps = [
        "Gathering sources...",
        "Analyzing data...", 
        "Summarizing findings...",
        "Finalizing report..."
    ]
    
    total_steps = len(steps)
    
    for i, step in enumerate(steps):
        current_step = i + 1
        progress_message = f"({current_step}/{total_steps}) {step}"
        logger.info(f"Step {current_step}/{total_steps}: {step}")
        
        # Send progress notification to VS Code if token provided
        if progress_token:
            await ctx.session.send_progress_notification(
                progress_token=progress_token,
                progress=current_step,
                total=total_steps,
                message=progress_message
            )
        
        await anyio.sleep(2)  # 2 second delay between steps
    
    # Final progress notification
    if progress_token:
        await ctx.session.send_progress_notification(
            progress_token=progress_token,
            progress=total_steps,
            total=total_steps,
            message=f"({total_steps}/{total_steps}) Research completed!"
        )
    
    result_text = f"🔍 Research on '{topic}' completed successfully!"
    logger.info(result_text)
    
    return [TextContent(type="text", text=result_text)]


# async def research_agent_tool(
#     topic: str,
#     ctx: Any | None = None,
#     progress_token: Any | None = None,
# ) -> list[TextContent]:
#     """Research a topic with progress updates.
    
#     Args:
#         topic: Research topic
#         ctx: Request context for sending progress notifications
#         progress_token: Optional progress token from client for progress notifications
        
#     Returns:
#         List of TextContent with research results
#     """
#     tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

#     # Search tool to use to do research
#     def internet_search(
#         query: str,
#         max_results: int = 5,
#         topic: Literal["general", "news", "finance"] = "general",
#         include_raw_content: bool = False,
#     ):
#         """Run a web search."""
#         return tavily_client.search(
#             query,
#             max_results=max_results,
#             include_raw_content=include_raw_content,
#             topic=topic,
#         )

#     # Prompt prefix to steer the agent to be an expert researcher
#     research_instructions = """You are an expert researcher. 
#     Your job is to conduct thorough research, and then write a polished report.
#     YOU ALWAYS USE A TODO LIST TO TRACK YOUR PROGRESS.

#     You have access to a few tools.

#     ## `internet_search`

#     Use this to run an internet search for a given query. You can specify the number 
#     of results, the topic, and whether raw content should be included. 
    
#     IMPORTANT: Use the todo list tool to track your progress.
#     """

#     os.environ["AZURE_INFERENCE_ENDPOINT"]  = os.getenv("AZURE_ENDPOINT")
#     os.environ["AZURE_INFERENCE_CREDENTIAL"] = os.getenv("AZURE_CREDENTIAL")

#     # Create agent using create_react_agent directly
#     model = AzureAIChatCompletionsModel(
#         credential=os.getenv("AZURE_CREDENTIAL"),
#         endpoint=os.getenv("AZURE_ENDPOINT"),
#         model="gpt-5-mini",
#     )

#     # Create the agent
#     agent = create_deep_agent(
#         [internet_search],
#         research_instructions,
#         model=model,
#     )

#     # Track todo progress so we only emit real updates
#     last_reported_todos: tuple[tuple[str, str], ...] | None = None

#     def parse_message_text(content: Any) -> str:
#         """Flatten LangChain content payloads into plain text."""
#         if isinstance(content, str):
#             return content
#         if isinstance(content, list):
#             texts: list[str] = []
#             for item in content:
#                 if isinstance(item, dict) and "text" in item:
#                     texts.append(str(item["text"]))
#                 else:
#                     texts.append(str(item))
#             return "\n".join(texts)
#         return str(content)

#     async def emit_progress(todos: list[dict[str, Any]]) -> None:
#         nonlocal last_reported_todos
#         if not todos:
#             return
#         todo_signature = tuple(
#             (todo.get("content", ""), todo.get("status", "")) for todo in todos
#         )
#         if todo_signature == last_reported_todos:
#             return
#         last_reported_todos = todo_signature

#         if ctx is None or progress_token is None:
#             return

#         total = len(todos) or 1
#         completed = sum(1 for _, status in todo_signature if status == "completed")
#         status_emoji = {"pending": "⏳", "in_progress": "🔄", "completed": "✅"}

#         # Format a compact, multi-line summary so the client renders the progress cleanly.
#         header_line = f"Progress: {completed}/{total} tasks complete"
#         separator_line = "-" * len(header_line)
#         todo_lines = []
#         for idx, todo in enumerate(todos, 1):
#             status = (todo.get("status") or "pending").strip()
#             content = parse_message_text(todo.get("content", "")).strip()
#             badge = status_emoji.get(status, "•")
#             readable_status = status.replace("_", " ")
#             todo_lines.append(f"{idx:>2}. {badge} {content} [{readable_status}]")

#         message_body = "\n".join([header_line, separator_line, *todo_lines]) if todo_lines else header_line

#         await ctx.session.send_progress_notification(
#             progress_token=progress_token,
#             progress=completed,
#             total=total,
#             message=message_body,
#         )

#     final_response_text = ""

#     for chunk in agent.stream(
#         input={"messages": [{"role": "user", "content": topic}]},
#         stream_mode="values",
#     ):
#         todos_from_state = chunk.get("state", {}).get("todos") if isinstance(chunk, dict) else None
#         if todos_from_state:
#             await emit_progress(todos_from_state)

#         if "messages" not in chunk:
#             continue

#         for message in chunk["messages"]:
#             if hasattr(message, "tool_calls") and message.tool_calls:
#                 for tool_call in message.tool_calls:
#                     if tool_call.get("name") == "write_todos":
#                         todos = tool_call.get("args", {}).get("todos")
#                         if isinstance(todos, list):
#                             await emit_progress(todos)

#             if getattr(message, "type", None) == "ai":
#                 final_response_text = parse_message_text(getattr(message, "content", ""))

#     return [TextContent(type="text", text=final_response_text)]


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
