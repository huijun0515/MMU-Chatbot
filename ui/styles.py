"""Global CSS for the app shell (sidebar theme, nav button styling)."""

SIDEBAR_CSS = """
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
