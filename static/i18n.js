/* 공유 번역 엔진. 메인 페이지(index.html)와 서버가 생성하는 Lot 보고서/비교 보고서
 * HTML(report.py, compare.py)이 모두 이 스크립트 하나를 로드해서 재사용한다.
 *
 * 두 가지 번역 방식을 지원한다:
 *   1) 고정 라벨: 요소에 data-i18n="key"를 붙이고, 페이지별 dict({key: {ko, en}})를 전달하면
 *      언어에 맞는 텍스트로 교체된다.
 *   2) Lot마다 달라지는 문장(예: 비교 결론): 파이썬이 한국어/영어 버전을 모두 렌더링해두고
 *      data-lang="ko" / data-lang="en"로 감싸면, 선택된 언어만 보이도록 토글된다.
 *      (AI가 생성하는 해석·개선 권고는 번역 API 없이는 자동 번역할 수 없어 한국어로만 존재하며
 *       이 매커니즘의 대상이 아니다.)
 */

const I18N_STORAGE_KEY = "line-simulator-lang";

function i18nGetLang() {
  return localStorage.getItem(I18N_STORAGE_KEY) || "ko";
}

function i18nSetLang(lang) {
  localStorage.setItem(I18N_STORAGE_KEY, lang);
}

function i18nApply(dict, lang) {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const entry = dict[el.dataset.i18n];
    if (entry && entry[lang] != null) el.textContent = entry[lang];
  });
  document.querySelectorAll("[data-lang]").forEach((el) => {
    el.hidden = el.dataset.lang !== lang;
  });
  document.documentElement.lang = lang === "en" ? "en" : "ko";
}

/**
 * 언어 토글 버튼(#langToggleBtn)을 초기화하고, 저장된 언어를 즉시 적용한다.
 * @param {object} dict - 고정 라벨 번역 사전 {key: {ko, en}}
 * @param {(lang: string) => void} [onChange] - 언어가 바뀔 때마다 호출(동적 콘텐츠 재렌더링용)
 * @returns {{getLang: () => string}}
 */
function i18nSetup(dict, onChange) {
  const btn = document.getElementById("langToggleBtn");

  function render(lang) {
    i18nApply(dict, lang);
    if (btn) btn.textContent = lang === "ko" ? "EN" : "한국어";
    if (onChange) onChange(lang);
  }

  render(i18nGetLang());

  if (btn) {
    btn.addEventListener("click", () => {
      const next = i18nGetLang() === "ko" ? "en" : "ko";
      i18nSetLang(next);
      render(next);
    });
  }

  return { getLang: i18nGetLang };
}
