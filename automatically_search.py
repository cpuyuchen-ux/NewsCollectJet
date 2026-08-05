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
if sidebar_option == "系統簡介":
    st.subheader("ℹ️ 系統簡介")
    st.info("""
    **彰化家扶中心輿情自動檢索與報表生成系統** 旨在幫助同工快速彙整網路媒體報導。
    * **即時檢索**：自動抓取 Google News 最新相關新聞。
    * **AI + 本地備用演算法**：優先使用 Gemini 1.5 Flash 進行精準解析；若 API 限流則自動啟動「本地防爆演算法」，保障 100% 順利產出。
    """)

elif sidebar_option == "系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.warning("""
    1. **遵守使用規範**：本系統僅供彰化家扶內部輿情檢索使用。
    2. **API 額度雙保險機制**：系統採用 Gemini 1.5 Flash 模型，若仍遇到 429 配額額滿，會自動無縫轉入「本地純文字演算法」，確保資料不遺漏！
    3. **非網路新聞補充**：紙本報紙、廣播、電視露出請務必人工補充。
    """)

elif sidebar_option == "系統管理員":
    st.subheader("🔐 系統管理員後台")
    admin_key = st.text_input("🔑 請輸入管理員金鑰：", type="password")
    if admin_key == "Automation_initiator114077":
        st.success("🔓 驗證成功！")
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
    """方案三：本地純 Python 標題清理演算法 (不用 AI 也能剔除標題後綴)"""
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
    
    # 小批次處理，降低單次 API 負擔
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
                
                # 方案一：改用額度較充裕且獨立計算的 gemini-1.5-flash
                response = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                res_data = json.loads(response.text)
                parsed = res_data.get("articles", [])
                
                for art in parsed:
                    art_id = art.get("id", -1)
                    if 0 <= art_id < len(batch):
                        m_name = art.get("media_name") or batch[art_id]["media_name"]
                        results.append({
                            "media_name": m_name,
                            "media_type": lookup_media_type(m_name, media_map),
                            "title": art.get("title", batch[art_id]["title"]),
                            "reporter": art.get("reporter", "編輯部"),
                            "url": batch[art_id]["url"]
                        })
                success = True
                break
            except Exception as e:
                # 遇到頻率限制，短暫等待後重試
                time.sleep(2)
        
        # 方案三（保底）：若 AI API 依然爆掉 (429/500/Timeout)，無縫切換為 Python 本地純文字演算法！
        if not success:
            st.toast(f"⚡ 第 {idx} 批次 API 限流，已自動啟動「本地演算法」解析！", icon="⚡")
            for item in batch:
                c_title = clean_title_local(item["title"], item["media_name"])
                results.append({
                    "media_name": item["media_name"],
                    "media_type": lookup_media_type(item["media_name"], media_map),
                    "title": c_title,
                    "reporter": "編輯部",
                    "url": item["url"]
                })
            
        current_pct = int((idx / len(batches)) * 100)
        progress_placeholder.markdown(render_airplane_progress(current_pct, f"🛫 正在處理第 {idx}/{len(batches)} 批次..."), unsafe_allow_html=True)
        time.sleep(1) # 緩衝間隔，維護 API 健康
        
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
            selected_office = st.selectbox("🏢 篩選服務處", ["彰化分事務所", "和美兒童館", "員林服務處", "田中服務處", "彰化服務處", "二林服務處", "中心行政組"])
        with row1_col2:
            staff_name = st.text_input("👤 同工姓名", placeholder="請輸入同工姓名")

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        with row2_col1:
            target_org = st.text_input("🏢 機構 / 品牌名稱", value="彰化家扶")
        with row2_col2:
            search_keyword = st.text_input("🔑 搜尋關鍵字", value="課輔班")
        with row2_col3:
            target_year = st.text_input("📅 目標年份 (YYYY)", value="2026")

        st.markdown("</div>", unsafe_allow_html=True)

    if st.button("🚀 開始自動化檢索與解析", type="primary", use_container_width=True):
        if not staff_name or not target_org or not search_keyword or not target_year:
            st.error("⚠️ 請完整填寫搜尋條件！")
        else:
            results = run_news_pipeline(selected_office, staff_name, target_org, search_keyword, target_year, media_type_map, api_key)
            
            if not results:
                st.warning(f"🔍 未找到符合條件的新聞報導。")
            else:
                st.balloons()
                st.success(f"🎉 成功匯出 {len(results)} 筆新聞報導！")
                
                df_display = pd.DataFrame(results)
                df_display["服務處"] = selected_office
                df_display["檢索同工"] = staff_name
                
                df_export = df_display[["服務處", "檢索同工", "media_name", "media_type", "title", "reporter", "url"]].copy()
                df_export.columns = ["服務處", "檢索同工", "媒體名稱", "媒體類型", "新聞標題", "記者", "新聞連結"]
                
                st.dataframe(df_export, column_config={"新聞連結": st.column_config.LinkColumn("新聞連結")}, use_container_width=True, hide_index=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='輿情報導')
                    worksheet = writer.sheets['輿情報導']
                    for row_idx, url in enumerate(df_export['新聞連結'], start=2):
                        cell = worksheet.cell(row=row_idx, column=7)
                        cell.hyperlink = url
                        cell.style = "Hyperlink"

                st.download_button(
                    label="📥 下載 Excel 格式輿情報表",
                    data=output.getvalue(),
                    file_name=f"[{selected_office}_{staff_name}]{target_org}_{search_keyword}_{target_year}_輿情報表.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
