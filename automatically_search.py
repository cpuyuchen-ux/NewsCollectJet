import io
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. 頁面配置與標題
# ---------------------------------------------------------------------------
st.set_page_config(page_title="輿情新聞自動化檢索系統", page_icon="📰", layout="wide")

st.title("📰 輿情新聞自動化檢索與報表生成系統")
st.caption("自動經由 Google News RSS 抓取新聞，並運用 Gemini AI 精準篩選年份與格式化")

# ---------------------------------------------------------------------------
# 2. 金鑰與資料庫管理者側邊欄
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ 系統設定")

# 讀取 API Key (優先讀取 Secrets)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("輸入 Gemini API Key:", type="password")

if not api_key:
    st.warning("⚠️ 請先在 Streamlit Secrets 設定 `GEMINI_API_KEY` 或於左側欄位輸入 API Key 以開始使用。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.subheader("🗄️ 內部數據庫 (Database.csv)")

# 管理者密碼解鎖機制 (預設密碼 automation_initiator114077)
db_df = None
db_unlocked = st.sidebar.checkbox("🔓 解鎖管理者設定 (上傳 Database.csv)")

if db_unlocked:
    admin_pwd = st.sidebar.text_input("請輸入管理者密碼:", type="password")
    if admin_pwd == "automation_initiator114077":
        st.sidebar.success("驗證成功！")
        uploaded_db = st.sidebar.file_uploader("上傳 Database.csv 檔", type=["csv"])
        if uploaded_db:
            try:
                db_df = pd.read_csv(uploaded_db)
                st.sidebar.info(f"已成功載入內部數據庫，共 {len(db_df)} 筆資料")
            except Exception as e:
                st.sidebar.error(f"讀取 Database.csv 失敗: {e}")
    elif admin_pwd:
        st.sidebar.error("密碼錯誤")

# ---------------------------------------------------------------------------
# 3. 核心搜尋與 AI 分批解析 (含 429 防爆與自動重試機制)
# ---------------------------------------------------------------------------
def run_news_pipeline(org, keyword, year, db_df, GEMINI_API_KEY):
    db_context = ""
    if db_df is not None:
        db_context = db_df.to_string(index=False)[:1000]

    # A. 組合搜尋關鍵字並進行 URL 編碼
    search_query = f"{org} {keyword}"
    encoded_query = urllib.parse.quote(search_query)
    
    # B. 存取 Google News 台灣區中文 RSS 串流 (免費、免金鑰、不限制 IP)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    raw_results = []
    with st.spinner(f"正在經由 Google News 檢索『{search_query}』新聞報導..."):
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
            st.error(f"Google News 檢索異常：{e}")
            return []

    if not raw_results:
        return []

    # C. AI 分批解析 (加入 429 防爆與自動重試機制)
    results = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 放大批次數量 (例如一次處理 50 筆)，減少呼叫 API 次數
    batch_size = 50
    batches = [raw_results[i:i + batch_size] for i in range(0, len(raw_results), batch_size)]
    
    progress_bar = st.progress(0, text=f"🤖 Gemini 正在精準篩選 {year} 年份報導並整理結構...")
    
    for idx, batch in enumerate(batches, start=1):
        prompt = f"""
        內部數據庫參考範例：
        ---
        {db_context}
        ---

        原始新聞列表 (每則新聞包含標題 title、連結 url、媒體 source、發布時間 date)：
        ---
        {json.dumps(batch, ensure_ascii=False)}
        ---
        請仔細分析資料，並進行精準篩選與整理：
        1. 文章內容或標題必須提及「{org}」與「{keyword}」。
        2. 檢查新聞的發布日期 (pubDate/date) 或報導內容，**必須屬於『{year} 年』發布的報導**。若屬於其他年份請務必剔除。
        3. 請將標題中的媒體名稱後綴（例如 "- ETtoday新聞雲" 或 "- 自由時報"）清除，只保留純新聞標題，並將媒體名稱獨立填入 media_name。

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
        
        # 進行最多 3 次重試，應對 429 API Rate Limit 限制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                res_data = json.loads(response.text)
                results.extend(res_data.get("articles", []))
                break  # 成功就跳出重試迴圈
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    st.toast(f"⏳ 觸發 API 頻率限制，等待 15 秒後重試第 {idx} 批次...", icon="⏳")
                    time.sleep(15)  # 等待 15 秒讓 Quota 冷卻
                else:
                    st.warning(f"第 {idx} 批次 AI 解析失敗：{e}")
                    break
            
        progress_bar.progress(idx / len(batches))
        time.sleep(4.0)  # 每批次間隔加大至 4 秒，防止瞬間請求過高
        
    progress_bar.empty()
    return results

# ---------------------------------------------------------------------------
# 4. 主要 UI 操作介面
# ---------------------------------------------------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    target_org = st.text_input("機構/品牌名稱", value="麗寶樂園")
with col2:
    search_keyword = st.text_input("搜尋關鍵字", value="斷軌")
with col3:
    target_year = st.text_input("指定目標年份 (YYYY)", value="2026")

if st.button("🚀 開始自動化檢索", type="primary", use_container_width=True):
    if not target_org or not search_keyword or not target_year:
        st.error("請完整填寫搜尋條件！")
    else:
        results = run_news_pipeline(target_org, search_keyword, target_year, db_df, api_key)
        
        if not results:
            st.warning(f"未找到符合條件的 {target_year} 年新聞報導。")
        else:
            st.success(f"🎉 成功找到 {len(results)} 筆符合條件的 {target_year} 年新聞報導！")
            
            # 轉換為 DataFrame 顯示與供下載
            df_display = pd.DataFrame(results)
            
            # 重新排列與重命名欄位
            df_export = df_display[["media_name", "title", "reporter", "url"]].copy()
            df_export.columns = ["媒體名稱", "新聞標題", "記者", "新聞連結"]
            
            # 呈現表格預覽
            st.dataframe(
                df_export,
                column_config={
                    "新聞連結": st.column_config.LinkColumn("新聞連結")
                },
                use_container_width=True,
                hide_index=True
            )
            
            # ---------------------------------------------------------------------------
            # 5. 匯出 Excel 報表 (包含超連結)
            # ---------------------------------------------------------------------------
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # 寫入資料
                df_export.to_excel(writer, index=False, sheet_name='輿情報導')
                
                # 自動調整欄寬與為 URL 加入點擊效果
                worksheet = writer.sheets['輿情報導']
                for row_idx, url in enumerate(df_export['新聞連結'], start=2):
                    cell = worksheet.cell(row=row_idx, column=4)
                    cell.hyperlink = url
                    cell.style = "Hyperlink"
                
                # 調整欄寬
                worksheet.column_dimensions['A'].width = 20
                worksheet.column_dimensions['B'].width = 50
                worksheet.column_dimensions['C'].width = 15
                worksheet.column_dimensions['D'].width = 40

            st.download_button(
                label="📥 下載 Excel 輿情報表",
                data=output.getvalue(),
                file_name=f"{target_org}_{search_keyword}_{target_year}_輿情報表.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
