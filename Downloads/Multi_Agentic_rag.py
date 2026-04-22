import streamlit as st
import tempfile
import os
import time
from typing import TypedDict, List, Dict, Any

# Core
from pdfminer.high_level import extract_text
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma

# Cloud LLMs
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# LangGraph
from langgraph.graph import StateGraph, END

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Parallel Agentic RAG", layout="wide")
st.title("🏢 Enterprise Parallel Agentic RAG (Cloud-only)")

BASE_URL = st.secrets.get("BASE_URL", "")
API_KEY = st.secrets.get("GENAI_API_KEY", "")

# Different cloud models per agent (as per your list)
ROUTER_MODEL = "azure/genailab-maas-gpt-4o-mini"
RETRIEVER_MODEL = "azure/genailab-maas-gpt-4o-mini"
COMPLIANCE_MODEL = "azure_ai/genailab-maas-Phi-4-reasoning"
RISK_MODEL = "azure_ai/genailab-maas-DeepSeek-R1"
COLLECTOR_MODEL = "azure/genailab-maas-gpt-4o"

EMBED_MODEL = "azure/genailab-maas-text-embedding-3-large"

# ---------------- LLM INIT ----------------
def make_llm(model_name: str, temperature: float = 0.2):
    return ChatOpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        model=model_name,
        temperature=temperature,
        default_headers={"Ocp-Apim-Subscription-Key": API_KEY}
    )

router_llm = make_llm(ROUTER_MODEL, 0.1)
retriever_llm = make_llm(RETRIEVER_MODEL, 0.1)
compliance_llm = make_llm(COMPLIANCE_MODEL, 0.1)
risk_llm = make_llm(RISK_MODEL, 0.1)
collector_llm = make_llm(COLLECTOR_MODEL, 0.2)

embeddings = OpenAIEmbeddings(
    base_url=BASE_URL,
    api_key=API_KEY,
    model=EMBED_MODEL
)

# ---------------- STATE ----------------
class AgentState(TypedDict, total=False):
    query: str
    vectordb: Any

    # router outputs
    events: List[str]

    # retriever outputs
    docs: List[Any]
    context: str

    # parallel agent outputs
    compliance_answer: str
    risk_answer: str
    retrieval_summary: str

    # collector outputs
    final_answer: str
    logs: Dict[str, Any]

# ---------------- UTIL ----------------
def build_vectordb(text: str):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunks = splitter.split_text(text)
    vectordb = Chroma.from_texts(chunks, embedding=embeddings)
    return vectordb

# ---------------- AGENTS ----------------

# 1) ROUTER (Event emitter)
def router_agent(state: AgentState) -> AgentState:
    prompt = f"""
    Classify the query into tasks and return a JSON list of tasks to run in parallel.
    Possible tasks: ["retrieve", "compliance", "risk"]

    Query: {state["query"]}
    Return ONLY JSON list.
    """
    resp = router_llm.invoke(prompt).content

    # naive parse fallback
    tasks = []
    for t in ["retrieve", "compliance", "risk"]:
        if t in resp:
            tasks.append(t)

    if not tasks:
        tasks = ["retrieve"]

    state["events"] = tasks
    state["logs"] = {"router_tasks": tasks, "time": time.ctime()}
    return state

# 2) RETRIEVER (RAG)
def retriever_agent(state: AgentState) -> AgentState:
    docs = state["vectordb"].similarity_search(state["query"], k=6)
    context = "\n".join([d.page_content for d in docs])

    prompt = f"""
    Summarize relevant context for answering:

    {context}
    """
    summary = retriever_llm.invoke(prompt).content

    state["docs"] = docs
    state["context"] = context
    state["retrieval_summary"] = summary
    return state

# 3) COMPLIANCE AGENT
def compliance_agent(state: AgentState) -> AgentState:
    prompt = f"""
    Analyze the query from a compliance perspective.

    Context:
    {state.get("context","")}

    Query: {state["query"]}
    """
    ans = compliance_llm.invoke(prompt).content
    state["compliance_answer"] = ans
    return state

# 4) RISK AGENT
def risk_agent(state: AgentState) -> AgentState:
    prompt = f"""
    Identify risks, violations, and edge cases.

    Context:
    {state.get("context","")}

    Query: {state["query"]}
    """
    ans = risk_llm.invoke(prompt).content
    state["risk_answer"] = ans
    return state

# 5) COLLECTOR (merge + verify)
def collector_agent(state: AgentState) -> AgentState:
    prompt = f"""
    Combine the following into a structured final answer.

    Retrieval:
    {state.get("retrieval_summary","")}

    Compliance:
    {state.get("compliance_answer","")}

    Risk:
    {state.get("risk_answer","")}

    Ensure:
    - grounded in context
    - remove contradictions
    - structured output
    """
    final = collector_llm.invoke(prompt).content
    state["final_answer"] = final
    return state

# ---------------- GRAPH ----------------
def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("router", router_agent)
    graph.add_node("retriever", retriever_agent)
    graph.add_node("compliance", compliance_agent)
    graph.add_node("risk", risk_agent)
    graph.add_node("collector", collector_agent)

    graph.set_entry_point("router")

    # Dynamic fan-out
    graph.add_conditional_edges(
        "router",
        lambda s: s["events"],
        {
            "retrieve": "retriever",
            "compliance": "compliance",
            "risk": "risk"
        }
    )

    # All parallel paths go to collector
    graph.add_edge("retriever", "collector")
    graph.add_edge("compliance", "collector")
    graph.add_edge("risk", "collector")

    graph.set_finish_point("collector")

    return graph.compile()

# ---------------- UI ----------------
uploaded_file = st.file_uploader("Upload Policy PDF", type="pdf")

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        f.write(uploaded_file.read())
        path = f.name

    text = extract_text(path)
    vectordb = build_vectordb(text)
    graph = build_graph()

    query = st.text_input("Ask about policy/compliance/risk")

    if st.button("Run Parallel Agentic RAG"):
        state = {"query": query, "vectordb": vectordb}
        result = graph.invoke(state)

        st.subheader("Final Answer")
        st.write(result["final_answer"])

        st.subheader("Logs")
        st.json(result["logs"])

    os.remove(path)