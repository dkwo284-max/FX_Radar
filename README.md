# FX Radar

NZD/KRW 환율 추이와 송금 타이밍을 보여 주는 개인 앱입니다. https://dkwo284-max.github.io/FX_Radar/

- 데이터: ECB 기준환율(frankfurter.dev) 2년치, 평일 하루 1회. 업체별 송금 견적은 Wise 공개 비교 API가 응답할 때만.
- 신호: 지금 환율이 최근 1년 중 어디쯤인지(백분위)와 30·90일 평균 대비 흐름. 예측이 아니라 위치입니다.
- 목표 환율: `config.json` 의 `alerts` 에 원 단위로 넣으면, 그 선을 넘는 날 기록되고 My Hub 경고에 뜹니다.
  저장소 Secrets 에 `TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID` 가 있으면 텔레그램으로도 보냅니다.
- 갱신: `.github/workflows/update.yml` (평일 UTC 16:37, 예비 20:07). AI 사용 0회.
- 로컬 확인: `python scripts/fx.py && python -m http.server -d web 8000`
