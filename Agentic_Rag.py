import streamlit as st
import tempfile
import os
import time

# LangChain + LangGraph
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI

from langgraph.graph import StateGraph

from pdfminer.high_level import extract_text

# --- CONFIG ---
LOCAL_EMBED = "gte-large"
LOCAL_LLM = "gemma:4b"
CLOUD_MODEL = "azure_ai/genailab-maas-DeepSeek-V3-0324"

# --- INIT MODELS ---
embed_model = OllamaEmbeddings(model=LOCAL_EMBED)
local_llm = Ollama(model=LOCAL_LLM)

cloud_llm = ChatOpenAI(
    base_url=st.secrets["BASE_URL"],
    api_key=st.secrets["GENAI_API_KEY"],
    model=CLOUD_MODEL,
    temperature=0.2
)

# --- STATE DEFINITION ---
class RAGState(dict):
    pass

# --- GUARDRAILS ---
def guardrails(state):
    query = state["query"]
    if "illegal" in query.lower():
        state["final_answer"] = "Blocked due to unsafe query"
        return state
    return state

# --- AGENT 1: RETRIEVER ---
def retriever_agent(state):
    query = state["query"]
    docs = state["vectordb"].similarity_search(query, k=5)

    state["docs"] = docs
    state["context"] = "\n".join([d.page_content for d in docs])
    return state

# --- AGENT 2: LOCAL DRAFT ---
def draft_agent(state):
    prompt = f"""
    Answer ONLY using context. If unsure say I don't know.

    Context:
    {state['context']}

    Question:
    {state['query']}
    """

    draft = local_llm.invoke(prompt)
    state["draft"] = draft
    return state

# --- AGENT 3: CRITIC / REFINER ---
def critic_agent(state):
    refine_prompt = f"""
    Improve the answer for:
    - accuracy
    - clarity
    - remove bias

    Question: {state['query']}
    Draft: {state['draft']}
    """

    final = cloud_llm.invoke(refine_prompt)
    state["final_answer"] = final
    return state

# --- FAIRNESS CHECK ---
def bias_check(state):
    answer = state["final_answer"]
    bias_words = ["always", "never", "all people"]

    flags = [w for w in bias_words if w in answer.lower()]
    state["bias_flags"] = flags
    return state

# --- TRANSPARENCY ---
def logger(state):
    state["log"] = {
        "query": state["query"],
        "num_docs": len(state["docs"]),
        "time": time.ctime()
    }
    return state

# --- GRAPH BUILD ---
def build_graph():

    graph = StateGraph(RAGState)

    graph.add_node("guardrails", guardrails)
    graph.add_node("retriever", retriever_agent)
    graph.add_node("draft", draft_agent)
    graph.add_node("critic", critic_agent)
    graph.add_node("bias", bias_check)
    graph.add_node("logger", logger)

    graph.set_entry_point("guardrails")

    graph.add_edge("guardrails", "retriever")
    graph.add_edge("retriever", "draft")
    graph.add_edge("draft", "critic")
    graph.add_edge("critic", "bias")
    graph.add_edge("bias", "logger")

    graph.set_finish_point("logger")

    return graph.compile()

# --- VECTOR DB ---
def build_vectordb(text):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunks = splitter.split_text(text)

    vectordb = Chroma.from_texts(chunks, embedding=embed_model)
    return vectordb

# --- STREAMLIT UI ---
st.title("🧠 Agentic RAG with Responsible AI")

uploaded_file = st.file_uploader("Upload PDF", type="pdf")

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        f.write(uploaded_file.read())
        path = f.name

    text = extract_text(path)

    vectordb = build_vectordb(text)

    graph = build_graph()

    query = st.text_input("Ask a question")

    if st.button("Run Agentic RAG"):

        state = {
            "query": query,
            "vectordb": vectordb
        }

        result = graph.invoke(state)

        st.subheader("Answer")
        st.write(result["final_answer"])

        st.subheader("Transparency Log")
        st.json(result["log"])

        if result["bias_flags"]:
            st.warning(f"Bias detected: {result['bias_flags']}")

    os.remove(path)
