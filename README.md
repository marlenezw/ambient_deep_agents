# Ambient Deep Agents

A comprehensive research and demonstration project showcasing how to build Ambient Deep Agents using **LangChain** and **Azure AI Foundry**. This project explores advanced agent patterns including todo management, context offloading, human-in-the-loop workflows, and sub-agent delegation.

## 🎯 Project Overview

**Ambient Deep Agents** demonstrates four core research areas for building production-ready AI agent systems:

1. **Todo Management & Progress Tracking** (`research_1_todo.py`)
2. **Context Offloading via Virtual Filesystems** (`research_2a_files.ipynb`, `research_2b_files.py`)
3. **Sub-Agent Delegation & Parallel Execution** (`research_3_subagents.ipynb`)
4. **Human-in-the-Loop Workflows** (`research_4_human_in_loop.py`)

Each research component builds upon the previous, culminating in a sophisticated agent framework capable of handling complex, long-running tasks with proper oversight and context management.

## 🏗️ Architecture

The project is built on:

- **LangChain** for agent orchestration and tool management
- **Azure AI Foundry** (GPT models) for language processing
- **LangGraph** for stateful agent workflows
- **Model Context Protocol (MCP)** for VS Code integration
- **Tavily API** for web search capabilities

## 📚 Research Components

### 1. Todo Management (`research_1_todo.py`)

Demonstrates structured task tracking and progress visualization for complex agent workflows.

**Key Features:**

- MCP server for VS Code integration
- Progress notifications with real-time updates
- Structured todo list management
- Azure AI model integration

**Use Cases:**

- Breaking down complex tasks into manageable steps
- Tracking progress across long-running operations
- Providing user visibility into agent reasoning

```python
# Core functionality: Research agent with progress tracking
@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="research_agent_tool",
            description="Research a topic with progress updates",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"}
                }
            },
        )
    ]
```

### 2. Context Offloading (`research_2a_files.ipynb`, `research_2b_files.py`)

Explores virtual filesystem patterns for managing agent context and preventing token overflow.

**Key Features:**

- Virtual file system stored in LangGraph state
- Context compression and retrieval strategies
- File-based resource management
- Durable resource links for price tracking

**Why This Matters:**
> Agent context windows can grow rapidly during complex tasks—the average production task uses approximately 50 tool calls, creating substantial context accumulation. A powerful technique for managing this growth is **context offloading** through filesystem operations.

**Implementation Highlights:**

```python
@tool(description=WRITE_FILE_DESCRIPTION)
def write_file(
    file_path: str,
    content: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Write content to a file in the virtual filesystem."""
    files = state.get("files", {})
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)]
        }
    )
```

### 3. Sub-Agent Delegation (`research_3_subagents.ipynb`)

Demonstrates advanced multi-agent patterns with parallel execution and specialized sub-agents.

**Key Features:**
- Parallel sub-agent execution
- Specialized agent roles (research, GitHub operations, security)
- Context isolation between agents
- Strategic delegation patterns

**Sub-Agent Types:**
- **Research Agent**: Web search and information gathering
- **GitHub Info Agent**: Repository reading and analysis
- **Draft PR Agent**: Pull request creation and management
- **Security Agent**: Vulnerability and compliance monitoring

**Parallel Execution Example:**

```python
# Create research sub-agent
research_sub_agent = {
    "name": "research-sub-agent", 
    "description": "Delegate research to the sub-agent researcher",
    "prompt": RESEARCHER_INSTRUCTIONS.format(date=get_today_str()),
    "tools": ["tavily_search", "think_tool"],
}

agent = create_deep_agent(
    sub_agent_tools,
    INSTRUCTIONS,
    subagents=[research_sub_agent],
    model=model,
)
```

### 4. Human-in-the-Loop (`research_4_human_in_loop.py`)

Implements approval workflows and user oversight for sensitive operations.

**Key Features:**
- Interactive approval prompts
- Tool call interception and modification
- Structured decision schemas
- Graceful fallback handling

**Approval Flow:**

```python
class ToolApprovalSchema(BaseModel):
    decision: Literal["accept", "decline", "edit"] = Field(
        description="Choose how to handle the proposed tool call"
    )
    notes: str = Field(description="Optional message for the agent")
    new_action: str | None = Field(description="Override tool name when editing")
    new_args: dict[str, Any] | None = Field(description="Override tool arguments")
```

## 🚀 Getting Started

### Prerequisites

1. **Azure AI Foundry Account**: Set up your Azure AI service
2. **API Keys**: Configure Tavily API for web search
3. **Python 3.8+**: With required dependencies

### Environment Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd azure_dev_summit
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
# Create .env file
AZURE_ENDPOINT=your_azure_ai_endpoint
AZURE_CREDENTIAL=your_azure_api_key
TAVILY_API_KEY=your_tavily_api_key
```

### Running the Examples

#### 1. Basic Todo Management
```bash
python research_1_todo.py
```

#### 2. File System Context Management
```bash
jupyter notebook research_2a_files.ipynb
```

#### 3. Sub-Agent Delegation
```bash
jupyter notebook research_3_subagents.ipynb
```

#### 4. Human-in-the-Loop Workflows
```bash
python research_4_human_in_loop.py
```

## 🔧 Key Technologies

### Azure AI Foundry Integration

The project leverages Azure AI Foundry for:
- **GPT Model Access**: Using `gpt-5-mini` for fast, cost-effective processing
- **Structured Outputs**: Type-safe responses with Pydantic models
- **Streaming Responses**: Real-time agent communication

```python
model = AzureAIChatCompletionsModel(
    credential=os.getenv("AZURE_CREDENTIAL"),
    endpoint=os.getenv("AZURE_ENDPOINT"),
    model="gpt-5-mini",
)
```

## 🤝 Contributing

This is a research and educational project. Contributions that enhance the learning experience are welcome:

- **Additional Research Areas**: New agent patterns or capabilities
- **Documentation**: Improved explanations and tutorials  
- **Integration Examples**: Additional Azure AI services
- **Performance Optimizations**: Efficiency improvements

## 🔗 Resources

- [LangChain Documentation](https://python.langchain.com/)
- [LangChain Azure Repository](https://github.com/langchain-ai/langchain-azure)
- [Azure AI Foundry](https://azure.microsoft.com/en-us/products/ai-foundry)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [LangGraph Framework](https://langchain-ai.github.io/langgraph/)

---
