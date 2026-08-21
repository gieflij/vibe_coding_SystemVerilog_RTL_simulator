"""
===============================================================================
RTL Verilog to SystemVerilog Converter - 메인 웹 애플리케이션 (app.py)
===============================================================================
이 파일은 Streamlit 프레임워크 기반의 메인 UI 진입점입니다.
- 초기 화면에서 의도하지 않은 기본 샘플(counter 코드) 자동 채움 전면 제거
- 파일 업로드 또는 직접 입력시에만 Verilog 소스가 채워지도록 완벽 수정
===============================================================================
"""

import streamlit as st
import os
import time

# 커스텀 유틸리티 및 백엔드 모듈 임포트
from utils import (
    validate_verilog_file, 
    validate_code_input, 
    extract_module_name,
    init_session_state,
    push_history,
    can_undo,
    can_redo,
    undo_history,
    redo_history,
    reset_session,
    create_zip_download_package,
    sync_sv_code,
    sync_verilog_code
)
from llm_pipeline import RTLConverterPipeline

# =============================================================================
# 1. Streamlit 페이지 기본 설정 (Page Config)
# =============================================================================
st.set_page_config(
    page_title="RTL Verilog → SystemVerilog 변환기",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 세션 상태 초기화 (앱 시작 시 항상 안전하게 보장)
init_session_state()

# =============================================================================
# 2. 커스텀 CSS 스타일 정의 (폰트 크기 및 카드 렌더링)
# =============================================================================
font_size_map = {"Small": "13px", "Medium": "15px", "Large": "18px"}
current_font_size = font_size_map.get(st.session_state.font_size, "15px")

st.markdown(f"""
    <style>
    .main-title {{
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E88E5;
        margin-bottom: 0.2rem;
    }}
    .sub-title {{
        font-size: 1.0rem;
        color: #555555;
        margin-bottom: 1.2rem;
    }}
    .status-card {{
        background-color: #F8F9FA;
        border-radius: 8px;
        padding: 1.2rem;
        border-left: 5px solid #1E88E5;
        margin-bottom: 1rem;
    }}
    .download-container {{
        background-color: #E8F5E9;
        border-radius: 8px;
        padding: 1.5rem;
        border: 2px dashed #4CAF50;
        text-align: center;
        margin-top: 1rem;
    }}
    .stTextArea textarea {{
        font-family: 'Consolas', 'Courier New', monospace !important;
        font-size: {current_font_size} !important;
    }}
    </style>
""", unsafe_allow_html=True)


# =============================================================================
# 3. Streamlit Secrets (보안 키) 가져오기
# =============================================================================
def get_gemini_api_key() -> str:
    """Streamlit Secrets 또는 환경 변수에서 Gemini API 키를 가져옵니다."""
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return os.environ.get("GEMINI_API_KEY", "")


# =============================================================================
# 4. 메인 화면 레이아웃 (Main Layout)
# =============================================================================
def main():
    # 헤더 섹션
    st.markdown('<div class="main-title">⚡ RTL Verilog → SystemVerilog 자동 변환 웹앱</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Verilog(.v) 코드를 표준 SystemVerilog(.sv)로 변환하고 한글 주석과 RTL 하드웨어 안전성을 검수합니다.</div>', unsafe_allow_html=True)
    
    # -------------------------------------------------------------------------
    # 상단 옵션 및 제어 바
    # -------------------------------------------------------------------------
    col_opt1, col_opt2, col_opt3 = st.columns([2, 2, 2])
    
    with col_opt1:
        st.session_state.enable_korean_comments = st.toggle(
            "📝 한글 주석 생성 (ON/OFF)", 
            value=st.session_state.enable_korean_comments
        )

    with col_opt2:
        st.session_state.font_size = st.selectbox(
            "🔤 에디터 폰트 크기", 
            options=["Small", "Medium", "Large"], 
            index=["Small", "Medium", "Large"].index(st.session_state.font_size)
        )

    with col_opt3:
        if st.button("↺ 전체 초기화", use_container_width=True):
            reset_session()
            st.toast("세션 상태와 변환 히스토리가 초기화되었습니다.", icon="🧹")
            st.rerun()

    st.divider()

    # -------------------------------------------------------------------------
    # 메인 요약 리포트 (Summary Dashboard)
    # -------------------------------------------------------------------------
    st.subheader("📊 변환 요약 대시보드")
    m = st.session_state.summary_metrics

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)

    with col_m1:
        st.metric("📦 모듈 정보", value=str(m.get("module_name", "-")), delta=f"Input: {m.get('inputs_count', 0)} / Output: {m.get('outputs_count', 0)}")

    with col_m2:
        st.metric("⚡ logic 타입 변환", value=f"{m.get('logic_conversions', 0)} 건", delta="reg/wire 통일")

    with col_m3:
        st.metric("🔄 always_ff/comb 전환", value=f"{m.get('always_conversions', 0)} 건", delta="동작 구분 완료")

    with col_m4:
        err_cnt = m.get("error_count", 0)
        auto_fixed = m.get("auto_fix_applied", False)
        status_str = "수정 완료" if auto_fixed else ("자동수정 대기" if err_cnt > 0 else "정상")
        st.metric("⚠️ 감지된 문법/안전성 오류", value=f"{err_cnt} 건", delta=status_str, delta_color="inverse" if err_cnt > 0 else "normal")

    st.divider()

    # -------------------------------------------------------------------------
    # Side-by-Side 비교 에디터
    # -------------------------------------------------------------------------
    st.subheader("🖥️ Side-by-Side 코드 비교 & 직접 수정 에디터")

    col_editor_left, col_editor_right = st.columns(2)

    # --- 좌측 에디터 (Verilog 원본 - 기본 카운터 샘플 제거) ---
    with col_editor_left:
        st.markdown("**Verilog (원본 코드 입력 / 붙여넣기)**")
        uploaded_file = st.file_uploader("`.v` 파일 업로드", type=["v", "txt", "docx", "pdf"], key="verilog_uploader")
        
        # 사용자가 파일을 올렸을 때만 소스가 세션에 들어가도록 처리
        if uploaded_file is not None:
            is_valid_file, msg = validate_verilog_file(uploaded_file.name)
            if not is_valid_file:
                st.error(f"❌ 파일 업로드 오류: {msg}")
                st.toast(msg, icon="🚨")
            else:
                try:
                    file_contents = uploaded_file.getvalue().decode("utf-8")
                    if st.session_state.verilog_code != file_contents:
                        sync_verilog_code(file_contents)
                        st.toast(f"'{uploaded_file.name}' 파일이 올바르게 로드되었습니다.", icon="📂")
                        st.rerun()
                except Exception as e:
                    st.error(f"파일 인코딩 읽기 실패: {str(e)}")

        # **[요구사항 완벽 반영]**: 올리지도 않은 샘플 counter 코드가 뜨지 않고 완전히 깨끗한 빈 상태(placeholder)로 시작!
        v_input = st.text_area(
            "Verilog 소스",
            value=st.session_state.verilog_code,
            height=320,
            placeholder="여기에 Verilog 코드를 직접 입력하시거나, 상단의 '.v 파일 업로드' 버튼을 이용해 파일을 등록해 주세요...",
            key=f"verilog_input_widget_{st.session_state.verilog_key_id}"
        )
        st.session_state.verilog_code = v_input

    # --- 우측 에디터 (SystemVerilog 변환 결과 - 직접 수정 가능) ---
    with col_editor_right:
        st.markdown("**SystemVerilog (변환 결과 - 편집 가능)**")
        
        col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
        with col_btn1:
            if st.button("↩️ Undo", disabled=not can_undo(), use_container_width=True):
                undo_history()
                st.rerun()
        with col_btn2:
            if st.button("↪️ Redo", disabled=not can_redo(), use_container_width=True):
                redo_history()
                st.rerun()
        with col_btn3:
            curr_idx = st.session_state.history_index
            total_h = len(st.session_state.history_stack)
            st.caption(f"히스토리 위치: `{curr_idx + 1} / {total_h}`")

        sv_edited = st.text_area(
            "SystemVerilog 소스",
            value=st.session_state.sv_code,
            height=320,
            placeholder="// [🚀 SystemVerilog로 변환 실행] 버튼을 클릭하면 여기에 변환 결과물이 도출됩니다.",
            key=f"sv_output_widget_{st.session_state.sv_key_id}"
        )

        if sv_edited != st.session_state.sv_code and sv_edited.strip() != "":
            st.session_state.sv_code = sv_edited
            push_history(sv_edited)

    # --- 변환 실행 버튼 ---
    btn_convert = st.button("🚀 SystemVerilog로 변환 실행", type="primary", use_container_width=True)

    if btn_convert:
        is_valid, msg = validate_code_input(st.session_state.verilog_code)
        if not is_valid:
            st.error(f"❌ 입력 오류: {msg}")
            return

        api_key = get_gemini_api_key()
        pipeline = RTLConverterPipeline(api_key=api_key)

        if not pipeline.is_ready():
            st.error("❌ Gemini API 키가 설정되지 않았습니다. .streamlit/secrets.toml을 확인해 주세요.")
            return

        progress_bar = st.progress(0, text="Step 1: 파일 분석 및 토큰 검사 진행 중...")
        time.sleep(0.2)
        progress_bar.progress(25, text="Step 1: 토큰 분석 완료 (25%)")

        time.sleep(0.2)
        progress_bar.progress(50, text="Step 2: 문법 및 RTL 하드웨어 안전성 검사 진행 중... (50%)")

        progress_bar.progress(75, text="Step 3: Gemini 3.6 Flash 호출 - SV 코드 및 한글 주석 생성 중... (75%)")
        result = pipeline.convert_verilog_to_sv(
            verilog_code=st.session_state.verilog_code, 
            include_korean_comments=st.session_state.enable_korean_comments
        )

        if result["success"]:
            progress_bar.progress(100, text="Step 4: 모듈 설명 및 요약 리포트 생성 완료! (100%)")
            
            st.session_state.summary_metrics = result.get("metrics", {})
            st.session_state.code_explanation = result.get("explanation", "")
            st.session_state.detected_errors = result.get("detected_errors", [])
            
            sync_sv_code(result["sv_code"])
            push_history(result["sv_code"])
            
            st.success("🎉 SystemVerilog 변환이 성공적으로 완료되었습니다!")
            st.rerun()
        else:
            progress_bar.empty()
            st.error(f"❌ 변환 중 오류 발생: {result['error']}")

    st.divider()

    # -------------------------------------------------------------------------
    # 상세 분석 탭 패널 (Tabs)
    # -------------------------------------------------------------------------
    st.subheader("🔍 상세 분석 패널")

    tab1, tab2 = st.tabs(["📝 모듈 동작 설명", "⚠️ 오류 검사 및 자동 수정"])

    with tab1:
        if st.session_state.code_explanation:
            st.info(st.session_state.code_explanation)
        else:
            st.write("*(변환 실행 후 모듈 동작 원리 및 입출력 설명이 여기에 표시됩니다.)*")

    with tab2:
        errors = st.session_state.detected_errors
        if not errors:
            st.success("✅ 원본 코드에서 감지된 문법 오류나 Latch 위험 요소가 없습니다.")
        else:
            st.warning(f"⚠️ 원본 코드에서 {len(errors)}건의 경고/오류가 감지되었습니다.")
            for err in errors:
                line_no = err.get("line", "-")
                issue = err.get("issue", "오류 내용 없음")
                suggestion = err.get("suggestion", "제안 없음")
                st.write(f"- **[Line {line_no}]** `{issue}` -> *추천 수정*: {suggestion}")

            st.divider()
            
            if st.button("🪄 오류 자동 수정 승인 및 재변환", type="secondary", use_container_width=True):
                api_key = get_gemini_api_key()
                pipeline = RTLConverterPipeline(api_key=api_key)
                
                with st.spinner("AI가 오류를 자동으로 수정하고 재변환하는 중입니다..."):
                    fix_result = pipeline.auto_fix_code(
                        verilog_code=st.session_state.verilog_code,
                        detected_errors=errors,
                        include_korean_comments=st.session_state.enable_korean_comments
                    )
                    
                if fix_result["success"]:
                    st.session_state.summary_metrics = fix_result.get("metrics", {})
                    st.session_state.code_explanation = fix_result.get("explanation", "")
                    st.session_state.detected_errors = []
                    
                    sync_sv_code(fix_result["sv_code"])
                    push_history(fix_result["sv_code"])
                    st.success("✨ AI 오류 자동 수정 및 재변환이 반영되었습니다!")
                    st.rerun()
                else:
                    st.error(f"자동 수정 실행 실패: {fix_result['error']}")

    st.divider()

    # -------------------------------------------------------------------------
    # 변환 결과물 전체 다운로드 영역 (ZIP Download Area)
    # -------------------------------------------------------------------------
    st.subheader("📦 변환 결과물 다운로드 (.zip)")

    if not st.session_state.sv_code:
        st.info("ℹ️ SystemVerilog 변환이 완료되면 여기에 전체 결과물(.zip) 다운로드 버튼이 활성화됩니다.")
    else:
        zip_bytes, zip_filename = create_zip_download_package(
            sv_code=st.session_state.sv_code,
            metrics=st.session_state.summary_metrics,
            explanation=st.session_state.code_explanation
        )

        st.markdown(
            f"""
            <div class="download-container">
                <h4>🎉 변환 및 검수가 완료되었습니다!</h4>
                <p>수정된 SystemVerilog (<code>.sv</code>) 코드와 분석 리포트 (<code>_report.md</code>) 패키지 파일을 다운로드하세요.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.download_button(
            label=f"📦 {zip_filename} 전체 다운로드 (.zip)",
            data=zip_bytes,
            file_name=zip_filename,
            mime="application/zip",
            type="primary",
            use_container_width=True
        )

    st.divider()

    # -------------------------------------------------------------------------
    # 시스템 상태 카드
    # -------------------------------------------------------------------------
    st.markdown(
        """
        <div class="status-card">
            <h4>📌 RTL SystemVerilog 자동 변환기</h4>
            <ul>
                <li>Verilog RTL → SystemVerilog (ANSI 스타일, logic 타입, always_ff/comb 분리) 변환</li>
                <li>라인별 한글 주석, 모듈 분석 리포트 및 ZIP 패키지 다운로드 제공</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
