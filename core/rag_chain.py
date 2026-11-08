"""
The chat pipeline: history-aware retrieval + grounded generation.

Built on LangChain's own create_history_aware_retriever / create_retrieval_chain
/ create_stuff_documents_chain instead of hand-rolled glue code, with one
addition spliced into the retriever: an exact/alias/room-code lookup over the
structured locations (core/location_lookup.py) runs BEFORE semantic search and
is prepended to the vector hits. That is what makes "where is BR1024" reliable
regardless of how well the code happens to embed.
"""

import datetime

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_classic.chains import create_retrieval_chain, create_history_aware_retriever
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_google_genai import ChatGoogleGenerativeAI

from core import config
from core.query_log import log_interaction
from core.location_lookup import find_matching_location

CONTEXTUALIZE_SYSTEM_PROMPT = (
    "Given a chat history and the latest user question, "
    "rewrite it as a standalone question that makes sense without the history. "
    "Do NOT answer it. If it is already standalone, return it unchanged."
)

ANSWER_SYSTEM_PROMPT = """You are the official MMU AI Campus Assistant.
Your goal is to provide clear, concise, and helpful answers based on the official documents and campus directory provided below.

GUIDELINES:
1. If the answer involves dates or lists, use bullet points.
2. Each context passage below is tagged with its source document — ground your answer only in these passages, and you may refer to the tagged source when useful.
3. If the question is about a location, describe it relative to other landmarks.
4. If you cannot find the answer, say: "I'm sorry, I couldn't find that specific information in the current data. Please contact the Student Service Centre email ssc@mmu.edu.my for further assistance."

Context:
{context}"""

# Each retrieved chunk is rendered with its source tag before being joined
# into {context} above — so the "ground your answer in the tagged source"
# instruction is something the model can actually follow.
_DOCUMENT_PROMPT = PromptTemplate.from_template(
    "[Source: {source_file}, page {page}]\n{page_content}"
)


def _location_record_to_document(rec):
    from locations import location_to_document  # local import avoids a cycle at module load

    return location_to_document(rec)


def _make_hybrid_retriever(vector_db, list_locations_fn):
    """A Runnable: query (str) -> list[Document]. Semantic search, with an
    exact location match (if any) pinned to the front of the results."""
    base_retriever = vector_db.as_retriever(search_kwargs={"k": config.RETRIEVER_K})

    def _retrieve(query):
        docs = base_retriever.invoke(query)
        match = find_matching_location(query, list_locations_fn())
        if match:
            loc_doc = _location_record_to_document(match)
            docs = [loc_doc] + [
                d for d in docs if d.metadata.get("loc_id") != match.get("id")
            ]
        # Normalize "page" for the document prompt — PDF loaders set an int,
        # location/other docs may not set it at all.
        for d in docs:
            d.metadata.setdefault("page", "N/A")
            if isinstance(d.metadata.get("page"), int):
                d.metadata["page"] = d.metadata["page"] + 1  # 1-indexed for humans
        return docs[: config.RETRIEVER_K]

    return RunnableLambda(_retrieve)


def build_chat_chain(vector_db, list_locations_fn):
    """Return a Runnable with .invoke({"input": str, "chat_history": [...]})
    -> {"answer": str, "context": list[Document]}."""
    api_key = config.get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set in st.secrets or the environment. "
            "Generation always uses Gemini, even with the local embedding backend."
        )
    llm = ChatGoogleGenerativeAI(
        model=config.LLM_MODEL, temperature=config.GENERATION_TEMPERATURE, google_api_key=api_key
    )

    contextualize_prompt = ChatPromptTemplate.from_messages([
        ("system", CONTEXTUALIZE_SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    answer_prompt = ChatPromptTemplate.from_messages([
        ("system", ANSWER_SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    retriever = _make_hybrid_retriever(vector_db, list_locations_fn)
    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_prompt)
    combine_docs_chain = create_stuff_documents_chain(
        llm, answer_prompt, document_prompt=_DOCUMENT_PROMPT
    )
    return create_retrieval_chain(history_aware_retriever, combine_docs_chain)


def ask(chat_chain, question, chat_history, log=True):
    """Invoke the chain and optionally log the interaction.

    Returns the raw response dict (with "answer" and "context") plus a
    "log_id" key (None if log=False or logging failed) so callers can attach
    feedback (👍/👎) to the right query-log entry without logging twice.
    """
    response = chat_chain.invoke({"input": question, "chat_history": chat_history})
    response["log_id"] = None
    if log:
        sources = sorted({
            doc.metadata.get("source_file") or "Unknown Source"
            for doc in response.get("context", [])
        })
        response["log_id"] = log_interaction(
            question=question,
            answer=response["answer"],
            sources=sources,
            timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        )
    return response


def trim_history(chat_history):
    """Keep conversation memory bounded (config.MAX_HISTORY_MESSAGES)."""
    if len(chat_history) > config.MAX_HISTORY_MESSAGES:
        return chat_history[-config.MAX_HISTORY_MESSAGES :]
    return chat_history
