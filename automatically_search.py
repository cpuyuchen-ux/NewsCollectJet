import datetime
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. 頁面配置與自訂 CSS 樣式
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="彰化家扶輿情自動檢索與報表生成系統", 
    page_icon="📰", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化 Session State
if "api_count_today" not in st.session_state:
    st.session_state["api_count_today"] = 0
if "last_api_date" not in st.session_state:
    st.session_state["last_api_date"] = datetime.date.today()
if "search_history" not in st.session_state:
    st.session_state["search_history"] = []

if st.session_state["last_api_date"] != datetime.date.today():
    st.session_state["api_count_today"] = 0
    st.session_state["last_api_date"] = datetime.date.today()

# 注入自訂 CSS
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1F2937; margin-bottom: 0.2rem; }
    .sub-header { color: #6B7280; font-size: 1.0rem; margin-bottom: 0.8rem; }
    .warning-bar {
        background-color: #FEF2F2;
        border-left: 5px solid #EF4444;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        margin-bottom: 1.5rem;
    }
    .warning-text { color: #DC2626; font-weight: 700; font-size: 0.95rem; margin: 0; }
    .search-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #E5E7EB;
        margin-bottom: 1.5rem;
    }
    [data-testid="stSidebar"] { background-color: #f1f5f9; border-right: 1px solid #E2E8F0; }
    div.stButton > button:first-child {
        background: linear-gradient(90deg, #2563EB, #1D4ED8);
        color: white; border: none; padding: 0.6rem 1.2rem;
        font-weight: 600; border-radius: 8px; transition: all 0.3s ease;
    }
    div.stButton > button:first-child:hover {
        background: linear-gradient(90deg, #1D4ED8, #1E40AF);
        transform: translateY(-1px);
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 2. 標題與警示橫幅區塊
# ---------------------------------------------------------------------------
st.markdown('<div class="main-header">📰 彰化家扶中心輿情自動檢索與報表生成系統</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">自動整合 Google News 即時新聞，並透過 Gemini AI 自動進行年份對齊與格式化</div>', unsafe_allow_html=True)

st.markdown("""
<div class="warning-bar">
    <p class="warning-text">※此系統為個人自主開發，請勿用做非法行為😈</p>
    <p class="warning-text">※檢索資料庫為「彰化家扶」常見出報媒體，資料庫將不定期更新👀</p>
    <p class="warning-text">※此系統供同工免費使用，惟開發者仍保有此系統所有權🔧</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 3. 側邊欄與資料庫讀取
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ 系統核心設定")

sidebar_option = st.sidebar.selectbox(
    "請選擇功能模組：",
    ["主控台 / 檢索系統", "系統簡介", "系統須知", "系統管理員"]
)

api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("🔑 輸入 Gemini API Key:", type="password", help="請輸入您的 Gemini API Key")

st.sidebar.markdown("---")

db_file_path = "database.csv"
media_type_map = {}

if os.path.exists(db_file_path):
    try:
        db_df = pd.read_csv(db_file_path, encoding='utf-8').dropna(how='all')
        st.sidebar.success("✅ database.csv 已連線")
        if len(db_df.columns) >= 2:
            media_col = db_df.columns[0]
            type_col = db_df.columns[1]
            media_type_map = dict(zip(db_df[media_col].astype(str).str.strip(), db_df[type_col].astype(str).str.strip()))
    except Exception as e:
        st.sidebar.error(f"❌ 讀取 database.csv 失敗: {e}")

# ---------------------------------------------------------------------------
# 4. 功能模組內容
# ---------------------------------------------------------------------------
    **彰化家扶中心輿情自動檢索與報表生成系統** 旨在幫助同工快速彙整網路媒體報導。
    
    * **即時檢索**：自動爬取 Google News 最新相關新聞。
    * **AI 結構化整理**：運用 Gemini AI 自動識別新聞標題、發布年份、記者姓名、對照媒體分類（三大報/非三大報等）並進行資料淨化。
    * **一鍵報表**：自動產出包含服務處、主責查詢同工、媒體分類與超連結的標準化 Excel 檔案，提升行政與輿情整理效率。
    * **模組化減速**：批次發送檢索請求，避免觸發 Google反爬蟲機制（Anti-Sraping）。
    * **本地備用演算法防爆**：優先使用 Gemini 2.5 Flash 進行精準解析；若 API 限流則自動啟動「本地防爆演算法」，保障 100% 順利產出。
    """)

elif sidebar_option == "系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.warning("""
    1. **遵守使用規範**：本系統僅供彰化家扶內部輿情檢索使用，嚴禁用於商業爬蟲、網路攻擊或任何非法用途。
    2. **API 額度雙保險機制**：系統採用 Gemini 1.5 Flash 模型，若仍遇到 429 配額額滿，會自動無縫轉入「本地純文字演算法」，確保資料不遺漏！
    3. **資料準確性**：AI自動解析結果僅供參考，匯出報表後建議人工進行二次核對，尤其檢核奧丁丁新聞、PChome新聞、蕃新聞、奇摩新聞等4家媒體，確認有無遺漏。
    4. **中心PDF檔留存**：報表生成後，請將每一篇報導儲存成PDF檔，放置於中心查報資料夾備查。
    5. **人工調整格式**：報表生成後，請配合將資料貼入會「2026年單位季報_媒體統計格式」之excel檔，並視情況補充記者姓名。
    6. **非網路新聞補充**：本系統僅能抓取網路電子新聞，紙本報紙、電台廣播、電視新聞等露出請務必人工補充，俾使資料趨於完整。
    """)

elif sidebar_option == "系統管理員":
    st.subheader("🔐 系統管理員後台")
    admin_key = st.text_input("🔑 請輸入管理員金鑰：", type="password")
    if admin_key == "Automation_initiator114077":
        st.success("🔓 驗證成功，歡迎進入管理員後台！")
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("📅 今日日期", str(st.session_state["last_api_date"]))
        col_m2.metric("📡 今日 API 請求次數", f"{st.session_state['api_count_today']} 次")
        col_m3.metric("🔍 累積檢索次數", f"{len(st.session_state['search_history'])} 筆")
        
        if st.session_state["search_history"]:
            history_df = pd.DataFrame(st.session_state["search_history"])
            st.dataframe(history_df, use_container_width=True)
    elif admin_key:
        st.error("❌ 金鑰錯誤！")

# ---------------------------------------------------------------------------
# 5. 核心邏輯：方案一 (Gemini 1.5 Flash) + 方案三 (Python 本地防爆)
# ---------------------------------------------------------------------------
def render_airplane_progress(percent, text=""):
    return f"""
    <div style="width: 100%; margin-top: 10px; margin-bottom: 20px;">
        <div style="font-size: 0.9rem; font-weight: 600; color: #374151; margin-bottom: 5px;">{text}</div>
        <div style="width: 100%; background-color: #E5E7EB; border-radius: 10px; height: 24px; position: relative; overflow: hidden;">
            <div style="width: {percent}%; background: linear-gradient(90deg, #3B82F6, #1D4ED8); height: 100%; transition: width 0.4s ease; display: flex; align-items: center; justify-content: flex-end; padding-right: 5px;">
                <span style="font-size: 14px;">🛫</span>
            </div>
        </div>
        <div style="text-align: right; font-size: 0.85rem; font-weight: 700; color: #2563EB; margin-top: 3px;">🛫 {percent}%</div>
    </div>
    """

def lookup_media_type(media_name, media_map):
    """本地字典模糊與精準比對媒體類別"""
    m_name = str(media_name).strip()
    if m_name in media_map:
        return media_map[m_name]
    for k, v in media_map.items():
        if k in m_name or m_name in k:
            return v
    return "非三大報全國性"

def clean_title_local(title, media_name):
    """本地純 Python 標題清理演算法 (不用 AI 也能剔除標題後綴)"""
    cleaned = re.sub(r'\s*-\s*.*$', '', title) # 剔除 - 自由時報
    cleaned = re.sub(r'｜.*$', '', cleaned)    # 剔除 ｜ 聯合新聞網
    cleaned = re.sub(r'\|.*$', '', cleaned)
    return cleaned.strip()

def run_news_pipeline(office, staff_name, org, keyword, year, media_map, GEMINI_API_KEY):
    st.session_state["search_history"].append({
        "檢索時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "服務處": office, "同工姓名": staff_name, "機構": org, "關鍵字": keyword, "目標年份": year
    })

    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    raw_results = []
    with st.spinner(f"📡 正在經由 Google News 檢索『{search_query}』新聞報導..."):
        try:
            req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                source = item.find('source').text if item.find('source') is not None else "新聞媒體"
                
                raw_results.append({"title": title, "url": link, "date": pub_date, "media_name": source})
        except Exception as e:
            st.error(f"❌ Google News 檢索異常：{e}")
            return []

    if not raw_results:
        return []

    results = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    batch_size = 5
    batches = [raw_results[i:i + batch_size] for i in range(0, len(raw_results), batch_size)]
    
    progress_placeholder = st.empty()
    progress_placeholder.markdown(render_airplane_progress(0, f"🤖 開始處理新聞資料 (共 {len(batches)} 批次)..."), unsafe_allow_html=True)
    
    for idx, batch in enumerate(batches, start=1):
        batch_payload = [
            {"id": i, "title": item["title"], "date": item["date"], "media_name": item["media_name"]} 
            for i, item in enumerate(batch)
        ]

        prompt = f"""
        新聞列表：{json.dumps(batch_payload, ensure_ascii=False)}
        條件：發布年份須為 {year}，標題或內容需包含 {org} 或 {keyword}。
        請去除標題末端媒體名稱後綴（如「 - 自由時報」），並提取記者姓名 (若無填 '編輯部')。
        傳回 JSON 格式：
        {{"articles": [{{"id": 0, "media_name": "媒體名稱", "title": "純標題", "reporter": "記者姓名"}}]}}
        """
        
        max_retries = 2
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                st.session_state["api_count_today"] += 1
                
                response = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
