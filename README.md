                         ┌────────────────────────────┐
                         │        User Query          │
                         └────────────┬───────────────┘
                                      │
                                      ▼
                     ┌────────────────────────────────┐
                     │   🛡️ Guardrails Layer (Ethics) │
                     │ - Input filtering              │
                     │ - Unsafe keyword blocking      │
                     └────────────┬───────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────────────┐
                    │ ⚖️ Query Router (Accountability) │
                    │ - Local vs Cloud decision        │
                    │ - Rule-based / logic routing     │
                    └────────────┬─────────────┬───────┘
                                 │             │
                                 ▼             ▼
                ┌──────────────────────┐   ┌────────────────────────┐
                │ Local Path (SLM)     │   │ Cloud Path (LLM)       │
                │ Gemma / Llama        │   │ GPT-4o / DeepSeek      │
                └──────────┬───────────┘   └──────────┬─────────────┘
                           │                          │
                           └──────────┬───────────────┘
                                      ▼
                     ┌────────────────────────────────┐
                     │ 📚 Retrieval Layer (Accuracy)  │
                     │ - Chroma Vector DB             │
                     │ - Local Embeddings (GTE)       │
                     │ - Top-K relevant chunks        │
                     └────────────┬───────────────────┘
                                  │
                                  ▼
                     ┌────────────────────────────────┐
                     │ 🧠 Generation Layer             │
                     │ - Context-grounded response     │
                     │ - “I don’t know” fallback      │
                     └────────────┬───────────────────┘
                                  │
                                  ▼
        ┌─────────────────────────────────────────────────────────┐
        │ 🔍 Transparency & Accountability Layer                  │
        │ - Model used (local/cloud)                             │
        │ - Latency tracking                                     │
        │ - Query logs                                           │
        │ - Source chunks displayed                              │
        └────────────┬────────────────────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │ ⚖️ Fairness Layer                                       │
        │ - Bias keyword detection                                │
        │ - Flags potentially biased outputs                      │
        └────────────┬────────────────────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │ 📊 Accuracy Layer                                       │
        │ - Confidence score (based on retrieved docs)            │
        │ - Grounded answers (RAG)                                │
        └────────────┬────────────────────────────────────────────┘
                     │
                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │ ⚡ Scalability Layer                                    │
        │ - Caching (Streamlit cache)                             │
        │ - Modular pipeline                                      │
        │ - Hybrid compute (Local + Cloud)                        │
        └────────────┬────────────────────────────────────────────┘
                     │
                     ▼
               ┌───────────────┐
               │ Final Answer  │
               └───────────────┘
