import datetime
import io
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. 頁面配置與自訂 CSS 樣式 (UI 美化核心)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="彰化家扶輿情自動檢索與報表生成系統", 
    page_icon="📰", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化 Session State (紀錄搜尋歷史與 API 請求次數)
if "api_count_today" not in st.session_state:
    st.session_state["api_count_today"] = 0
if "last_api_date" not in st.session_state:
    st.session_state["last_api_date"] = datetime.date.today()
if "search_history" not in st.session_state:
    st.session_state["search_history"] = []

# 重置每日 API 次數
if st.session_state["last_api_date"] != datetime.date.today():
    st.session_state["api_count_today"] = 0
    st.session_state["last_api_date"] = datetime.date.today()

# 注入 CSS 樣式
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1F2937;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        color: #6B7280;
        font-size: 1.0rem;
        margin-bottom: 0.8rem;
    }
    .warning-bar {
        background-color: #FEF2F2;
        border-left: 5px solid #EF4444;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        margin-bottom: 1.5rem;
    }
    .warning-text {
        color: #DC2626;
        font-weight: 700;
        font-size: 0.95rem;
        margin: 0;
    }
    .search-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        border: 1px solid #E5E7EB;
        margin-bottom: 1.5rem;
    }
    [data-testid="stSidebar"] {
        background-color: #f1f5f9;
        border-right: 1px solid #E2E8F0;
    }
    div.stButton > button:first-child {
        background: linear-gradient(90deg, #2563EB, #1D4ED8);
        color: white;
        border: none;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
        transition: all 0.3s ease;
    }
    div.stButton > button:first-child:hover {
        background: linear-gradient(90deg, #1D4ED8, #1E40AF);
        box-shadow: 0 4px 8px rgba(37, 99, 235, 0.3);
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
    <p class="warning-text">※此系統為個人自主開發，請勿用做非法行為！</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 3. 側邊欄與 Database 載入
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ 系統核心設定")

sidebar_option = st.sidebar.selectbox(
    "請選擇功能模組：",
    ["主控台 / 檢索系統", "系統簡介", "系統須知", "系統管理員"]
)

api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("🔑 輸入 Gemini API Key:", type="password", help="請輸入您的 Gemini API Key 以啟用 AI 解析功能")

st.sidebar.markdown("---")

db_file_path = "Database.csv"
db_df = None
if os.path.exists(db_file_path):
    try:
        db_df = pd.read_csv(db_file_path, encoding='utf-8').dropna(how='all')
        st.sidebar.success("✅ Database.csv 已連線")
        st.sidebar.caption(f"已匯入 {len(db_df)} 筆對照媒體資料")
    except Exception as e:
        st.sidebar.error(f"❌ 讀取 Database.csv 失敗: {e}")

# ---------------------------------------------------------------------------
# 4. 選單模組切換邏輯
# ---------------------------------------------------------------------------
if sidebar_option == "系統簡介":
    st.subheader("ℹ️ 系統簡介")
    st.info("""
    **彰化家扶中心輿情自動檢索與報表生成系統** 旨在幫助同工快速彙整網路媒體報導。
    
    * **即時檢索**：自動爬取 Google News 最新相關新聞。
    * **AI 結構化整理**：運用 Gemini AI 自動識別新聞標題、發布年份、記者姓名並對照媒體資料庫自動歸類媒體類型。
    * **一鍵報表**：自動產出包含服務處、同工、媒體分類與超連結的標準化 Excel 檔案。
    """)

elif sidebar_option == "系統須知":
    st.subheader("📌 系統須知與使用規範")
    st.warning("""
    1. **遵守使用規範**：本系統僅供彰化家扶內部輿情檢索與學術研究使用，嚴禁用於商業爬蟲、攻擊或任何非法用途。
    2. **API 額度限制**：請勿短時間內頻繁發送大規模檢索請求，以免觸發 API 限流。
    3. **資料準確性**：AI 自動解析結果僅供參考，匯出報表後建議人工進行二次核對。
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
        
        st.markdown("---")
        st.subheader("📊 檢索歷史紀錄與統計")
        
        if st.session_state["search_history"]:
            history_df = pd.DataFrame(st.session_state["search_history"])
            st.dataframe(history_df, use_container_width=True)
            
            history_output = io.BytesIO()
            with pd.ExcelWriter(history_output, engine='openpyxl') as writer:
                history_df.to_excel(writer, index=False, sheet_name='系統使用統計')
            
            st.download_button(
                label="📥 匯出管理員統計報表 (Excel)",
                data=history_output.getvalue(),
                file_name=f"系統使用紀錄_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("目前尚無搜尋歷史紀錄。")
            
    elif admin_key:
        st.error("❌ 金鑰錯誤，無法存取管理員後台！")

# ---------------------------------------------------------------------------
# 5. 核心搜尋與進度條渲染邏輯
# ---------------------------------------------------------------------------
def render_airplane_progress(percent, text=""):
    return f"""
    <div style="width: 100%; margin-top: 10px; margin-bottom: 20px;">
        <div style="font-size: 0.9rem; font-weight: 600; color: #374151; margin-bottom: 5px;">
            {text}
        </div>
        <div style="width: 100%; background-color: #E5E7EB; border-radius: 10px; height: 24px; position: relative; overflow: hidden; box-shadow: inset 0 1px 2px rgba(0,0,0,0.1);">
            <div style="width: {percent}%; background: linear-gradient(90deg, #3B82F6, #1D4ED8); height: 100%; border-radius: 10px; transition: width 0.4s ease; display: flex; align-items: center; justify-content: flex-end; padding-right: 5px;">
                <span style="font-size: 14px; line-height: 1; user-select: none;">🛫</span>
            </div>
        </div>
        <div style="text-align: right; font-size: 0.85rem; font-weight: 700; color: #2563EB; margin-top: 3px;">
            🛫 {percent}%
        </div>
    </div>
    """

def run_news_pipeline(office, staff_name, org, keyword, year, db_df, GEMINI_API_KEY):
    st.session_state["search_history"].append({
        "檢索時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "服務處": office,
        "同工姓名": staff_name,
        "機構": org,
        "關鍵字": keyword,
        "目標年份": year
    })

    db_context = ""
    if db_df is not None and not db_df.empty:
        clean_db = db_df.to_dict(orient="records")
        db_context = json.dumps(clean_db, ensure_ascii=False)

    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    raw_results = []
    with st.spinner(f"📡 正在經由 Google News 檢索『{search_query}』新聞報導..."):
        try:
            req = urllib.request.Request(
                rss_url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                source = item.find('source').text if item.find('source') is not None else "新聞媒體"
                
                raw_results.append({
                    "title": title,
                    "url": link,
                    "date": pub_date,
                    "media_name": source
                })
        except Exception as e:
            st.error(f"❌ Google News 檢索異常：{e}")
            return []

    if not raw_results:
        return []

    results = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    batch_size = 10
    batches = [raw_results[i:i + batch_size] for i in range(0, len(raw_results), batch_size)]
    
    progress_placeholder = st.empty()
    progress_placeholder.markdown(
        render_airplane_progress(0, f"🤖 Gemini 正在精準篩選 {year} 年份報導並自動比對媒體分類..."), 
        unsafe_allow_html=True
    )
    
    for idx, batch in enumerate(batches, start=1):
        prompt = f"""
        媒體數據庫對照清單：{db_context}
        原始新聞資料：{json.dumps(batch, ensure_ascii=False)}

        請執行以下任務：
        1. 篩選標題或內容包含「{org}」與「{keyword}」的新聞。
        2. 發布年份必須為『{year}』年。
        3. 淨化新聞標題（去除媒體名稱後綴）。
        4. 比對媒體數據庫對照清單，給出正確的「media_type（媒體類型）」。若資料庫無對應，填寫「網路媒體」。

        請回傳 JSON 格式：
        {{
            "articles": [
                {{
                    "media_name": "媒體名稱",
                    "media_type": "媒體類型",
                    "title": "純淨新聞標題",
                    "reporter": "記者姓名 (若無則填 '編輯部')",
                    "url": "新聞連結"
                }}
            ]
        }}
        """
        
        max_retries = 3
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                st.session_state["api_count_today"] += 1
                
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                res_data = json.loads(response.text)
                results.extend(res_data.get("articles", []))
                success = True
                break
            except Exception as e:
                st.toast(f"⏳ 第 {idx}/{len(batches)} 批次觸發頻率限制，自動等待 60 秒重試...", icon="⏳")
                time.sleep(60)
        
        if not success:
            st.warning(f"⚠️ 第 {idx} 批次解析失敗，已跳過該批次。")
            
        current_pct = int((idx / len(batches)) * 100)
        progress_placeholder.markdown(
            render_airplane_progress(current_pct, f"🤖 Gemini 正在處理第 {idx}/{len(batches)} 批次新聞資料..."), 
            unsafe_allow_html=True
        )
        time.sleep(2.0)
        
    progress_placeholder.empty()
    return results

# ---------------------------------------------------------------------------
# 6. 主控台介面
# ---------------------------------------------------------------------------
if sidebar_option == "主控台 / 檢索系統":
    if not api_key:
        st.warning("⚠️ 請先在 Streamlit Secrets 設定 `GEMINI_API_KEY` 或於左側欄位輸入 API Key 以開始使用。")
        st.stop()

    with st.container():
        st.markdown('<div class="search-card">', unsafe_allow_html=True)
        st.subheader("🔍 設定檢索條件")
        
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            office_list = ["總會/彰化事務所", "和美服務處", "員林服務處", "田中服務處", "鹿港服務處", "二林服務處"]
            selected_office = st.selectbox("🏢 篩選服務處", options=office_list)
        with row1_col2:
            staff_name = st.text_input("👤 同工姓名", placeholder="請輸入填表/檢索同工姓名")

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        with row2_col1:
            target_org = st.text_input("🏢 機構 / 品牌名稱", value="彰化家扶", placeholder="例：彰化家扶")
        with row2_col2:
            search_keyword = st.text_input("🔑 搜尋關鍵字", value="課輔班", placeholder="例：課輔班、相見歡")
        with row2_col3:
            target_year = st.text_input("📅 目標年份 (YYYY)", value="2026", placeholder="例：2026")

        st.markdown("</div>", unsafe_allow_html=True)

    if st.button("🚀 開始自動化檢索與 AI 解析", type="primary", use_container_width=True):
        if not staff_name:
            st.error("⚠️ 請輸入「同工姓名」以方便後續核對紀錄！")
        elif not target_org or not search_keyword or not target_year:
            st.error("⚠️ 請完整填寫搜尋條件！")
        else:
            results = run_news_pipeline(selected_office, staff_name, target_org, search_keyword, target_year, db_df, api_key)
            
            if not results:
                st.warning(f"🔍 未找到符合條件的 {target_year} 年新聞報導。")
            else:
                st.balloons()
                st.success(f"🎉 成功找到 {len(results)} 筆符合條件的 {target_year} 年新聞報導！")
                
                st.subheader("📋 輿情數據預覽")
                
                df_display = pd.DataFrame(results)
                df_display["服務處"] = selected_office
                df_display["檢索同工"] = staff_name
                
                # 調整輸出欄位順序（帶入媒體類型）
                df_export = df_display[["服務處", "檢索同工", "media_name", "media_type", "title", "reporter", "url"]].copy()
                df_export.columns = ["服務處", "檢索同工", "媒體名稱", "媒體類型", "新聞標題", "記者", "新聞連結"]
                
                st.dataframe(
                    df_export,
                    column_config={
                        "新聞連結": st.column_config.LinkColumn("新聞連結")
                    },
                    use_container_width=True,
                    hide_index=True
                )
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='輿情報導')
                    
                    worksheet = writer.sheets['輿情報導']
                    for row_idx, url in enumerate(df_export['新聞連結'], start=2):
                        cell = worksheet.cell(row=row_idx, column=7)
                        cell.hyperlink = url
                        cell.style = "Hyperlink"
                    
                    worksheet.column_dimensions['A'].width = 18
                    worksheet.column_dimensions['B'].width = 12
                    worksheet.column_dimensions['C'].width = 18
                    worksheet.column_dimensions['D'].width = 15
                    worksheet.column_dimensions['E'].width = 45
                    worksheet.column_dimensions['F'].width = 12
                    worksheet.column_dimensions['G'].width = 35

                st.markdown("---")
                st.download_button(
                    label="📥 下載 Excel 格式輿情報表",
                    data=output.getvalue(),
                    file_name=f"[{selected_office}_{staff_name}]{target_org}_{search_keyword}_{target_year}_輿情報表.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
