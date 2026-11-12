# 공모전 API 계약 검증

공모전 API 계약의 원본은 [openapi.json](openapi.json)입니다. 경로나 응답 필드를 변경한 뒤 생성 파일을 갱신하고 검증합니다.

~~~powershell
python tools/api_contract.py generate
python tools/api_contract.py describe GET /api/contests
python tools/api_contract.py check
python -m unittest discover -s tests -p 'test_*.py'
~~~

화면 코드는 public/contest-api.js를 통해 API를 호출합니다. 검사 명령은 계약과 생성 파일의 불일치, 어댑터 밖의 직접 fetch 호출을 발견하면 실패합니다. 테스트에는 로컬 HTTP 요청과 가상 데이터가 사용됩니다.
