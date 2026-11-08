import os
import time
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Prefer the modern package; fall back to the old one if needed.
try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

# ── API key comes from the ENVIRONMENT — never hardcode it in the file ──
#   mac/linux:  export GOOGLE_API_KEY="your-new-key"
#   windows:    set GOOGLE_API_KEY=your-new-key
if not os.environ.get("GOOGLE_API_KEY"):
    raise SystemExit(
        "GOOGLE_API_KEY is not set.\n"
        '  mac/linux:  export GOOGLE_API_KEY="your-new-key"\n'
        "  windows:    set GOOGLE_API_KEY=your-new-key"
    )

DATA_DIR = "./data"
CHROMA_DIR = "./chroma_db"


def build_database():
    print("Step 1: Loading PDFs from ./data ...")
    documents = PyPDFDirectoryLoader(DATA_DIR).load()
    if not documents:
        print("ERROR: No PDFs found in ./data")
        return
    print(f"  Loaded {len(documents)} pages.")

    print("Step 2: Splitting into chunks ...")
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(documents)
    # Stable key so the admin panel can list / delete these files later.
    for c in chunks:
        c.metadata["source_file"] = os.path.basename(c.metadata.get("source", "unknown.pdf"))
    print(f"  {len(chunks)} chunks.")

    print("Step 3: Embedding + storing (with auto-retry) ...")
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    vector_db = Chroma(embedding_function=embeddings, persist_directory=CHROMA_DIR)

    batch_size = 15
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        print(f"   -> chunks {i} to {i + len(batch)} ...")
        while True:
            try:
                vector_db.add_documents(batch)
                time.sleep(15)
                break
            except Exception as e:
                msg = str(e).lower()
                if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
                    print("      Rate limit — pausing 45s ...")
                    time.sleep(45)
                else:
                    raise
    print("DONE. Vector DB saved to ./chroma_db")


if __name__ == "__main__":
    build_database()