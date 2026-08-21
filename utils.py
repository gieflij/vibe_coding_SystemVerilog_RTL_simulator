"""
===============================================================================
RTL Verilog to SystemVerilog Converter - 유틸리티 모듈 (utils.py)
===============================================================================
이 모듈은 웹 애플리케이션에서 사용되는 일반 유틸리티 함수, 세션 관리 및 ZIP 파일 패키징을 제공합니다.
- 업로드된 파일 확장자 검증
- 텍스트 입력 유효성 검사
- 안전한 파일명 및 모듈명 추출
- Streamlit 세션 상태(st.session_state) 및 동적 위젯 Key 리셋 관리
- ZIP 압축 생성 유틸리티
===============================================================================
"""

import os
import re
import io
import zipfile
import streamlit as st
from typing import Tuple, Optional, Dict, Any, List


# =============================================================================
# 1. 파일 및 코드 검증 유틸리티
# =============================================================================

def validate_verilog_file(file_name: str) -> Tuple[bool, str]:
    """업로드된 파일이 올바른 Verilog 파일(.v)인지 검증하는 함수"""
    if not file_name:
        return False, "파일 이름이 비어 있습니다."
        
    _, ext = os.path.splitext(file_name)
    ext = ext.lower()
    
    if ext == ".v":
        return True, "올바른 Verilog 파일입니다."
    else:
        return False, f"지원하지 않는 파일 형식입니다: '{ext}' -> '.v' 파일만 업로드할 수 있습니다."


def validate_code_input(code_text: str) -> Tuple[bool, str]:
    """입력된 Verilog 코드 텍스트가 유효한지 기본적인 검사를 수행합니다."""
    stripped_code = code_text.strip()
    if not stripped_code:
        return False, "입력된 코드가 없습니다. Verilog 코드를 입력하거나 파일을 업로드해 주세요."
        
    if len(stripped_code) < 10:
        return False, "입력된 코드가 너무 짧습니다. 올바른 RTL 코드를 입력해 주세요."
        
    return True, "유효한 코드 입력입니다."


def extract_module_name(code_text: str) -> str:
    """Verilog 또는 SystemVerilog 코드 텍스트에서 모듈 이름을 추출합니다."""
    match = re.search(r'\bmodule\s+([a-zA-Z_][a-zA-Z0-9_]*)', code_text)
    if match:
        return match.group(1)
    return "converted_module"


# =============================================================================
# 2. 세션 상태 (st.session_state) 초기화 및 히스토리 관리
# =============================================================================

def init_session_state() -> None:
    """Streamlit 세션 변수 초기화"""
    if "verilog_code" not in st.session_state:
        st.session_state.verilog_code = ""
        
    if "sv_code" not in st.session_state:
        st.session_state.sv_code = ""

    if "verilog_key_id" not in st.session_state:
        st.session_state.verilog_key_id = 0

    if "sv_key_id" not in st.session_state:
        st.session_state.sv_key_id = 0

    if "enable_korean_comments" not in st.session_state:
        st.session_state.enable_korean_comments = True
        
    if "font_size" not in st.session_state:
        st.session_state.font_size = "Medium"

    if "progress_step" not in st.session_state:
        st.session_state.progress_step = 0
        
    if "summary_metrics" not in st.session_state:
        st.session_state.summary_metrics = {
            "module_name": "-",
            "inputs_count": 0,
            "outputs_count": 0,
            "converted_lines": 0,
            "logic_conversions": 0,
            "always_conversions": 0,
            "error_count": 0,
            "auto_fix_applied": False
        }

    if "code_explanation" not in st.session_state:
        st.session_state.code_explanation = ""
        
    if "detected_errors" not in st.session_state:
        st.session_state.detected_errors = []

    if "history_stack" not in st.session_state:
        st.session_state.history_stack = []
        
    if "history_index" not in st.session_state:
        st.session_state.history_index = -1


def sync_sv_code(new_sv_code: str) -> None:
    """
    st.session_state.sv_code를 업데이트하고 위젯 Key ID를 증가시켜 우측 에디터 렌더링을 100% 강제 갱신합니다.
    """
    st.session_state.sv_code = new_sv_code
    st.session_state.sv_key_id = st.session_state.get("sv_key_id", 0) + 1


def sync_verilog_code(new_verilog_code: str) -> None:
    """
    st.session_state.verilog_code를 업데이트하고 위젯 Key ID를 증가시켜 좌측 에디터 렌더링을 100% 강제 갱신합니다.
    """
    st.session_state.verilog_code = new_verilog_code
    st.session_state.verilog_key_id = st.session_state.get("verilog_key_id", 0) + 1


def push_history(sv_code: str) -> None:
    """히스토리 스택에 새로운 코드 버전 기록 및 위젯 동기화"""
    init_session_state()
    if not sv_code:
        return
        
    current_idx = st.session_state.history_index
    stack = st.session_state.history_stack
    
    if current_idx >= 0 and current_idx < len(stack):
        if stack[current_idx] == sv_code:
            return
            
    st.session_state.history_stack = stack[:current_idx + 1]
    st.session_state.history_stack.append(sv_code)
    st.session_state.history_index = len(st.session_state.history_stack) - 1
    
    sync_sv_code(sv_code)


def can_undo() -> bool:
    return st.session_state.get("history_index", -1) > 0


def can_redo() -> bool:
    idx = st.session_state.get("history_index", -1)
    stack_len = len(st.session_state.get("history_stack", []))
    return idx >= 0 and idx < stack_len - 1


def undo_history() -> Optional[str]:
    if can_undo():
        st.session_state.history_index -= 1
        new_code = st.session_state.history_stack[st.session_state.history_index]
        sync_sv_code(new_code)
        return new_code
    return None


def redo_history() -> Optional[str]:
    if can_redo():
        st.session_state.history_index += 1
        new_code = st.session_state.history_stack[st.session_state.history_index]
        sync_sv_code(new_code)
        return new_code
    return None


def reset_session() -> None:
    st.session_state.verilog_code = ""
    st.session_state.sv_code = ""
    st.session_state.verilog_key_id = st.session_state.get("verilog_key_id", 0) + 1
    st.session_state.sv_key_id = st.session_state.get("sv_key_id", 0) + 1
    st.session_state.enable_korean_comments = True
    st.session_state.font_size = "Medium"
    st.session_state.progress_step = 0
    st.session_state.summary_metrics = {
        "module_name": "-",
        "inputs_count": 0,
        "outputs_count": 0,
        "converted_lines": 0,
        "logic_conversions": 0,
        "always_conversions": 0,
        "error_count": 0,
        "auto_fix_applied": False
    }
    st.session_state.code_explanation = ""
    st.session_state.detected_errors = []
    st.session_state.history_stack = []
    st.session_state.history_index = -1


# =============================================================================
# 3. ZIP 압축 파일 패키징 유틸리티
# =============================================================================

def create_zip_download_package(
    sv_code: str,
    metrics: Dict[str, Any],
    explanation: str
) -> Tuple[bytes, str]:
    """SystemVerilog 소스 코드와 분석 리포트를 메모리 상에서 ZIP 파일로 압축하여 반환합니다."""
    module_name = metrics.get("module_name") or extract_module_name(sv_code)
    if not module_name or module_name == "-":
        module_name = "converted_module"

    report_md_content = f"""# RTL SystemVerilog 변환 및 분석 리포트

## 1. 모듈 개요 (Module Overview)
- **모듈 이름**: `{module_name}`
- **입력 포트 (Input)**: {metrics.get('inputs_count', 0)} 개
- **출력 포트 (Output)**: {metrics.get('outputs_count', 0)} 개
- **변환된 총 라인 수**: {metrics.get('converted_lines', 0)} 라인

## 2. 변환 통계 (Conversion Metrics)
- **`logic` 타입 전환 건수**: {metrics.get('logic_conversions', 0)} 건
- **`always_ff/comb` 분리 건수**: {metrics.get('always_conversions', 0)} 건
- **탐지된 문법/안전성 오류**: {metrics.get('error_count', 0)} 건
- **AI 오류 자동 보정 적용 여부**: {'예 (Applied)' if metrics.get('auto_fix_applied') else '아니오 (None)'}

## 3. 모듈 구조 및 동작 원리 설명
{explanation if explanation else '모듈 동작 설명이 작성되지 않았습니다.'}

---
*본 문서와 SystemVerilog 소스는 Verilog to SystemVerilog Converter 웹앱에 의해 자동 생성되었습니다.*
"""

    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        sv_filename = f"{module_name}.sv"
        zip_file.writestr(sv_filename, sv_code.encode("utf-8"))
        
        report_filename = f"{module_name}_report.md"
        zip_file.writestr(report_filename, report_md_content.encode("utf-8"))

    zip_bytes = zip_buffer.getvalue()
    zip_filename = f"{module_name}_package.zip"

    return zip_bytes, zip_filename
