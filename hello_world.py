from langgraph.graph import StateGraph, MessagesState, START, END

def mock_llm(state: MessagesState):
    return {"messages": [{"role": "ai", "content": "hello world"}]}


def main():
    graph = StateGraph(MessagesState)
    graph.add_node(mock_llm)
    graph.add_edge(START, "mock_llm")
    graph.add_edge("mock_llm", END)
    graph = graph.compile()

    print(graph.get_graph().draw_ascii())

    graph.invoke({"messages": [{"role": "user", "content": "hi!"}]})


if __name__ == "__main__":
    main()