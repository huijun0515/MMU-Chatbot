import streamlit as st
import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import Chroma
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import PromptTemplate


# 1. Page Configuration
st.set_page_config(page_title="MMU Campus Assistant", page_icon="🎓", layout="centered")

# 2. Get API Key safely
os.environ["GOOGLE_API_KEY"] = st.secrets["GEMINI_API_KEY"]

# 3. Load the AI Brain (Modern 2026 Version)
@st.cache_resource
def load_ai_brain():
    # Load the embedding model and the database
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
    
    # Clean, simple LLM call using the modern 1.5 model (No translation flags needed!)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)
    
    # Put everything into ONE single text template so LangChain doesn't get confused
    template = """You are the official MMU AI Campus Assistant. 
    Your goal is to provide clear, concise, and helpful answers based on all pdf provided.

    GUIDELINES:
    1. If the answer involves dates or lists, use bullet points to make it easy to read.
    2. Always mention which document you found the information in (e.g., 'According to the 2026 Academic Calendar...').
    3. If the question is about a location, try to describe where it is in relation to other landmarks.
    4. If you cannot find the answer in the context, say: "I'm sorry, I couldn't find that specific information in the current MMU handbooks. Please contact the Student Service Centre for further assistance."

    Context:
    {context}

    Question: {input}

    Answer:"""
    
    prompt_template = PromptTemplate.from_template(template)
    
    # Combine the AI, the prompt, and the database together
    document_chain = create_stuff_documents_chain(llm, prompt_template)
    retrieval_chain = create_retrieval_chain(
        vector_db.as_retriever(search_kwargs={"k": 3}), 
        document_chain
    )
    return retrieval_chain

qa_system = load_ai_brain()

# 4. Sidebar 
with st.sidebar:
    st.title("🏛️ MMU Student Hub")
    st.info("Welcome to the official MMU student Assistant. I can help you navigate MMU Cyberjaya and Melaka, understand academic rules, and find campus facilities.")
    st.markdown("---")
    st.markdown("**Core Capabilities:**")
    st.markdown("- 📍 Campus Navigation")
    st.markdown("- 📖 Academic Regulations")
    st.markdown("- 📞 Staff & Faculty Info")
    st.caption("FYP Prototype | Developed by Goh Hui Jun")

# 5. UI Branding
st.markdown("<h1 style='text-align: center; color: #0033A0;'>🎓 MMU Campus Assistant</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>Your 24/7 intelligent guide to Multimedia University.</p>", unsafe_allow_html=True)
st.markdown("---")

# 6. Chat History
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! I am the MMU Campus Assistant. I have finished reading the student handbooks. Ask me anything!"}
    ]

# 7. Quick Suggestion Buttons
st.write("**Suggested Queries:**")
col1, col2, col3, col4 = st.columns(4)

def set_query(query):
    st.session_state.quick_query = query

with col1:
    st.button("📍 Find Lecture Hall", on_click=set_query, args=("Where is the nearest lecture hall?",), use_container_width=True)
with col2:
    st.button("📅 Exam Rules", on_click=set_query, args=("What are the rules for final exams?",), use_container_width=True)
with col3:
    st.button("💰 Finance Office", on_click=set_query, args=("Where is the finance office?",), use_container_width=True)
with col4:
    st.button("📚 Library Hours", on_click=set_query, args=("What time does the library open?",), use_container_width=True)

# 8. Display Messages 
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        # Print the main text
        st.markdown(message["content"])
        
        # If this message has sources, draw the dropdown box!
        if "sources" in message and message["sources"]:
            with st.expander("📚 View Sources"):
                for source in message["sources"]:
                    st.caption(f"📄 {source}")

# 9. AI Logic
prompt = st.chat_input("Type your question here...")
if "quick_query" in st.session_state:
    prompt = st.session_state.quick_query
    del st.session_state.quick_query

if prompt:
    # Show user question
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Show AI response
    with st.chat_message("assistant"):
        
        # 🌟 THE NEW SPINNING ANIMATION 🌟
        with st.spinner("🧠 Thinking for the answer..."):
            try:
                # 1. Ask the AI for the answer
                response = qa_system.invoke({"input": prompt})
                ai_answer = response["answer"]
                
                # 2. Extract the Source PDF names
                sources = set()
                if "context" in response:
                    for doc in response["context"]:
                        file_path = doc.metadata.get("source", "Unknown Source")
                        file_name = os.path.basename(file_path)
                        sources.add(file_name)
                
                st.markdown(ai_answer)

                if sources:
                    with st.expander("📚 View Sources"):
                        for source in sources:
                            st.caption(f"📄 {source}")
                        
                # 5. Save them separately into the chat history
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": ai_answer,
                    "sources": list(sources) # Save as a list for the expander
                })
                
                # 3. Format the final output
                full_response = ai_answer
                if sources:
                    source_list = ", ".join(sources)
                    full_response += f"\n\n---\n**📚 Sources:** {source_list}"

            except Exception as e:
                error_message = f"❌ Oops, something went wrong: {e}"
                st.markdown(error_message)
                st.session_state.messages.append({"role": "assistant", "content": error_message})
        