🔹 CONFIG
Define different models per agent
👉 shows specialized intelligence, not generic LLM usage
🔹 make_llm()

Creates reusable cloud LLM instances
👉 avoids repetition
👉 improves scalability

🔹 AgentState

Shared memory between agents
Stores:

query
events
intermediate outputs
👉 enables agent communication
🔹 Router Agent
tasks = ["retrieve", "compliance", "risk"]

👉 Converts query → parallel tasks
👉 This is your event dispatcher

🔹 Conditional Edges
graph.add_conditional_edges(...)

👉 Core of parallel execution

One input → multiple agents
dynamic branching
🔹 Retriever Agent
similarity_search()

👉 Ensures:

grounding
accuracy
🔹 Compliance Agent

👉 Uses Phi-4 reasoning model
👉 Focus: rules, governance

🔹 Risk Agent

👉 Uses DeepSeek-R1
👉 Focus: edge cases, failures

🔹 Collector Agent

👉 Most important

Combines:

retrieval
compliance
risk

Ensures:

no contradiction
structured output
accuracy
🔹 Graph Edges
retriever → collector
compliance → collector
risk → collector

👉 Fan-out → Fan-in pattern:wq!
