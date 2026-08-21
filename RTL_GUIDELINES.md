# RTL 처리 원칙
- 원본 RTL의 기능과 동작을 유지해서 SystemVerilog로 변환
- 신호명, 비트 폭, 조건문, 상태 전이, reset 방식 등을
  임의로 변경하지 않음
- 코드에 없는 기능이나 내용을 임의로 추측하지 않음
- 코드 설명과 한글 주석은 변환된 SystemVerilog 기준으로
  정확하게 생성
- 주석은 실제 코드와 맞는 위치에 작성
- 상승/하강 엣지, 동기/비동기 reset, blocking/nonblocking을
  정확하게 구분
- 의도하지 않은 latch가 발생하지 않도록 주의
- multi driven이 발생하지 않도록 주의
- Unknown 값이 전파되지 않도록 주의
- Reset이 negedge인지 posedge인지 정해지지 않았다면 negedge로 처리

# Testbench 생성 원칙
- 변환된 SystemVerilog 기준으로 생성
- reset, enable, 상태 전이, 상태 유지, 카운터, 경계값,
  case/default 등 RTL에 있는 주요 조건을 가능한 한 검증
- 입력 비트 위치와 실제 입력값이 정확히 일치하도록 생성
- FSM의 상태 전이 조건과 예상 결과가 RTL과 맞는지 확인
- 비동기 reset이 있으면 해당 동작도 검증
- 출력값이 안정된 시점에서 결과를 확인
- 주요 테스트 결과는 PASS / FAIL로 확인
- 큰 카운터 값이라는 이유만으로 주요 테스트를 임의로 생략 X
- Testbench 생성 후 입력값, 예상 결과, 주석이
  RTL과 맞는지 다시 확인