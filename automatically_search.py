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

# 注入自訂 CSS 來打造現代化介面
st.markdown("""
<style>
    /* 全局字體與背景優化 */
    .main {
        background-color: #f8f9fa;
    }
    
    /* 主標題樣式 */
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(120deg, #1E3A8A, #3B82F6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    
    .sub-header {
        color: #6B7280;
        font-size: 1.0rem;
        margin-bottom: 1.5rem;
    }

    /* 搜尋區塊卡片化 */
    .search-card {
        background-color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        border: 1px solid #E5E7EB;
        margin-bottom: 1.5rem;
    }
    
    /* 側邊欄優化 */
    [data-testid="stSidebar"] {
        background-color: #f1f5f9;
        border-right: 1px solid #E2E8F0;
    }
    
    /* 狀態卡片微調 */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.875rem;
        font-weight: 600;
    }
    
    /* 按鈕美化加強 */
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
# 2. 標題區塊
# ---------------------------------------------------------------------------
st.markdown('<div class="main-header">📰 彰化家扶中心輿情自動檢索與報表生成系統</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">自動整合 Google News 即時新聞，並透過 Gemini AI 自動進行年份對齊與格式化</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 3. 側邊欄設定與 Database 狀態檢查
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ 系統核心設定")

# 讀取 API Key (優先讀取 Secrets)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("🔑 輸入 Gemini API Key:", type="password", help="請輸入您的 Gemini API Key 以啟用 AI 解析功能")

if not api_key:
    st.warning("⚠️ 請先在 Streamlit Secrets 設定 `GEMINI_API_KEY` 或於左側欄位輸入 API Key 以開始使用。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.subheader("🗄️ 內部數據庫狀態")

# 自動讀取同目錄下的 Database.csv 檔案
db_file_path = "Database.csv"
db_df = None

if os.path.exists(db_file_path):
    try:
        db_df = pd.read_csv(db_file_path, encoding='utf-8').dropna(how='all')
        st.sidebar.success("✅ Database.csv 已連線")
        st.sidebar.metric(label="數據庫媒體筆數", value=f"{len(db_df)} 筆")
    except Exception as e:
        st.sidebar.error(f"❌ 讀取 Database.csv 失敗: {e}")
else:
    st.sidebar.info("ℹ️ 未檢測到 Database.csv\n(系統將以一般模式搜尋)")

# ---------------------------------------------------------------------------
# 4. 核心搜尋與 AI 分批解析 (帶有防錯與 Token 瘦身機制)
# ---------------------------------------------------------------------------
def run_news_pipeline(org, keyword, year, db_df, GEMINI_API_KEY):
    # 乾淨地將 CSV 轉為簡短 JSON，大幅省 Token
    db_context = ""
    if db_df is not None and not db_df.empty:
        clean_db = db_df.head(10).to_dict(orient="records")
        db_context = json.dumps(clean_db, ensure_ascii=False)

    # A. 組合搜尋關鍵字並進行 URL 編碼
    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)
    
    # B. 存取 Google News 台灣區中文 RSS 串流
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

    # C. AI 分批解析 (每批 10 筆)
    results = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    batch_size = 10
    batches = [raw_results[i:i + batch_size] for i in range(0, len(raw_results), batch_size)]
    
    progress_bar = st.progress(0, text=f"🤖 Gemini 正在精準篩選 {year} 年份報導並整理結構...")
    
    for idx, batch in enumerate(batches, start=1):
        prompt = f"""
        數據庫參考：{db_context}
        原始新聞：{json.dumps(batch, ensure_ascii=False)}

        請篩選出符合條件的新聞：
        1. 標題或內容包含「{org}」與「{keyword}」。
        2. 發布年份必須為『{year}』年。
        3. 清除標題中的媒體名稱後綴。

        輸出 JSON：
        {{
            "articles": [
                {{
                    "media_name": "媒體名稱",
                    "title": "純標題",
                    "reporter": "記者姓名 (若無填 '編輯部')",
                    "url": "新聞連結"
                }}
            ]
        }}
        """
        
        # 強制重試機制
        max_retries = 3
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
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
                st.toast(f"⏳ 第 {idx}/{len(batches)} 批次觸發頻率限制，自動等待 60 秒重試 (嘗試 {attempt}/{max_retries})...", icon="⏳")
                time.sleep(60)
        
        if not success:
            st.warning(f"⚠️ 第 {idx} 批次於多次重試後依然失敗，已跳過該批次。")
            
        progress_bar.progress(idx / len(batches))
        time.sleep(5.0)
        
    progress_bar.empty()
    return results

# ---------------------------------------------------------------------------
# 5. 主要 UI 操作介面 (卡片化容器)
# ---------------------------------------------------------------------------
with st.container():
    st.markdown('<div class="search-card">', unsafe_allow_html=True)
    st.subheader("🔍 設定檢索條件")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        target_org = st.text_input("🏢 機構 / 品牌名稱", value="彰化家扶", placeholder="例：彰化家扶")
    with col2:
        search_keyword = st.text_input("🔑 搜尋關鍵字", value="課輔班", placeholder="例：課輔班、相見歡")
    with col3:
        target_year = st.text_input("📅 目標年份 (YYYY)", value="2026", placeholder="例：2026")

    st.markdown("</div>", unsafe_allow_html=True)

# 搜尋執行按鈕
if st.button("🚀 開始自動化檢索與 AI 解析", type="primary", use_container_width=True):
    if not target_org or not search_keyword or not target_year:
        st.error("⚠️ 請完整填寫所有搜尋條件！")
    else:
        results = run_news_pipeline(target_org, search_keyword, target_year, db_df, api_key)
        
        if not results:
            st.warning(f"🔍 未找到符合條件的 {target_year} 年新聞報導 (或因免費 API 額度限制未能順利解析)。")
        else:
            st.balloons() # 搜尋成功的小慶祝動畫
            st.success(f"🎉 成功找到 {len(results)} 筆符合條件的 {target_year} 年新聞報導！")
            
            # 結果展示區塊
            st.subheader("📋 輿情數據預覽")
            
            df_display = pd.DataFrame(results)
            df_export = df_display[["media_name", "title", "reporter", "url"]].copy()
            df_export.columns = ["媒體名稱", "新聞標題", "記者", "新聞連結"]
            
            st.dataframe(
                df_export,
                column_config={
                    "新聞連結": st.column_config.LinkColumn("新聞連結")
                },
                use_container_width=True,
                hide_index=True
            )
            
            # 產出 Excel 檔案
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False, sheet_name='輿情報導')
                
                worksheet = writer.sheets['輿情報導']
                for row_idx, url in enumerate(df_export['新聞連結'], start=2):
                    cell = worksheet.cell(row=row_idx, column=4)
                    cell.hyperlink = url
                    cell.style = "Hyperlink"
                
                worksheet.column_dimensions['A'].width = 20
                worksheet.column_dimensions['B'].width = 50
                worksheet.column_dimensions['C'].width = 15
                worksheet.column_dimensions['D'].width = 40

            st.markdown("---")
            st.download_button(
                label="📥 下載 Excel 格式輿情報表",
                data=output.getvalue(),
                file_name=f"{target_org}_{search_keyword}_{target_year}_輿情報表.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
