import os
import json
from typing import List

class OpenAILawKeywordExtractor:
    """
    OpenAI gpt-4o-mini 모델을 사용하여 사용자 질문에서 
    법률 검색용 핵심 키워드를 추출하는 2차 방어망 (Fallback) 클래스입니다.
    """
    def __init__(self):
        try:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print("[Warning] OPENAI_API_KEY가 설정되지 않아 LLM Fallback이 비활성화됩니다.")
                self.client = None
            else:
                self.client = OpenAI(api_key=api_key)
        except ImportError:
            print("[Warning] openai 패키지가 설치되지 않아 LLM Fallback이 비활성화됩니다.")
            self.client = None

    def extract_legal_keywords(self, text: str) -> List[str]:
        if not self.client or not text.strip():
            return []
            
        system_prompt = (
            "너는 대한민국 법률 검색을 위한 키워드 추출기야. "
            "사용자의 비공식적, 일상적 질문에서 도로교통법 등 법령 검색에 사용될 "
            "핵심 법률 용어(키워드) 3~5개를 추출해 줘. "
            "결과는 반드시 순수 JSON 배열 형식으로 반환해야 해. (예: [\"신호위반\", \"범칙금\", \"교차로\"])"
        )
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.0,
                max_tokens=50
            )
            
            result_text = response.choices[0].message.content.strip()
            # 마크다운 백틱 등 제거 (만약 출력되었다면)
            if result_text.startswith("```json"):
                result_text = result_text.replace("```json", "").replace("```", "").strip()
            elif result_text.startswith("```"):
                result_text = result_text.replace("```", "").strip()
                
            keywords = json.loads(result_text)
            if isinstance(keywords, list):
                return [str(k) for k in keywords]
            return []
            
        except Exception as e:
            print(f"[LLM Fallback Error] 키워드 추출 실패: {e}")
            return []

    def format_api_response(self, provisions: list, input_context: dict) -> dict:
        if not self.client: return {}
        system_prompt = (
            "당신은 법률 정보 요약 및 판단기입니다. 제공된 'Input Context'와 "
            "'Provisions(조문)'을 분석하여 다음 JSON 스키마에 맞게 결과를 출력하세요.\n"
            "{\n"
            "  \"law_code\": \"대표적인 법령 코드\",\n"
            "  \"violation_text\": \"위반 행위 요약\",\n"
            "  \"matched_laws\": [{\"title\": \"법령명\", \"article\": \"조항\", \"summary\": \"조항 요약\", \"source_ref\": \"해당 조문의 chunk_id\"}],\n"
            "  \"reduction_eligible\": true/false,\n"
            "  \"reduction_rate\": 0.2 등 (없으면 null),\n"
            "  \"special_reduction\": false (또는 null),\n"
            "  \"objection_possible\": true/false/null (사전통지/1차고지면 true, 2차고지면 false),\n"
            "  \"missing_documents\": [\"추가 증빙 서류명\"],\n"
            "  \"applicable_reductions\": [\"감경 사유\"],\n"
            "  \"inapplicable_reductions\": [],\n"
            "  \"objection_reason\": \"이의신청 추정 사유 (없으면 null)\"\n"
            "}\n"
            "오직 JSON만 출력하세요."
        )
        user_prompt = f"Input Context:\n{json.dumps(input_context, ensure_ascii=False)}\n\nProvisions:\n"
        for p in provisions:
            user_prompt += f"- {p.get('source_name', '')} {p.get('article_no', '')}: {p.get('provision_text', '')} (chunk_id: {p.get('chunk_id', '')})\n"
            
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content.strip())
        except Exception as e:
            print(f"[LLM Formatter Error] 포맷팅 실패: {e}")
            return {}

