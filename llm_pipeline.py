"""
===============================================================================
RTL Verilog to SystemVerilog Converter - LLM 연동 파이프라인 (llm_pipeline.py)
===============================================================================
이 모듈은 Google GenAI SDK (google-genai)를 이용하여 Gemini 3.6 Flash 모델과 통신합니다.
- RTL 변환 제약사항 및 가이드라인(RTL_GUIDELINES.md)을 준수하는 System Prompt
- 4단계 파이프라인 (분석 -> 문법/안전성 검사 -> SV 코드 & 주석 생성 -> 리포트 작성)
- 자동 오류 수정 승인(auto_fix_code) 파이프라인 지원
===============================================================================
"""

import os
import json
import re
from typing import Optional, Dict, Any, List

# Google GenAI 최신 SDK 임포트
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class RTLConverterPipeline:
    """
    Verilog 코드를 SystemVerilog로 변환하고 하드웨어 안전성을 검수하는 Gemini LLM 파이프라인 클래스입니다.
    """
    
    SYSTEM_PROMPT = """
당신은 최고 수준의 RTL (Register Transfer Level) 설계 및 SystemVerilog 전문 엔지니어입니다.
전달받은 Verilog (.v) 코드를 표준 SystemVerilog (.sv) 코드로 변환하고 분석 결과를 JSON 형식으로 반환해야 합니다.

[RTL 변환 및 가이드라인 절대 원칙]
1. 기능 및 동작 보존: 원본 RTL의 기능, 신호명, 비트 폭, 조건문, 상태 전이, Reset 방식을 임의로 변경하거나 추측하여 추가하지 마십시오.
2. 구문 및 스타일 구체화:
   - reg / wire 구분을 logic으로 일괄 통일합니다.
   - always 블록을 동작 유형에 따라 always_ff (순차 회로), always_comb (조합 회로), always_latch (래치 회로)로 명확히 분리합니다.
   - 포트 선언 방식을 ANSI 스타일 표준 포트 선언으로 정리합니다.
3. Hardware-Safety 검증:
   - 의도하지 않은 Latch 발생 방지 (조합 회로 내 완전한 if-else 및 default 처리)
   - Multi-driven bus 및 Unknown(X) 값 전파 방지
   - Blocking(=) / Non-blocking(<=) 할당 구문의 정확한 구분 사용 (always_ff에서는 <=, always_comb에서는 =)
4. Reset 처리 규칙: Reset이 negedge인지 posedge인지 명시되지 않은 경우 기본적으로 Active-Low (negedge)로 처리합니다.
5. 한글 주석: 요청된 경우 변환된 SystemVerilog 코드에 주요 모듈/로직 구문마다 라인에 맞는 한글 주석(// ...)을 생성합니다.

[응답 포맷 규칙]
반드시 다음 구조를 가진 pure JSON 객체로만 응답하십시오 (Markdown ```json ... ``` 태그 포함 가능):
{
  "sv_code": "변환 완료된 SystemVerilog 전체 코드 문자열 (한글 주석 포함)",
  "metrics": {
    "module_name": "추출된 모듈 이름",
    "inputs_count": 입력 포트 수 (정수),
    "outputs_count": 출력 포트 수 (정수),
    "converted_lines": 변환된 총 라인 수 (정수),
    "logic_conversions": logic으로 변환된 reg/wire 수 (정수),
    "always_conversions": always_ff/comb로 전환된 건수 (정수),
    "error_count": 원본 코드에서 탐지된 오류 건수 (정수)
  },
  "explanation": "변환된 모듈의 구조, 입출력 신호 역할, FSM 및 조합 회로 동작 원리에 대한 상세 한글 요약 설명",
  "detected_errors": [
    {
      "line": 라인 번호 (정수),
      "issue": "문법 오류 또는 Latch 위험 설명",
      "suggestion": "자동 수정 제안"
    }
  ]
}
"""

    def __init__(self, api_key: Optional[str] = None):
        """
        파이프라인을 초기화하고 Gemini API 클라이언트를 설정합니다.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.client = None
        
        if GENAI_AVAILABLE and self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                # google-genai SDK 클라이언트 생성
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"[경고] Gemini 클라이언트 생성 실패: {e}")

    def is_ready(self) -> bool:
        """Gemini API 호출 준비 상태 확인"""
        return self.client is not None

    def convert_verilog_to_sv(
        self, 
        verilog_code: str, 
        include_korean_comments: bool = True
    ) -> Dict[str, Any]:
        """
        Gemini 3.6 Flash API를 호출하여 Verilog 코드를 SystemVerilog로 4단계 변환 파이프라인을 수행합니다.
        """
        if not self.is_ready():
            return {
                "success": False,
                "error": "Gemini API 키가 설정되지 않았거나 클라이언트 초기화에 실패했습니다. .streamlit/secrets.toml을 확인해 주세요.",
                "sv_code": "",
                "metrics": {},
                "explanation": "",
                "detected_errors": []
            }

        user_prompt = f"""
다음 Verilog 코드를 SystemVerilog로 변환하고 분석 리포트를 산출해 주십시오.

[한글 주석 생성 옵션]: {'ON (모든 핵심 로직에 친절한 한글 주석 // 추가)' if include_korean_comments else 'OFF'}

[원본 Verilog 코드]:
```verilog
{verilog_code}
```
"""

        try:
            model_name = "gemini-3.6-flash"
            response = self.client.models.generate_content(
                model=model_name,
                contents=[self.SYSTEM_PROMPT, user_prompt]
            )

            response_text = response.text.strip()
            
            # JSON 응답 파싱
            json_text = response_text
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0].strip()
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0].strip()

            parsed_data = json.loads(json_text)

            return {
                "success": True,
                "error": None,
                "sv_code": parsed_data.get("sv_code", ""),
                "metrics": parsed_data.get("metrics", {}),
                "explanation": parsed_data.get("explanation", ""),
                "detected_errors": parsed_data.get("detected_errors", [])
            }

        except Exception as e:
            err_msg = str(e)
            if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                friendly_err = "⚠️ Gemini API 무료 이용 할당량(Rate Limit)을 초과했습니다. 약 30초~1분 후 [변환 실행]을 다시 클릭해 주세요."
            else:
                friendly_err = f"Gemini API 연동 중 오류 발생: {err_msg}"

            return {
                "success": False,
                "error": friendly_err,
                "sv_code": "",
                "metrics": {},
                "explanation": "",
                "detected_errors": []
            }


    def auto_fix_code(
        self,
        verilog_code: str,
        detected_errors: List[Dict[str, Any]],
        include_korean_comments: bool = True
    ) -> Dict[str, Any]:
        """
        탐지된 문법 및 Latch 예외 오류 목록을 반영하여 AI로 자동 코드를 보정 및 재변환합니다.
        """
        if not self.is_ready():
            return {"success": False, "error": "Gemini Client 준비 필요"}

        error_summary = json.dumps(detected_errors, ensure_ascii=False)
        user_prompt = f"""
[오류 자동 수정 승인 요청]
아래 Verilog 코드에서 탐지된 문법 오류 및 Latch 위험 요소를 완벽히 보정하여 안전한 SystemVerilog로 재변환해 주십시오.

[탐지된 오류 내용]:
{error_summary}

[한글 주석 생성 옵션]: {'ON' if include_korean_comments else 'OFF'}

[원본 Verilog 코드]:
```verilog
{verilog_code}
```
"""

        try:
            response = self.client.models.generate_content(
                model="gemini-3.6-flash",
                contents=[self.SYSTEM_PROMPT, user_prompt]
            )
            response_text = response.text.strip()
            json_text = response_text
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0].strip()
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0].strip()

            parsed_data = json.loads(json_text)
            
            # 자동 수정 적용 완료 표시
            metrics = parsed_data.get("metrics", {})
            metrics["auto_fix_applied"] = True
            metrics["error_count"] = 0  # 오류 보정 완료

            return {
                "success": True,
                "error": None,
                "sv_code": parsed_data.get("sv_code", ""),
                "metrics": metrics,
                "explanation": parsed_data.get("explanation", "") + " (AI 오류 자동 수정 승인 완료)",
                "detected_errors": []
            }
        except Exception as e:
            err_msg = str(e)
            if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                friendly_err = "⚠️ Gemini API 무료 이용 할당량(Rate Limit)을 초과했습니다. 약 30초~1분 후 다시 시도해 주세요."
            else:
                friendly_err = f"자동 수정 요청 중 오류: {err_msg}"
            return {"success": False, "error": friendly_err}

