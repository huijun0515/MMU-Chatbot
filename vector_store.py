"""
Shared vector-store access for the whole app.

Both the chatbot (app.py) and the admin panel (admin.py) import from here,
so they use the SAME cached database handle. That is what lets a freshly
uploaded PDF show up in the assistant's answers without rebuilding anything.
"""

import streamlit as st
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Prefer the modern package; fall back to the old one if it isn't installed yet.
# To silence the deprecation warning entirely:  pip install langchain-chroma
try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

CHROMA_DIR = "./chroma_db"
DATA_DIR = "./data"
EMBED_MODEL = "models/gemini-embedding-001"


@st.cache_resource
def get_embeddings():
    """One embeddings client, reused everywhere."""
    return GoogleGenerativeAIEmbeddings(model=EMBED_MODEL)


@st.cache_resource
def get_vector_db():
    """
    One shared Chroma handle pointing at ./chroma_db.

    Because this is @st.cache_resource, every part of the app gets the exact
    same object. When admin.py adds documents to it, the assistant's retriever
    (built on this same object) sees them immediately.
    """
    return Chroma(persist_directory=CHROMA_DIR, embedding_function=get_embeddings())