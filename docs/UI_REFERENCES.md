# Backspace AI Workspace — 2026-10-06

## 조사한 공식 레퍼런스

- [Linear: A calmer interface for a product in motion](https://linear.app/now/behind-the-latest-design-refresh) — 2026-03-12. 낮은 대비의 사이드바, 작은 아이콘, 일정한 헤더, 부드러운 경계를 참고했다. 공식 글에 포함된 사이드바 전후 이미지도 브라우저에서 확인했다.
- [Google: NotebookLM interface redesign](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-new-features-december-2024/) — 2024-12-13의 디자인 사례. 자료 관리와 생성 작업을 구분하고, 원문과 편집기를 나란히 보여주는 구성을 참고했다. 현재 서비스의 모든 화면이 동일하다고 가정하지 않는다.
- [Claude: Artifacts](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them) — 작업 결과를 별도 영역에서 보고 편집하는 방식을 확인했다.

## Backspace에 적용한 결정

- 녹색 기운이 강했던 화면을 중성 차콜로 정리하고 주요 행동에 라임을 사용한다.
- 메뉴의 선택 상태는 낮은 대비로 표시한다. 카드와 구분선의 시각적 비중을 줄인다.
- 데스크톱 자료 화면은 목록을 왼쪽, 업로드와 처리 작업을 오른쪽에 둔다. 모바일은 업로드를 먼저 보여준다.
- 자료 이름 검색은 저장된 목록을 브라우저에서 필터링한다. 검색어와 목록 스크롤은 상태 갱신 시 유지한다.
- 홈은 짧은 환영 제목, 실제 다음 행동, 상태 수치, 빠른 이동으로 구성한다.
- 원문, 근거, 오류, 확인 대기 상태는 계속 제공한다. 기존 자료 공간과 100MB 업로드 제한을 유지한다.

스타일은 `web_static/studio.css`, 화면 구성은 기존 Vanilla JavaScript 모듈에 있다. 검색은 로컬 화면 기능이며 새 AI 호출을 추가하지 않았다.
