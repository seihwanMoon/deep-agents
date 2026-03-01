from typing import TypedDict, Annotated
import operator

from langchain_core.messages import HumanMessage, BaseMessage, AIMessage
from langgraph.graph import StateGraph, END


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]


def build_local_echo_graph():
    def agent_node(state: AgentState):
        last = state["messages"][-1]
        content = getattr(last, "content", "")
        return {"messages": [AIMessage(content=f"[deepagents-backend] {content}")]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    return graph.compile()


def build_initial_state(message: str):
    return {"messages": [HumanMessage(content=message)]}
