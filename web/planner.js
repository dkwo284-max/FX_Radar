// 큰돈 송금 플래너: 한국 → 뉴질랜드 (기본 ₩10억). AI 없음. 환율은 fx.json 의 ECB 기준환율을 쓰고,
// 경로별 비용은 '예시 가정'으로 시작해 사용자가 실제 은행 고시·우대율로 바꿔 넣는다(이 브라우저에만 저장).
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const won = (v) => `${Math.round(v).toLocaleString('ko-KR')}원`;
  const nzd = (v) => `NZ$${Math.round(v).toLocaleString('en-NZ')}`;
  const KEY = 'fx.planner.v1';

  // 송금 목적별: 신고 경로와 서류 (공식·은행 안내 기준 요약, 원문 링크 포함)
  const PURPOSE = {
    emig: { l: '해외이주비 (이주 정착)', route: '해외이주자 송금 — 금액 제한 없음, 단 세무서 자금출처확인서 범위 안',
      steps: ['재외동포청 해외이주신고 → 해외이주신고확인서 발급 (현지이주라면 현지이주확인서)',
        '송금할 은행 한 곳을 거래외국환은행으로 지정 (지정신청서 + 여권·비자/영주권 사본)',
        '관할 세무서에서 해외이주비 자금출처확인서 발급 (통상 10일 안팎, 확인서 금액까지 송금 가능)',
        '지정 은행에서 NZD(또는 USD) 전신송금 — 받는 계좌는 본인 명의 NZ 은행 계좌',
        'NZ 은행이 자금출처를 물으면 자금출처확인서·한국 은행 거래내역·매각 계약서 등을 영문으로 준비'],
      links: [['우리은행 해외이주자 송금 안내', 'https://spot.wooribank.com/pot/Dream?withyou=FXFCE0026']] },
    home: { l: '뉴질랜드 집 구입', route: '거주자 해외부동산 취득 — 송금 전 지정거래외국환은행 신고(수리) 필수',
      steps: ['매매계약 전후로 은행에 해외부동산 취득 신고 (신고 전 선지급 불가, 공동명의 제한 확인)',
        '신고 수리 후 매매대금을 NZ 변호사 신탁계좌(trust account) 또는 본인 계좌로 송금',
        '소유권 이전 뒤 3개월 안에 은행에 취득보고, 이후 처분·보유 보고',
        '취득가 2억 원 이상이면 다음 해 6월 말까지 국세청에 해외부동산 명세서 제출',
        'NZ 쪽: 외국인 주택 구입 제한(Overseas Investment) 대상인지 변호사와 먼저 확인 — 거주비자 상태에 따라 다름'],
      links: [['국세청 해외부동산과 세금(개인투자자용)', 'https://www.taxnet.co.kr/upload-file-domain/20266/2025년_해외부동산과_세금_개인투자자용_a338fa33.pdf'], ['NZ Overseas Investment (LINZ)', 'https://www.linz.govt.nz/guidance/overseas-investment']] },
    invest: { l: '예금·투자 이전', route: '거주자 해외예금·해외증권투자 — 은행에 신고하거나 증빙을 내고 송금',
      steps: ['송금 목적(해외예금/해외증권투자)에 맞춰 지정 은행에 신고', '누계 미화 10만 달러를 넘는 예금 자금은 세무서 자금출처확인서가 필요할 수 있음',
        'NZ 계좌 잔액이 매월 말 기준 5억 원을 넘은 달이 있으면 다음 해 6월 국세청 해외금융계좌 신고 (한국 거주자인 동안)'],
      links: [['국세청 해외금융계좌 신고 안내', 'https://www.nts.go.kr/nts/na/ntt/selectNttInfo.do?mi=2201&nttSn=93325']] },
    living: { l: '생활비·학비 분할', route: '증빙 없는 송금 — 2026년부터 전 금융권 합산 연 미화 10만 달러',
      steps: ['은행·소액송금업체·증권사·카드사 송금이 모두 합산되어 연 10만 달러 한도 (1월 1일에 초기화)',
        '학비·체재비는 입학허가서·재학증명서 등 증빙을 내면 한도와 별개로 송금 가능',
        '비거주자로 바뀐 뒤에는 증빙 없는 송금을 쓸 수 없음 — 이주 전에 계획'],
      links: [['무증빙 해외송금 한도 통합 (세정일보)', 'https://taxtimes.co.kr/mobile/article.html?no=272760']] },
  };

  // 송금 경로 (안전·규정 준수 순). cost: 기본 가정값 — 화면에서 바꿀 수 있음
  const ROUTES = [
    { id: 'bank_nzd', l: '한국 은행 → NZD 직접 송금', safe: '높음', speed: '1~3 영업일',
      limit: '증빙·신고 범위 안에서 제한 없음', fits: ['emig', 'home', 'invest', 'living'],
      note: '거래외국환은행 신고 경로를 그대로 쓸 수 있어 큰 금액에 가장 무난합니다. 비용은 환율 우대율에 크게 좌우됩니다.',
      cost: { spread: 0.5, feeKRW: 10000, feeNZD: 40 } },
    { id: 'bank_usd', l: '한국 은행 → USD 송금 → NZ 은행 환전', safe: '높음', speed: '1~3 영업일 + NZ 환전',
      limit: '위와 같음', fits: ['emig', 'home', 'invest', 'living'],
      note: '원화→달러 우대가 좋을 때 쓰지만, NZ 은행에서 달러→NZD를 한 번 더 바꾸는 비용이 붙습니다.',
      cost: { spread: 0.3, spread2: 1.0, feeKRW: 10000, feeNZD: 40 } },
    { id: 'fxfirm', l: '외환 전문업체 (OFX 등)', safe: '확인 필요', speed: '1~5 영업일',
      limit: '한국 출발 원화 송금 지원 여부 미확인', fits: [],
      note: '한국 거주자가 원화로 보내는 경로는 공식 지원이 확인되지 않았습니다. 쓰려면 업체와 한국 신고 요건 충족 여부를 먼저 확인해야 합니다. 이 화면은 비용만 참고로 계산합니다.',
      cost: { spread: 0.6, feeKRW: 0, feeNZD: 15 } },
    { id: 'smallremit', l: '국내 소액송금업체 (모인 등)', safe: '보통', speed: '당일~2 영업일',
      limit: '증빙 없는 송금 연 미화 10만 달러 (전 금융권 합산)', fits: ['living'],
      note: 'Wise는 한국에서 원화를 보내는 송금을 지원하지 않습니다. 국내 소액송금업체는 생활비 분할에만 맞고, 10억 같은 큰돈은 한도 때문에 쓸 수 없습니다.',
      cost: { spread: 0.4, feeKRW: 5000, feeNZD: 15 } },
  ];

  let st = { amount: 1000000000, purpose: 'emig', splits: 1, months: 6, cost: {} };
  try { const s = JSON.parse(localStorage.getItem(KEY) || 'null'); if (s) st = { ...st, ...s }; } catch (e) { /* 저장 불가 */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) { /* 저장 불가 */ } };
  const C = (r) => ({ ...r.cost, ...(st.cost[r.id] || {}) });

  /** 한 번 보낼 때 받는 NZD: 원화 → (스프레드) → NZD, 고정 수수료 차감 */
  function received(r, krw, rate) {
    const c = C(r);
    let v = (krw - (c.feeKRW || 0)) / rate * (1 - (c.spread || 0) / 100);
    if (c.spread2) v *= 1 - c.spread2 / 100;
    return Math.max(0, v - (c.feeNZD || 0));
  }

  function render(D) {
    const box = $('#planner');
    if (!box || !D) return;
    const rate = D.pairs.KRW.last, pct = D.pairs.KRW.pct1y;
    const ideal = st.amount / rate;
    const P = PURPOSE[st.purpose];
    const rows = ROUTES.map((r) => {
      const n = r.id === 'smallremit' ? Math.max(st.splits, 1) : st.splits;
      const per = st.amount / n;
      const got = received(r, per, rate) * n;
      const capKRW = 100000 / (D.pairs.USD?.last || 0.6) * rate; // 미화 10만 달러의 원화 환산(대략)
      const blocked = r.id === 'smallremit' && st.amount > capKRW;
      const fit = r.fits.includes(st.purpose);
      return { r, got, loss: ideal - got, blocked, fit, capKRW };
    });
    const ok = rows.filter((x) => x.fit && !x.blocked);
    const best = ok.length ? ok.reduce((a, b) => (b.got > a.got ? b : a)) : null;
    const safest = ok[0] || null;

    // 분할 시뮬레이터: 환율이 지금 대비 -5% ~ +5% 사이에서 움직일 때 받는 NZD 범위 (선택한 경로 기준)
    const route = safest ? safest.r : ROUTES[0];
    const scen = [-5, -2.5, 0, 2.5, 5].map((m) => {
      const r2 = rate * (1 + m / 100);
      return { m, one: received(route, st.amount, r2) };
    });
    const split = st.splits > 1;
    // 분할: 환율이 기간 동안 한 방향으로 고르게 ±5% 움직인다고 가정하면 평균 적용 환율은 약 ±2.5% — 회당 수수료는 횟수만큼
    const splitGot = (m) => received(route, st.amount / st.splits, rate * (1 + m / 100)) * st.splits;
    const avgRange = split ? [splitGot(2.5), splitGot(-2.5)] : null;

    box.innerHTML = `
      <h2>큰돈 송금 플래너 <span class="hint">한국 → 뉴질랜드</span></h2>
      <div class="calc">
        <label for="p-amt">보낼 금액 (원)<input id="p-amt" type="number" min="0" step="10000000" value="${st.amount}" inputmode="numeric"></label>
        <label for="p-pur">송금 목적<select id="p-pur">${Object.entries(PURPOSE).map(([k, v]) => `<option value="${k}"${k === st.purpose ? ' selected' : ''}>${esc(v.l)}</option>`).join('')}</select></label>
        <label for="p-spl">나눠 보낼 횟수<input id="p-spl" type="number" min="1" max="24" step="1" value="${st.splits}"></label>
        <label for="p-mon">기간 (개월)<input id="p-mon" type="number" min="1" max="24" step="1" value="${st.months}"></label>
      </div>
      <div class="sigs">
        <div class="sig g"><span class="hint">가장 안전한 경로 (추천)</span><b>${safest ? esc(safest.r.l) : '해당 경로 없음'}</b><span class="hint">${safest ? `받는 금액 약 ${nzd(safest.got)} · 비용 약 ${nzd(safest.loss)}` : '목적에 맞는 경로가 없습니다'}</span></div>
        <div class="sig"><span class="hint">가정 기준 가장 싼 경로</span><b>${best ? esc(best.r.l) : '—'}</b><span class="hint">${best ? `받는 금액 약 ${nzd(best.got)}` : ''}</span></div>
      </div>
      <p class="hint">기준환율로 계산한 이론값 ${nzd(ideal)} (NZ$1 = ${rate.toFixed(2)}원). 아래 비용은 예시 가정이니 '비용 가정 바꾸기'에서 은행 고시 환율 우대율로 바꿔 넣으세요.</p>

      <h3 class="ph">경로 비교 <span class="hint">안전·규정 준수 순</span></h3>
      <div class="tbl"><table><thead><tr><th>경로</th><th>안전성</th><th class="r">받는 금액</th><th class="r">비용</th><th>소요</th><th>한도</th></tr></thead><tbody>
        ${rows.map((x) => `<tr class="${!x.fit || x.blocked ? 'dim' : ''}"><td><b>${esc(x.r.l)}</b>${!x.fit ? '<br><small>이 목적에 맞지 않음</small>' : x.blocked ? '<br><small>한도 초과</small>' : ''}</td><td>${esc(x.r.safe)}</td>
          <td class="r num">${nzd(x.got)}</td><td class="r num">${nzd(x.loss)}<br><small>${(x.loss / ideal * 100).toFixed(2)}%</small></td><td>${esc(x.r.speed)}</td><td><small>${esc(x.r.limit)}</small></td></tr>`).join('')}
      </tbody></table></div>
      <ul class="pnotes">${ROUTES.map((r) => `<li><b>${esc(r.l)}</b>: ${esc(r.note)}</li>`).join('')}</ul>

      <details class="pdet"><summary>비용 가정 바꾸기</summary>
        <p class="hint">스프레드는 기준환율 대비 실제 적용 환율 차이(%)입니다. 은행 전신환 매도율과 우대율을 보고 넣으세요. 중개·수취 수수료는 받는 쪽에서 빠지는 금액(NZ$)입니다.</p>
        <div class="tbl"><table><thead><tr><th>경로</th><th>스프레드 %</th><th>2차 환전 %</th><th>보내는 수수료 (원)</th><th>중개·수취 (NZ$)</th></tr></thead><tbody>
          ${ROUTES.map((r) => { const c = C(r); return `<tr><td>${esc(r.l)}</td>
            <td><input data-c="${r.id}:spread" type="number" step="0.05" min="0" max="5" value="${c.spread}"></td>
            <td>${r.cost.spread2 != null ? `<input data-c="${r.id}:spread2" type="number" step="0.05" min="0" max="5" value="${c.spread2}">` : '—'}</td>
            <td><input data-c="${r.id}:feeKRW" type="number" step="1000" min="0" value="${c.feeKRW}"></td>
            <td><input data-c="${r.id}:feeNZD" type="number" step="5" min="0" value="${c.feeNZD}"></td></tr>`; }).join('')}
        </tbody></table></div>
        <button type="button" id="p-reset">가정 되돌리기</button>
      </details>

      <h3 class="ph">분할 송금 시뮬레이터 <span class="hint">${esc(route.l)} 기준</span></h3>
      <p class="hint">지금 NZD/KRW는 1년 중 ${pct >= 50 ? `상위 ${Math.max(1, Math.round(100 - pct))}%` : `하위 ${Math.max(1, Math.round(pct))}%`}입니다. 원화를 NZD로 바꾸는 쪽은 환율이 낮을수록 유리합니다.</p>
      <div class="tbl"><table><thead><tr><th>환율 변화</th>${scen.map((s) => `<th class="r">${s.m > 0 ? '+' : ''}${s.m}%</th>`).join('')}</tr></thead><tbody>
        <tr><td>한 번에 전액</td>${scen.map((s) => `<td class="r num">${nzd(s.one)}</td>`).join('')}</tr></tbody></table></div>
      <p class="hint">${split ? `${st.splits}번으로 ${st.months}개월에 나눠 보내면: 환율이 그동안 한 방향으로 고르게 ±5% 움직인다고 가정할 때 받는 금액은 ${nzd(avgRange[0])} ~ ${nzd(avgRange[1])} (한 번에 보내면 ${nzd(scen[4].one)} ~ ${nzd(scen[0].one)}). 결과의 폭이 줄어드는 대신 회당 고정 수수료가 ${st.splits}번 붙습니다.` : '나눠 보낼 횟수를 2 이상으로 바꾸면 분할했을 때의 결과 폭을 함께 보여 드립니다.'} 환율 방향을 예측하지 않으며, 과거 위치만 참고합니다.</p>

      <h3 class="ph">단계별 체크리스트 <span class="hint">${esc(P.l)}</span></h3>
      <p class="hint">${esc(P.route)}</p>
      <ol class="pchk">${P.steps.map((s, i) => `<li><label><input type="checkbox" data-chk="${st.purpose}:${i}"${(st.done || {})[`${st.purpose}:${i}`] ? ' checked' : ''}> ${esc(s)}</label></li>`).join('')}</ol>
      <p class="hint">${P.links.map(([t, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>`).join(' · ')}</p>

      <h3 class="ph">세금·신고 주의사항</h3>
      <ul class="pnotes">
        <li><b>해외금융계좌 신고</b>: 한국 거주자인 동안, NZ 계좌 잔액 합계가 매월 말 중 하루라도 5억 원을 넘으면 다음 해 6월에 국세청 신고. 미신고 과태료가 큽니다. <a href="https://www.nts.go.kr/nts/na/ntt/selectNttInfo.do?mi=2201&nttSn=93325" target="_blank" rel="noopener">국세청 안내</a></li>
        <li><b>해외부동산 명세서</b>: 취득가 2억 원 이상 해외부동산은 다음 해 6월 말까지 명세서 제출. 은행 신고와 별개입니다.</li>
        <li><b>자금출처</b>: 한국에서는 세무서 자금출처확인서, NZ에서는 은행의 자금출처(Source of funds) 확인을 받습니다. 집 매각·예금 해지 서류를 영문과 함께 준비하면 지연이 줄어듭니다. <a href="https://www.anz.co.nz/sourcewealthfunds" target="_blank" rel="noopener">ANZ 자금출처 안내</a></li>
        <li><b>거주자 판정</b>: 송금 시점에 한국 거주자인지 비거주자인지에 따라 쓸 수 있는 경로가 달라집니다(비거주자는 증빙 없는 송금 불가). 이주 일정과 함께 은행·세무사에게 확인하세요.</li>
        <li><b>증여 주의</b>: 가족 명의 계좌로 보내면 증여로 볼 수 있습니다. 받는 계좌는 본인 명의로 하세요.</li>
      </ul>
      <p class="hint">이 화면은 공식 안내와 은행 자료를 요약한 참고용 계획 도구이며 법률·세무 자문이 아닙니다. 실제 송금 전 지정 은행과 세무 전문가에게 확인하세요.</p>`;

    const num = (id, f) => $(id).addEventListener('change', (e) => { f(+e.target.value || 0); save(); render(D); });
    num('#p-amt', (v) => { st.amount = Math.max(0, v); });
    num('#p-spl', (v) => { st.splits = Math.max(1, Math.min(24, Math.round(v))); });
    num('#p-mon', (v) => { st.months = Math.max(1, Math.min(24, Math.round(v))); });
    $('#p-pur').addEventListener('change', (e) => { st.purpose = e.target.value; save(); render(D); });
    box.querySelectorAll('[data-c]').forEach((el) => el.addEventListener('change', () => {
      const [id, k] = el.dataset.c.split(':');
      st.cost[id] = { ...(st.cost[id] || {}), [k]: Math.max(0, +el.value || 0) };
      save(); render(D); const d = $('#planner .pdet'); if (d) d.open = true;
    }));
    box.querySelectorAll('[data-chk]').forEach((el) => el.addEventListener('change', () => {
      st.done = { ...(st.done || {}), [el.dataset.chk]: el.checked }; save();
    }));
    $('#p-reset').addEventListener('click', () => { st.cost = {}; save(); render(D); });
  }

  window.addEventListener('fx:data', (e) => render(e.detail));
  if (window.__FX) render(window.__FX);
})();
