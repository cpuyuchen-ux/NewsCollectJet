# ========================================================
# 單位專屬新聞搜尋引擎 Web App (AI 年份精準篩選與權限控管版)
# ========================================================

import os
import json
import io
import time
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import streamlit as st
from duckduckgo_search import DDGS
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. 網頁基本設定與管理者密碼設定
# ---------------------------------------------------------------------------
st.set_page_config(page_title="單位專屬新聞搜尋引擎", page_icon="📰", layout="wide")

st.title("📰 單位專屬輿情新聞搜尋引擎")
st.caption("結合內部數據庫、DuckDuckGo 與 Gemini AI，自動檢索並整理格式化新聞報導。")

# 🔒 請在此設定您的專屬管理者密碼 (可自行修改)
ADMIN_PASSWORD = "Automation_initiator114077"

# 初始化 Session State (紀錄權限與數據庫)
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "active_db_df" not in st.session_state:
    st.session_state["active_db_df"] = None

# 讀取 GEMINI_API_KEY (優先從 Streamlit Secrets 讀取，其次從環境變數)
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    st.error("⚠️ 未偵測到 GEMINI_API_KEY！部署至雲端時請於 Secrets 設定，本地執行請設定環境變數。")

# ---------------------------------------------------------------------------
# 2. 側邊欄：搜尋條件與管理者解鎖控制
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🔍 新聞檢索條件")
    
    target_org = st.text_input("單位名稱", value="家扶")
    event_keyword = st.text_input("事件/活動關鍵字", value="麗寶樂園")
    target_year = st.selectbox("目標年份", options=[2026, 2025, 2024, 2023], index=0)
    
    # 搜尋按鈕
    search_submitted = st.button("🚀 開始搜尋輿情", type="primary", use_container_width=True)

    st.divider()

    # 🔒 管理者權限控管區塊
    st.subheader("🔐 後台管理權限")
    
    if not st.session_state["is_admin"]:
        input_pwd = st.text_input("輸入管理者密碼以解鎖進階設定", type="password")
        if st.button("解鎖權限", use_container_width=True):
            if input_pwd == ADMIN_PASSWORD:
                st.session_state["is_admin"] = True
                st.success("🔓 已成功登入管理者模式！")
                st.rerun()
            else:
                st.error("❌ 密碼錯誤！")
    else:
        st.success("👑 目前身分：系統管理者 (Admin)")
        if st.button("🔒 登出管理者權限", use_container_width=True):
            st.session_state["is_admin"] = False
            st.rerun()

    # ⚙️ 管理者專屬控管面板 (只有管理者看得見)
    if st.session_state["is_admin"]:
        st.divider()
        st.subheader("⚙️ 管理者控制台")
        st.info("💡 只有您能在此上傳/更新數據庫 CSV。")
        
        uploaded_db = st.file_uploader("上傳/更換單位 Database.csv", type=["csv"])
        if uploaded_db is not None:
            try:
                st.session_state["active_db_df"] = pd.read_csv(uploaded_db)
                st.success("✅ 數據庫已更新並儲存於當前 Session！")
            except Exception as e:
                st.error(f"⚠️ 讀取 CSV 失敗：{e}")

# ---------------------------------------------------------------------------
# 3. 核心搜尋與 AI 年份精準過濾邏輯
# ---------------------------------------------------------------------------
def run_news_pipeline(org, keyword, year, db_df):
    db_context = ""
    if db_df is not None:
        db_context = db_df.to_string(index=False)[:1000]

    # 1. 搜尋關鍵字只放「單位 + 關鍵字」，不放年份以防漏抓新聞
    search_query = f"{org} {keyword}"
    
    # A. 爬取新聞 (加入請求延遲緩衝)
    raw_results = []
    with st.spinner(f"正在全網搜尋『{search_query}』相關報導中..."):
        time.sleep(1)  # 搜尋前緩衝 1 秒，保護 API
        try:
            with DDGS() as ddgs:
                ddg_news = list(ddgs.news(keywords=search_query, region="tw-tzh", max_results=100))
                if ddg_news:
                    raw_results = ddg_news
        except Exception as e:
            st.error(f"搜尋發生異常：{e}")
            return []

    if not raw_results:
        return []

    # B. AI 分批解析 (交由 Gemini 讀取發布時間 date 並嚴格比對年份)
    results = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    batch_size = 25
    batches = [raw_results[i:i + batch_size] for i in range(0, len(raw_results), batch_size)]
    
    progress_bar = st.progress(0, text=f"🤖 Gemini 正在精準篩選 {year} 年份報導並進行結構化...")
    
    for idx, batch in enumerate(batches, start=1):
        prompt = f"""
        內部數據庫參考範例：
        ---
        {db_context}
        ---

        原始新聞列表 (每則新聞皆包含發布時間 date)：
        ---
        {json.dumps(batch, ensure_ascii=False)}
        ---
        請仔細分析資料，並進行精準篩選：
        1. 文章內容或標題必須提及「{org}」與「{keyword}」。
        2. 檢查新聞的發布日期 (date) 或報導內容，**必須屬於『{year} 年』發布的報導**。若屬於其他年份請務必剔除。

        輸出 JSON 格式：
        {{
            "articles": [
                {{
                    "media_name": "新聞媒體名稱",
                    "title": "新聞標題",
                    "reporter": "記者姓名 (若無顯示請填 '編輯部')",
                    "url": "新聞連結"
                }}
            ]
        }}
        """
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            res_data = json.loads(response.text)
            results.extend(res_data.get("articles", []))
        except Exception as e:
            st.warning(f"第 {idx} 批次解析稍有延遲：{e}")
            
        progress_bar.progress(idx / len(batches))
        time.sleep(1.5)  # 每批次間隔 1.5 秒，確保遵循 RPM 限制
        
    progress_bar.empty()
    return results

# ---------------------------------------------------------------------------
# 4. 產出指定格式 Excel 記憶體二進位檔 (A:媒體, B:標題+連結, C:記者)
# ---------------------------------------------------------------------------
def generate_custom_excel(articles_data):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "新聞輿情彙整"
    ws.views.sheetView[0].showGridLines = True

    # Excel 樣式設定
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="微軟正黑體", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="微軟正黑體", size=10)
    link_font = Font(name="微軟正黑體", size=10, color="0000FF", underline="single")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    headers = ["媒體名稱", "報導標題", "記者姓名"]
    ws.append(headers)

    for col_idx in range(1, 4):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25

    # 寫入資料列
    for row_idx, item in enumerate(articles_data, start=2):
        ws.row_dimensions[row_idx].height = 22
        
        c_a = ws.cell(row=row_idx, column=1, value=item.get("media_name", "未知媒體"))
        
        c_b = ws.cell(row=row_idx, column=2, value=item.get("title", "無標題"))
        raw_url = item.get("url", "")
        if raw_url:
            c_b.hyperlink = raw_url
            c_b.font = link_font
        else:
            c_b.font = body_font

        c_c = ws.cell(row=row_idx, column=3, value=item.get("reporter", "編輯部"))

        c_a.alignment = Alignment(horizontal="center", vertical="center")
        c_b.alignment = Alignment(horizontal="left", vertical="center")
        c_c.alignment = Alignment(horizontal="center", vertical="center")

        for col_idx in range(1, 4):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border
            if col_idx != 2:
                cell.font = body_font

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 60
    ws.column_dimensions['C'].width = 18

    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    return excel_buffer

# ---------------------------------------------------------------------------
# 5. 主畫面互動與結果顯示
# ---------------------------------------------------------------------------
if search_submitted:
    if not GEMINI_API_KEY:
        st.stop()
        
    articles = run_news_pipeline(
        target_org, 
        event_keyword, 
        target_year, 
        st.session_state.get("active_db_df")
    )
    
    if articles:
        st.session_state['search_results'] = articles
        st.success(f"🎉 搜尋完成！共檢索到 {len(articles)} 則符合條件的 {target_year} 年報導。")
    else:
        st.session_state['search_results'] = []
        st.warning(f"⚪ 未找到符合條件的 {target_year} 年新聞報導。")

if 'search_results' in st.session_state and st.session_state['search_results']:
    results_list = st.session_state['search_results']
    
    df_display = pd.DataFrame(results_list)
    df_display = df_display.rename(columns={
        "media_name": "媒體名稱 (A欄)",
        "title": "報導標題 (B欄)",
        "reporter": "記者姓名 (C欄)",
        "url": "報導連結"
    })
    
    st.subheader("📊 搜尋結果預覽")
    st.dataframe(df_display[["媒體名稱 (A欄)", "報導標題 (B欄)", "記者姓名 (C欄)", "報導連結"]], use_container_width=True)

    excel_file = generate_custom_excel(results_list)
    
    st.download_button(
        label="📥 匯出 Excel 報表",
        data=excel_file,
        file_name=f"{target_org}_{event_keyword}_{target_year}_輿情報表.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )