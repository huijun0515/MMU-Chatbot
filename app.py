import streamlit as st
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

# Shared database handle (used by both the assistant and the admin panel)
from vector_store import get_vector_db

# Extra pages
from cgpa_calculator import render_cgpa_calculator
from admin import render_admin_page
from announcements import render_announcements_page
from source_explorer import render_source_explorer_page
from locations import render_directory_page, location_card_from_context


# Page Configuration 
st.set_page_config(
    page_title="MMU Campus Assistant",
    page_icon="🎓",
    layout="wide"
)


# --- ADD THIS ENTIRE CSS BLOCK ---
sidebar_css = """
<style>
    /* Dark Blue Sidebar Background */
    [data-testid="stSidebar"] {
        background-color: #002B7F;
    }
    
    /* Force text color to white inside the sidebar */
    [data-testid="stSidebar"] * {
        color: #FFFFFF;
    }
    
    /* Header Styling */
    .sidebar-header {
        text-align: center;
        margin-bottom: 25px;
        margin-top: -20px;
    }
    .sidebar-icon {
        font-size: 3.5rem;
        margin-bottom: 5px;
    }
    .sidebar-header h2 {
        font-size: 1.3rem;
        font-weight: 700;
        margin: 0;
        padding: 0;
    }
    .sidebar-header p {
        font-size: 0.75rem;
        color: #A0B2D8;
        margin-top: 2px;
    }

    /* Features List Styling */
    .features-title {
        font-size: 0.65rem;
        color: #7B95D1;
        letter-spacing: 1.5px;
        margin-top: 30px;
        margin-bottom: 15px;
        font-weight: 600;
    }
    .feature-item {
        font-size: 0.85rem;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 10px;
        color: #E2E8F0;
    }

    /* Footer Styling */
    .sidebar-footer {
        text-align: center;
        font-size: 0.65rem;
        color: #7B95D1;
        margin-top: 40px;
    }

    /* --- BUTTON STYLING TRICKS --- */
    /* 1. Primary Buttons (The RED Active Tab) */
    [data-testid="stSidebar"] button[kind="primary"] {
        background-color: #E61932 !important; 
        border: none !important;
        color: white !important;
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] button[kind="primary"] p {
        color: white !important;
    }

    /* 2. Secondary Buttons (The WHITE 'Clear Chat' Button) */
    [data-testid="stSidebar"] button[kind="secondary"] {
        background-color: #F8FAFC !important;
        color: #1E293B !important;
        border: 1px solid #CBD5E1 !important;
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] button[kind="secondary"] p {
        color: #1E293B !important;
    }

    /* 3. Secondary Buttons INSIDE Columns (The DARK BLUE Inactive Tab) */
    [data-testid="column"] button[kind="secondary"] {
        background-color: #12409A !important;
        color: white !important;
        border: none !important;
    }
    [data-testid="column"] button[kind="secondary"] p {
        color: white !important;
    }
</style>
"""
st.markdown(sidebar_css, unsafe_allow_html=True)


# 2. API Key 
os.environ["GOOGLE_API_KEY"] = st.secrets["GEMINI_API_KEY"]


# 3. Load AI Brain 
@st.cache_resource
def load_ai_brain():
    vector_db = get_vector_db()   # same shared handle the admin panel writes to
    retriever = vector_db.as_retriever(search_kwargs={"k": 3})
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)

    contextualize_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Given a chat history and the latest user question, "
         "rewrite it as a standalone question that makes sense without the history. "
         "Do NOT answer it. If it is already standalone, return it unchanged."),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    answer_prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the official MMU AI Campus Assistant.
Your goal is to provide clear, concise, and helpful answers based on all PDFs provided.

GUIDELINES:
1. If the answer involves dates or lists, use bullet points.
2. Always mention which document you found the information in.
3. If the question is about a location, describe it relative to other landmarks.
4. If you cannot find the answer, say: "I'm sorry, I couldn't find that specific information in the current data. Please contact the Student Service Centre email ssc@mmu.edu.my for further assistance."

Context:
{context}"""),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    def retrieve_with_history(data: dict) -> dict:
        chat_history = data.get("chat_history", [])
        question = data["input"]
        if chat_history:
            rewrite_chain = contextualize_prompt | llm | StrOutputParser()
            standalone = rewrite_chain.invoke({
                "input": question,
                "chat_history": chat_history,
            })
        else:
            standalone = question
        docs = retriever.invoke(str(standalone))
        return {
            "input": question,
            "chat_history": chat_history,
            "context": docs,
        }

    def answer_from_context(data: dict) -> dict:
        context_text = "\n\n".join(doc.page_content for doc in data["context"])
        filled_prompt = answer_prompt.invoke({
            "input": data["input"],
            "chat_history": data["chat_history"],
            "context": context_text,
        })
        answer = llm.invoke(filled_prompt)
        return {
            "answer": answer.content,
            "context": data["context"],
        }

    full_chain = RunnablePassthrough() | retrieve_with_history | answer_from_context
    return full_chain


qa_system = load_ai_brain()


# 4. Sidebar Navigation 

if "current_page" not in st.session_state:
    st.session_state.current_page = "Assistant"

# Hidden admin entry point — there is NO button in the student-facing UI.
# Open the admin panel by adding ?admin=1 to the app URL, e.g.
#   local:     http://localhost:8501/?admin=1
#   deployed:  https://your-app.streamlit.app/?admin=1
# It is still protected by the password gate inside the page itself.
if "admin" in st.query_params:
    st.session_state.current_page = "Admin"
    st.query_params.clear()   # consume the flag so normal nav still works

with st.sidebar:
    st.markdown("""
    <div class="sidebar-header">
        <div class="sidebar-icon">🏛️</div>
        <h2>MMU Student Hub</h2>
        <p>Multimedia University</p>
    </div>
    """, unsafe_allow_html=True)

    nav_items = [
        ("Assistant", "🤖 Assistant"),
        ("Calculator", "📊 Calculator"),
        ("Announcements", "📢 Events"),
        ("Sources", "📚 Sources"),
        ("Places", "📍 Places"),
    ]
    for r in range(0, len(nav_items), 2):
        nav_cols = st.columns(2)
        for col, (key, label) in zip(nav_cols, nav_items[r:r + 2]):
            with col:
                if st.button(
                    label,
                    use_container_width=True,
                    type="primary" if st.session_state.current_page == key else "secondary",
                    key=f"nav_{key}",
                ):
                    st.session_state.current_page = key
                    st.rerun()

    st.markdown("<div class='features-title'>FEATURES</div>", unsafe_allow_html=True)
    st.markdown("""
    <div class='feature-item'>📍 Campus Navigation</div>
    <div class='feature-item'>📖 Academic Regulations</div>
    <div class='feature-item'>📞 Staff & Faculty Info</div>
    <div class='feature-item'>📊 CGPA Calculator</div>
    """, unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)

    if st.session_state.current_page == "Assistant":
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.messages = [{"role": "assistant", "content": "Hello! I am the MMU Campus Assistant. Ask me anything!"}]
            st.session_state.chat_history = []
            st.rerun()

    st.markdown("<div class='sidebar-footer'>FYP Prototype · Developed by Goh Hui Jun</div>", unsafe_allow_html=True)




#  5. Route to correct page 

# ════════════════════════════════════
#  PAGE A: Campus Assistant Chatbot
# ════════════════════════════════════
if st.session_state.current_page == "Assistant":

    st.markdown("<h1 style='text-align: center; color: #0033A0;'>🎓 MMU Campus Assistant</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Your 24/7 intelligent guide to Multimedia University.</p>", unsafe_allow_html=True)
    st.markdown("---")

    # Chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hello! I am the MMU Campus Assistant Bot. You can ask me anything!"}
        ]

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Quick suggestion buttons
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

    # Helper: show a location's photo + details under an answer (feature #8)
    def render_location_card(card):
        if not card:
            return
        header = f"📍 {card.get('name','')}"
        sub = " · ".join([x for x in [card.get("building", ""), card.get("floor", "")] if x])
        if card.get("image_path"):
            st.image(card["image_path"],
                     caption=f"{header}" + (f" — {sub}" if sub else ""),
                     use_container_width=True)
        elif sub:
            st.info(f"{header} — {sub}")

    # Display messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("location"):
                render_location_card(message["location"])
            if "sources" in message and message["sources"]:
                with st.expander("📚 View Sources"):
                    for source in message["sources"]:
                        st.caption(f"📄 {source}")

    # AI Logic
    prompt = st.chat_input("Type your question here...")
    if "quick_query" in st.session_state:
        prompt = st.session_state.quick_query
        del st.session_state.quick_query

    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("🧠 Thinking for the answer..."):
                try:
                    response = qa_system.invoke({
                        "input": prompt,
                        "chat_history": st.session_state.chat_history,
                    })
                    ai_answer = response["answer"]

                    sources = set()
                    if "context" in response:
                        for doc in response["context"]:
                            label = doc.metadata.get("source_file") or os.path.basename(
                                doc.metadata.get("source", "Unknown Source"))
                            sources.add(label)

                    st.markdown(ai_answer)

                    # Show a location photo/details if the answer used one (#8)
                    location_card = location_card_from_context(response.get("context", []))
                    render_location_card(location_card)

                    if sources:
                        with st.expander("📚 View Sources"):
                            for source in sources:
                                st.caption(f"📄 {source}")

                    # Update memory
                    st.session_state.chat_history.append(HumanMessage(content=prompt))
                    st.session_state.chat_history.append(AIMessage(content=ai_answer))
                    if len(st.session_state.chat_history) > 20:
                        st.session_state.chat_history = st.session_state.chat_history[-20:]

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": ai_answer,
                        "sources": list(sources),
                        "location": location_card,
                    })

                except Exception as e:
                    error_message = f"❌ Oops, something went wrong: {e}"
                    st.markdown(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})



elif st.session_state.current_page == "Calculator":
    render_cgpa_calculator()


# ════════════════════════════════════
#  PAGE C: Announcements / Events
# ════════════════════════════════════
elif st.session_state.current_page == "Announcements":
    render_announcements_page()


# ════════════════════════════════════
#  PAGE D: Source Explorer
# ════════════════════════════════════
elif st.session_state.current_page == "Sources":
    render_source_explorer_page()


# ════════════════════════════════════
#  PAGE E: Campus Directory (Places)
# ════════════════════════════════════
elif st.session_state.current_page == "Places":
    render_directory_page()


# ════════════════════════════════════
#  PAGE F: Admin — Console
# ════════════════════════════════════
elif st.session_state.current_page == "Admin":
    render_admin_page()