"""
The chat pipeline: intent routing + history-aware retrieval + grounded generation.

Built on LangChain's own create_history_aware_retriever / create_retrieval_chain
/ create_stuff_documents_chain instead of hand-rolled glue code, with two
additions:

  * The retriever runs an exact/alias/room-code lookup over the structured
    locations (core/location_lookup.py) BEFORE semantic search and pins the
    match to the front. That is what makes "where is BR1024" reliable
    regardless of how well the code happens to embed.

  * Sources are only reported when the answer is genuinely grounded (see ask()):
    chit-chat skips retrieval entirely, and retrieved chunks below
    config.MIN_RELEVANCE_SCORE are discarded.
"""

import datetime
import os
import warnings
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_classic.chains import create_retrieval_chain, create_history_aware_retriever
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_google_genai import ChatGoogleGenerativeAI

from core import config
from core.intent import classify_intent
from core.query_log import log_interaction
from core.location_lookup import find_matching_location

# similarity_search_with_relevance_scores warns (and prints every retrieved
# document) whenever a score is negative, which is normal for off-topic text
# with this embedding model. We handle low scores ourselves via the threshold.
warnings.filterwarnings("ignore", message="Relevance scores must be between 0 and 1")

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
5. If the message is only a greeting, thanks or small talk, just reply naturally and briefly — do not use the fallback message from guideline 4.

Context:
{context}"""

CHITCHAT_SYSTEM_PROMPT = """You are the MMU AI Campus Assistant, a friendly assistant for Multimedia University (MMU) students.
The user's message is small talk: a greeting, thanks, a goodbye, or a question about you.
Reply briefly and warmly, in the same language the user wrote in.
- If asked what you can do: you can answer questions about MMU academic regulations, the academic calendar, scholarships, campus facilities and opening hours, and campus locations.
- Do not state any specific MMU facts, dates or locations in this reply, and do not mention documents or sources.
- Invite them to ask an MMU-related question."""

# Each retrieved chunk is rendered with its source tag before being joined
# into {context} above — so the "ground your answer in the tagged source"
# instruction is something the model can actually follow.
_DOCUMENT_PROMPT = PromptTemplate.from_template(
    "[Source: {source_file}, page {page}]\n{page_content}"
)


@dataclass
class ChatPipeline:
    """The two answer paths; ask() picks one per message."""
    rag: Runnable        # retrieval chain -> {"answer", "context"}
    chitchat: Runnable   # direct LLM reply, no retrieval -> str


def _location_record_to_document(rec):
    from locations import location_to_document  # local import avoids a cycle at module load

    return location_to_document(rec)


def retrieve_documents(vector_db, list_locations_fn, query):
    """
    Hybrid retrieval with a relevance gate: query (str) -> list[Document].

    Semantic hits scoring below config.MIN_RELEVANCE_SCORE are dropped, so an
    off-topic query can return nothing at all. An exact location match (if any)
    is pinned to the front and always kept. Each returned doc carries its score
    in metadata["relevance_score"].
    """
    docs = []
    for doc, score in vector_db.similarity_search_with_relevance_scores(
        query, k=config.RETRIEVER_K
    ):
        if config.GROUNDING_GATE_ENABLED and score < config.MIN_RELEVANCE_SCORE:
            continue
        doc.metadata["relevance_score"] = round(score, 3)
        docs.append(doc)

    match = find_matching_location(query, list_locations_fn())
    if match:
        loc_doc = _location_record_to_document(match)
        loc_doc.metadata["relevance_score"] = 1.0
        docs = [loc_doc] + [d for d in docs if d.metadata.get("loc_id") != match.get("id")]

    # Normalize "page" for the document prompt — PDF loaders set an int,
    # location/other docs may not set it at all.
    for d in docs:
        d.metadata.setdefault("page", "N/A")
        if isinstance(d.metadata.get("page"), int):
            d.metadata["page"] += 1  # 1-indexed for humans
    return docs[: config.RETRIEVER_K]


def build_chat_pipeline(vector_db, list_locations_fn):
    """Build both answer paths around one shared LLM client."""
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
    chitchat_prompt = ChatPromptTemplate.from_messages([
        ("system", CHITCHAT_SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    retriever = RunnableLambda(lambda q: retrieve_documents(vector_db, list_locations_fn, q))
    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_prompt)
    combine_docs_chain = create_stuff_documents_chain(
        llm, answer_prompt, document_prompt=_DOCUMENT_PROMPT
    )
    return ChatPipeline(
        rag=create_retrieval_chain(history_aware_retriever, combine_docs_chain),
        chitchat=chitchat_prompt | llm | StrOutputParser(),
    )


def _source_labels(context_docs):
    """Distinct source names in retrieval (most relevant first) order."""
    labels = [
        doc.metadata.get("source_file")
        or os.path.basename(doc.metadata.get("source", ""))
        or "Unknown Source"
        for doc in context_docs
    ]
    return list(dict.fromkeys(labels))


def _is_no_answer(answer):
    return config.NO_ANSWER_MARKER.lower() in answer.lower()


def ask(pipeline, question, chat_history, log=True):
    """
    Answer one message and decide whether its sources may be shown.

    Returns a dict with:
      answer    str
      context   docs that were given to the model (empty for chit-chat)
      intent    "chitchat" | "knowledge"
      grounded  True only if the answer genuinely rests on retrieved context
      sources   source names to display — [] unless grounded
      log_id    query-log entry id (None if log=False), for 👍/👎 feedback
    """
    intent = classify_intent(question)
    inputs = {"input": question, "chat_history": chat_history}

    if intent == "chitchat":
        response = {"answer": pipeline.chitchat.invoke(inputs), "context": []}
    else:
        response = pipeline.rag.invoke(inputs)

    context = response.get("context", [])
    grounded = bool(context)
    if grounded and config.GROUNDING_GATE_ENABLED and _is_no_answer(response["answer"]):
        grounded = False  # the model itself said it found nothing

    response["intent"] = intent
    response["grounded"] = grounded
    response["sources"] = _source_labels(context) if grounded else []
    response["log_id"] = None
    if log:
        response["log_id"] = log_interaction(
            question=question,
            answer=response["answer"],
            sources=response["sources"],
            timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
            intent=intent,
        )
    return response


def trim_history(chat_history):
    """Keep conversation memory bounded (config.MAX_HISTORY_MESSAGES)."""
    if len(chat_history) > config.MAX_HISTORY_MESSAGES:
        return chat_history[-config.MAX_HISTORY_MESSAGES :]
    return chat_history
