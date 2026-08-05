import datetime
import io
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pandas as pd
import streamlit as st
import google.generativeai as genai

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
st.markdown('<div class="sub-header">自動整合 Google News 即時新聞，並透過 Python 與 Gemini AI 自動進行記者解析與格式化</div>', unsafe_allow_html=True)

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
if sidebar_option == "系統簡介":
    st.subheader("ℹ️ 系統簡介")
    st.info("""
    **彰化家扶中心輿情自動檢索與報表生成系統** 旨在幫助同工快速彙整網路媒體報導。
    * **即時檢索**：自動抓取 Google News 最新相關新聞。
    * **Python 深度網頁爬取**：自動點進新聞頁面，透過多重 Regex 與 HTML DOM 解析精準擷取記者姓名。
    * **一鍵報表**：自動產出包含超連結的標準化 Excel 檔案。
    """)

elif sidebar_option == "系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.warning("""
    1. **遵守使用規範**：本系統僅供彰化家扶內部輿情檢索使用。
    2. **中心PDF檔留存**：報表生成後，請將每一篇報導儲存成PDF檔，放置於中心查報資料夾。
    3. **人工調整格式**：報表生成後，請配合將資料貼進總會「2026年單位季報_媒體統計格式」之 excel 檔。
    """)

elif sidebar_option == "系統管理員":
    st.subheader("🔐 系統管理員後台")
    admin_key = st.text_input("🔑 請輸入管理員金鑰：", type="password")
    if admin_key == "Automation_initiator114077":
        st.success("🔓 驗證成功，歡迎進入管理員後台！")
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("📅 今日日期", str(st.session_state["last_api_date"]))
        col_m2.metric("📡 今日 API 請求次數", f"{st.session_state['api_count_today']} 次")
        col_m3.metric("📊 累積檢索次數", f"{len(st.session_state['search_history'])} 筆")
        
        if st.session_state["search_history"]:
            history_df = pd.DataFrame(st.session_state["search_history"])
            st.dataframe(history_df, use_container_width=True)

# ---------------------------------------------------------------------------
# 5. 核心 Python 記者抓取與標題清理邏輯
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

def extract_reporter_by_regex(text):
    """強化的 Python 正則表達式匹配引擎"""
    if not text:
        return None
        
    reporter_patterns = [
        r'[〔\[\(]?(?:記者|專題記者|特派記者)\s*([\u4e00-\u9fa5]{2,4})\s*[\/／\s]',  # 〔記者張三／彰化報導〕
        r'(?:記者|特派記者)\s*([\u4e00-\u9fa5]{2,4})\s*(?:報導|攝|電)',            # 記者李四報導
        r'([\u4e00-\u9fa5]{2,4})\s*[\/／]\s*(?:彰化|綜合|地方|台北|台中|高雄|報導)',# 王五／彰化報導
        r'(?:文|撰文|責任編輯|編輯|攝影)[\/／:\s]\s*([\u4e00-\u9fa5]{2,4})',       # 文／趙六 或 責任編輯：趙六
        r'[〔\[\(]\s*([\u4e00-\u9fa5]{2,4})\s*(?:採訪報導|報導)\s*[〕\]\)]',      # 〔孫七採訪報導〕
        r'記者\s*([\u4e00-\u9fa5]{2,4})'                                       # 記者張三
    ]
    for pattern in reporter_patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if name not in ["彰化", "報導", "綜合", "地方", "新聞", "中央社", "家扶", "中心"]:
                return name
    return None

def python_fetch_reporter_from_url(url, title):
    """Python 獨立抓取邏輯"""
    # 步驟 1: 先從標題比對
    reporter_from_title = extract_reporter_by_regex(title)
    if reporter_from_title:
        return reporter_from_title

    # 步驟 2: 連線抓取網頁內容 (加入安全設定避免 Request 報錯)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=4, context=ctx) as response:
            html = response.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            
            # (A) 檢查 HTML Meta author 標籤
            meta_author = soup.find('meta', {'name': re.compile(r'author|reporter|dable:author', re.I)})
            if meta_author and meta_author.get('content'):
                rep = extract_reporter_by_regex(meta_author['content'])
                if rep:
                    return rep
                elif len(meta_author['content'].strip()) <= 4:
                    return meta_author['content'].strip()

            # (B) 檢查常見新聞網站的記者 Class 區塊
            author_nodes = soup.select('.author, .reporter, .article-author, .author-name, .article-content__author')
            for node in author_nodes:
                rep = extract_reporter_by_regex(node.get_text())
                if rep:
                    return rep

            # (C) 抓取新聞前幾段 P 標籤內文進行比對
            paragraphs = soup.find_all('p')
            first_text = " ".join([p.get_text() for p in paragraphs[:5]])
            rep = extract_reporter_by_regex(first_text)
            if rep:
                return rep

    except Exception:
        pass  # 遇到失敗安全跳過

    return "編輯部"

def clean_title_python(title):
    """Python 清理新聞標題"""
    cleaned = re.sub(r'[\(\[\〔].*?(?:記者|報導|文|圖|攝影|編輯).*?[\)\]\〕]', '', title)
    cleaned = re.sub(r'\s*-\s*.*$', '', cleaned)     # 剔除 - 自由時報
    cleaned = re.sub(r'｜.*$', '', cleaned)          # 剔除 ｜ 聯合新聞網
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
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
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
    total_items = len(raw_results)
    
    progress_placeholder = st.empty()
    progress_placeholder.markdown(render_airplane_progress(0, f"🔎 Python 啟動網頁內文爬取與記者偵測 (共 {total_items} 筆)..."), unsafe_allow_html=True)
    
    for idx, item in enumerate(raw_results, start=1):
        detected_reporter = python_fetch_reporter_from_url(item["url"], item["title"])
        cleaned_title = clean_title_python(item["title"])
        m_type = lookup_media_type(item["media_name"], media_map)
        
        results.append({
            "media_name": item["media_name"],
            "media_type": m_type,
            "title": cleaned_title,
            "reporter": detected_reporter,
            "url": item["url"]
        })
        
        pct = int((idx / total_items) * 100)
        progress_placeholder.markdown(render_airplane_progress(pct, f"🛫 正在抓取第 {idx}/{total_items} 筆新聞內文與記者資訊..."), unsafe_allow_html=True)
        time.sleep(0.1)
        
    progress_placeholder.empty()
    return results

# ---------------------------------------------------------------------------
# 6. 主控台介面
# ---------------------------------------------------------------------------
if sidebar_option == "主控台 / 檢索系統":
    if not api_key:
        st.warning("⚠️ 請先設定 API Key 以啟用檢索系統。")
        st.stop()

    with st.container():
        st.markdown('<div class="search-card">', unsafe_allow_html=True)
        st.subheader("🔍 設定檢索條件")
        
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            selected_office = st.selectbox("🏢 篩選服務處", ["全部", "和美兒童館", "員林服務處", "田中服務處", "彰化服務處", "二林服務處", "中心行政組"])
        with row1_col2:
            staff_name = st.text_input("👤 同工姓名", placeholder="e.g. 家扶小幫手")

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        with row2_col1:
            target_org = st.text_input("🏢 機構 / 品牌名稱", placeholder="e.g. 彰化家扶")
        with row2_col2:
            search_keyword = st.text_input("🔑 搜尋關鍵字", placeholder="e.g. 課輔班、相見歡")
        with row2_col3:
            target_year = st.text_input("📅 目標年份 (YYYY)", placeholder="e.g. 2026")

        st.markdown("</div>", unsafe_allow_html=True)

    if st.button("🚀 開始自動化檢索與解析", type="primary", use_container_width=True):
        if not staff_name or not target_org or not search_keyword or not target_year:
            st.error("⚠️ 請完整填寫所有欄位條件！")
        else:
            results = run_news_pipeline(selected_office, staff_name, target_org, search_keyword, target_year, media_type_map, api_key)
            
            if not results:
                st.warning("🔍 未找到符合條件的新聞報導。")
            else:
                st.balloons()
                st.success(f"🎉 成功匯出 {len(results)} 筆新聞報導！")
                
                df_display = pd.DataFrame(results)
                df_display["服務處"] = selected_office
                df_display["檢索同工"] = staff_name
                
                # 欄位順序：A:媒體名稱 | B:新聞標題 | C:新聞連結 | D:記者姓名 | E:媒體類型 | F:服務處 | G:檢索同工
                df_export = df_display[["media_name", "title", "url", "reporter", "media_type", "服務處", "檢索同工"]].copy()
                df_export.columns = ["媒體名稱", "新聞標題", "新聞連結", "記者姓名", "媒體類型", "服務處", "檢索同工"]
                
                st.dataframe(df_export, column_config={"新聞連結": st.column_config.LinkColumn("新聞連結")}, use_container_width=True, hide_index=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='輿情報導')
                    worksheet = writer.sheets['輿情報導']
                    for row_idx, url in enumerate(df_export['新聞連結'], start=2):
                        cell = worksheet.cell(row=row_idx, column=3)
                        cell.hyperlink = url
                        cell.style = "Hyperlink"

                st.download_button(
                    label="📥 下載 Excel 格式輿情報表",
                    data=output.getvalue(),
                    file_name=f"[{selected_office}_{staff_name}]{target_org}_{search_keyword}_{target_year}_輿情報表.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
