import streamlit as st
import os
import tempfile
import hashlib
import time

# --- Core Imports ---
from pdfminer.high_level import extract_text
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Local Models (Ollama)
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.llms import Ollama

# Cloud LLM
from langchain_openai import ChatOpenAI

# Vector Store
from langchain_community.vectorstores import Chroma

# --- CONFIG ---
st.set_page_config(page_title="Responsible Hybrid RAG", layout="wide")
st.title("📄 Responsible AI: Hybrid RAG System")

BASE_URL = st.secrets.get("BASE_URL", "")
GENAI_API_KEY = st.secrets.get("GENAI_API_KEY", "")

# Models
LOCAL_EMBED_MODEL = "gte-large"
LOCAL_LLM_MODEL = "gemma:4b"
CLOUD_MODEL = "azure_ai/genailab-maas-DeepSeek-V3-0324"

# --- MODEL INIT ---
embed_model = OllamaEmbeddings(model=LOCAL_EMBED_MODEL)
local_llm = Ollama(model=LOCAL_LLM_MODEL)

cloud_llm = ChatOpenAI(
    base_url=BASE_URL,
    api_key=GENAI_API_KEY,
    model=CLOUD_MODEL,
    temperature=0.2
)

# --- UTILITIES ---

def hash_file(file_bytes):
    return hashlib.md5(file_bytes).hexdigest()

# --- GUARDRAILS (Ethics + Safety) ---
def guardrails_check(query):
    blocked_keywords = ["hate", "violence", "illegal"]
    for word in blocked_keywords:
        if word in query.lower():
            return False, f"Query blocked due to unsafe content: {word}"
    return True, ""

# --- FAIRNESS / BIAS CHECK ---
def bias_check(text):
    bias_words = ["always", "never", "all people"]
    flags = [w for w in bias_words if w in text.lower()]
    return flags

# --- TRANSPARENCY LOGGING ---
def log_interaction(query, route, latency):
    return {
        "query": query,
        "model_used": route,
        "latency_sec": round(latency, 2),
        "timestamp": time.ctime()
    }

# --- ACCURACY: Confidence Score ---
def compute_confidence(docs):
    return min(1.0, len(docs) / 5)

# --- ROUTER ---
def route_query(query):
    if len(query) < 60:
        return "local"
    return "cloud"

# --- RAG PIPELINE ---
@st.cache_resource
def build_vector_db(text):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=200
    )
    chunks = splitter.split_text(text)

    vectordb = Chroma.from_texts(
        chunks,
        embedding=embed_model
    )
    return vectordb

def generate_response(query, vectordb):

    # Guardrails
    safe, msg = guardrails_check(query)
    if not safe:
        return msg, [], {}

    start_time = time.time()

    retriever = vectordb.as_retriever(search_kwargs={"k": 5})
    docs = retriever.get_relevant_documents(query)
    context = "\n".join([d.page_content for d in docs])

    prompt = f"""
    Answer ONLY from the context below.
    If unsure, say "I don't know".

    Context:
    {context}

    Question:
    {query}
    """

    route = route_query(query)

    # Local draft
    if route == "local":
        answer = local_llm.invoke(prompt)
    else:
        draft = local_llm.invoke(prompt)

        refine_prompt = f"""
        Improve accuracy, remove bias, and structure clearly.

        Question: {query}
        Draft: {draft}
        """

        answer = cloud_llm.invoke(refine_prompt)

    latency = time.time() - start_time

    # Transparency log
    log = log_interaction(query, route, latency)

    # Bias detection
    bias_flags = bias_check(answer)

    # Confidence
    confidence = compute_confidence(docs)

    metadata = {
        "log": log,
        "bias_flags": bias_flags,
        "confidence": confidence
    }

    return answer, docs, metadata

# --- UI ---
uploaded_file = st.file_uploader("Upload PDF", type="pdf")

if uploaded_file:
    file_bytes = uploaded_file.read()
    file_hash = hash_file(file_bytes)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
        temp_file.write(file_bytes)
        temp_path = temp_file.name

    raw_text = extract_text(temp_path)

    if not raw_text.strip():
        st.error("No text found (scanned PDF?)")
        st.stop()

    vectordb = build_vector_db(raw_text)

    query = st.text_input("Ask something about the document")

    if st.button("Run RAG") and query:
        answer, docs, meta = generate_response(query, vectordb)

        st.subheader("📌 Answer")
        st.write(answer)

        # --- Transparency ---
        st.subheader("🔍 Transparency")
        st.json(meta["log"])

        # --- Accuracy ---
        st.subheader("📊 Confidence Score")
        st.write(meta["confidence"])

        # --- Fairness ---
        if meta["bias_flags"]:
            st.warning(f"Potential bias detected: {meta['bias_flags']}")

        # --- Source Attribution ---
        with st.expander("📚 Source Chunks"):
            for i, d in enumerate(docs):
                st.write(f"{i+1}: {d.page_content[:300]}...")

    os.remove(temp_path)